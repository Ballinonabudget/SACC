"""
kicksdb_enricher.py — SACC × KicksDB Post-Processing Enrichment
================================================================
Runs after Stage 8a (Gemini) has extracted the SKU from video.
Takes that SKU, hits the KicksDB API, and writes authoritative product
metadata directly into the clip record:

  • Model            — canonical marketing name (KicksDB wins over Gemini)
  • Colorway         — standardised colorway string
  • Release date     — official launch date (YYYY-MM-DD or YYYY)
  • MSRP / Price_Retail — manufacturer suggested retail price
  • Brand            — verified brand name

All raw KicksDB fields are also namespaced `kdb_*` for auditability.
Secondary-market pricing (StockX/GOAT asks) is intentionally excluded
from the schema per the SACC spec.

Hash-wall discount computation
-------------------------------
When Is_Hash_Wall is true and both a KicksDB MSRP and a Gemini-observed
outlet price are present, this module computes:

  hash_wall_discount_pct  — integer percentage saved vs MSRP (e.g. 65)
  hash_wall_msrp          — MSRP used in the calculation (e.g. "$190")
  hash_wall_outlet_price  — observed outlet price (e.g. "$59")

Environment
-----------
  KICKSDB_API_KEY   — Required. Set in .env.
  KICKSDB_BASE_URL  — Optional. Defaults to https://api.kicks.dev/v3

Usage (standalone test)
-----------------------
  python kicksdb_enricher.py 555088-101
  python kicksdb_enricher.py DZ5485-612
"""

import os
import time
import json
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

KICKSDB_API_KEY  = os.getenv("KICKSDB_API_KEY", "")
KICKSDB_BASE_URL = os.getenv("KICKSDB_BASE_URL", "https://api.kicks.dev/v3")

# In-process SKU cache — prevents duplicate API calls in the same pipeline run.
# Keyed by sku string; value is the enrichment dict (or {} on miss).
_SKU_CACHE: dict = {}


# ── Public entry point ────────────────────────────────────────────────────────

def enrich(sku: str) -> dict:
    """
    Look up a SKU in KicksDB and return an enrichment dict.

    Always returns a dict — empty on miss or error, populated on success.
    Result is cached for the lifetime of the process (one pipeline run).

    Returned keys when successful:
      kdb_colorway      — e.g. "Black/University Red/White"
      kdb_release_date  — e.g. "2015-09-05"
      kdb_msrp          — e.g. "$160"
      kdb_brand         — e.g. "Nike"
      kdb_model         — e.g. "Air Jordan 1 Retro High OG"
      kdb_title         — full product title string from KicksDB
      kdb_verified      — True  (present on successful lookup)
      kdb_sku_confirmed — True if KicksDB SKU matches input exactly
      kdb_source        — always "kicksdb"

    Note: StockX/GOAT lowest-ask fields are intentionally excluded from
    the schema per the SACC spec (2026-05-02).

    Returned keys on miss/error:
      kdb_verified      — False
      kdb_miss_reason   — short explanation string
      kdb_source        — always "kicksdb"
    """
    if not sku:
        return {}

    sku = sku.strip().upper()

    if sku in _SKU_CACHE:
        return _SKU_CACHE[sku]

    if not KICKSDB_API_KEY:
        result = {
            "kdb_verified":    False,
            "kdb_miss_reason": "KICKSDB_API_KEY not set in .env",
            "kdb_source":      "kicksdb",
        }
        _SKU_CACHE[sku] = result
        return result

    result = _fetch(sku)
    _SKU_CACHE[sku] = result
    return result


def enrich_result(gemini_result: dict) -> dict:
    """
    Convenience wrapper: takes a Gemini result dict, enriches it with
    KicksDB data, and returns the merged dict.

    KicksDB is the authoritative source for all product-spec fields.
    Gemini is authoritative only for in-context observations (prices,
    hash-wall flag, drop events).

    Promotion rules (KicksDB always wins for product specs):
      • Model        ← kdb_model         (canonical marketing name)
      • colorway     ← kdb_colorway      (standardised colorway string)
      • release_date ← kdb_release_date  (official launch date)
      • Price_Retail ← kdb_msrp          (MSRP — KicksDB wins; Gemini's
                                           observed tag value kept in
                                           Price_Observed / Price_Audio)

    Hash-wall discount (computed here when possible):
      hash_wall_discount_pct  — % saved vs MSRP (int, e.g. 65)
      hash_wall_msrp          — MSRP used in calculation
      hash_wall_outlet_price  — outlet price observed in video

    All kdb_* keys are always written for auditability.
    """
    sku = (gemini_result.get("SKU") or gemini_result.get("sku") or "").strip()
    if not sku:
        return gemini_result

    enrichment = enrich(sku)
    if not enrichment:
        return gemini_result

    merged = {**gemini_result, **enrichment}

    # ── Product spec promotion — KicksDB is 100% authoritative ───────────────
    if enrichment.get("kdb_model"):
        merged["Model"] = enrichment["kdb_model"]

    if enrichment.get("kdb_colorway"):
        merged["colorway"] = enrichment["kdb_colorway"]

    if enrichment.get("kdb_release_date"):
        merged["release_date"] = enrichment["kdb_release_date"]

    if enrichment.get("kdb_msrp"):
        merged["Price_Retail"] = enrichment["kdb_msrp"]

    # ── Hash-wall discount computation ────────────────────────────────────────
    if merged.get("Is_Hash_Wall"):
        msrp_raw    = merged.get("Price_Retail") or ""
        outlet_raw  = merged.get("Price_Observed") or merged.get("Price_Audio") or ""
        msrp_val    = _price_to_float(msrp_raw)
        outlet_val  = _price_to_float(outlet_raw)

        if msrp_val and outlet_val and outlet_val < msrp_val:
            discount_pct = round((msrp_val - outlet_val) / msrp_val * 100)
            merged["hash_wall_discount_pct"]  = discount_pct
            merged["hash_wall_msrp"]          = msrp_raw
            merged["hash_wall_outlet_price"]  = outlet_raw

    return merged


# ── API client ────────────────────────────────────────────────────────────────

def _fetch(sku: str, attempts: int = 3, delay: float = 2.0) -> dict:
    """
    Call StockX for base product info, then GOAT to supplement colorway/date/price.

    StockX: title, brand, model, slug, image, rank
    GOAT:   colorway, release_date, retail_prices, nickname
    Both results are merged before building the enrichment dict.
    """
    try:
        import requests
    except ImportError:
        return {
            "kdb_verified":    False,
            "kdb_miss_reason": "requests library not installed — pip install requests",
            "kdb_source":      "kicksdb",
        }

    headers = {
        "Authorization": f"Bearer {KICKSDB_API_KEY}",
        "Accept":        "application/json",
        "User-Agent":    "SACC-Pipeline/2.0",
    }

    last_err = None
    for attempt in range(attempts):
        try:
            resp = requests.get(
                f"{KICKSDB_BASE_URL}/stockx/products",
                params={"query": sku},
                headers=headers,
                timeout=8,
            )

            if resp.status_code == 401:
                return {"kdb_verified": False, "kdb_miss_reason": "KicksDB 401 — check KICKSDB_API_KEY", "kdb_source": "kicksdb"}

            if resp.status_code == 403:
                return {"kdb_verified": False, "kdb_miss_reason": "KicksDB 403 — plan may not include this endpoint", "kdb_source": "kicksdb"}

            if resp.status_code == 429:
                wait = delay * (2 ** attempt)
                print(f"  [kicksdb] 429 rate limit — retrying in {wait}s")
                time.sleep(wait)
                continue

            if resp.status_code == 200:
                stockx = _extract_product(resp.json(), sku)
                if stockx:
                    goat = _fetch_goat_raw(sku, headers)
                    return _build_enrichment(stockx, sku, goat_product=goat)
                return _fetch_goat_only(sku, headers)

            if resp.status_code == 404:
                return _fetch_goat_only(sku, headers)

            last_err = f"HTTP {resp.status_code}"
            time.sleep(delay * (2 ** attempt))

        except requests.exceptions.Timeout:
            last_err = "request timed out"
            time.sleep(delay * (2 ** attempt))
        except Exception as e:
            last_err = str(e)
            time.sleep(delay * (2 ** attempt))

    return {
        "kdb_verified":    False,
        "kdb_miss_reason": f"KicksDB fetch failed after {attempts} attempts: {last_err}",
        "kdb_source":      "kicksdb",
    }


def _fetch_goat_raw(sku: str, headers: dict):
    """Call GOAT search and return the raw product dict (or None on miss)."""
    try:
        import requests
        resp = requests.get(
            f"{KICKSDB_BASE_URL}/goat/products",
            params={"query": sku},
            headers=headers,
            timeout=8,
        )
        if resp.status_code == 200:
            return _extract_product(resp.json(), sku)
    except Exception:
        pass
    return None


def _fetch_goat_only(sku: str, headers: dict) -> dict:
    """Use GOAT as sole source when StockX returns nothing."""
    goat = _fetch_goat_raw(sku, headers)
    if goat:
        return _build_enrichment(goat, sku)
    return {
        "kdb_verified":    False,
        "kdb_miss_reason": f"SKU {sku} not found on StockX or GOAT",
        "kdb_source":      "kicksdb",
    }


# ── Response parsing ──────────────────────────────────────────────────────────

def _extract_product(data: dict, sku: str):
    """
    Extract a single product dict from a KicksDB response.
    KicksDB v3 wraps results in {"data": [...]} or {"data": {...}}.
    """
    if not isinstance(data, dict):
        return None
    inner = data.get("data") or data.get("results") or data.get("products")
    if isinstance(inner, list):
        return inner[0] if inner else None
    if isinstance(inner, dict):
        return inner
    # Some endpoints return the product at the top level
    if data.get("sku") or data.get("style_id") or data.get("id"):
        return data
    return None


def _build_enrichment(product: dict, input_sku: str, goat_product: dict = None) -> dict:
    """
    Map StockX + GOAT product dicts to the SACC kdb_* enrichment schema.

    StockX is primary for: brand, model, title, sku, image.
    GOAT is primary for:   colorway, release_date, retail_prices, nickname.
    """
    g = goat_product or {}

    def _s(v):
        return str(v).strip() if v not in (None, "", "null") else ""

    # StockX fields
    brand        = _s(product.get("brand"))
    model        = _s(product.get("model"))
    title        = _s(product.get("title"))
    sku_returned = _s(product.get("sku") or product.get("style_id"))

    # GOAT supplements — colorway, release_date, retail_prices not in StockX
    colorway     = _s(g.get("colorway") or g.get("colorway_name")
                      or product.get("colorway") or product.get("secondary_title"))
    nickname     = _s(g.get("nickname"))
    goat_brand   = _s(g.get("brand"))
    goat_model   = _s(g.get("name") or g.get("model"))

    # Release date: GOAT returns ISO timestamp — strip to YYYY-MM-DD
    raw_date = _s(g.get("release_date") or g.get("releaseDate")
                  or product.get("release_date"))
    release_date = raw_date[:10] if raw_date else ""

    # MSRP: GOAT retail_prices (int/float when available)
    msrp = _parse_price(g.get("retail_prices") or g.get("retail_price")
                        or product.get("retail_price") or product.get("retailPrice"))

    # Prefer GOAT brand/model when more specific (GOAT uses "Air Jordan 1" vs StockX "Jordan 1 Retro")
    final_brand = goat_brand or brand
    final_model = goat_model or model

    enrichment = {
        "kdb_source":        "kicksdb",
        "kdb_verified":      True,
        "kdb_sku_confirmed": sku_returned.upper() == input_sku.upper() if sku_returned else False,
    }
    if final_brand:   enrichment["kdb_brand"]        = final_brand
    if final_model:   enrichment["kdb_model"]        = final_model
    if title:         enrichment["kdb_title"]        = title
    if colorway:      enrichment["kdb_colorway"]     = colorway
    if nickname:      enrichment["kdb_nickname"]     = nickname
    if release_date:  enrichment["kdb_release_date"] = release_date
    if msrp:          enrichment["kdb_msrp"]         = msrp

    return enrichment


def _price_to_float(raw) -> float:
    """Parse a price string like '$190' or '190.00' to a float. Returns 0.0 on failure."""
    if raw is None:
        return 0.0
    s = str(raw).strip().replace("$", "").replace(",", "").strip()
    try:
        return float(s)
    except (ValueError, TypeError):
        return 0.0


def _parse_price(raw) -> str:
    """Normalise a price value to a '$NNN' string."""
    if raw is None:
        return ""
    if isinstance(raw, (int, float)):
        return f"${raw:,.0f}"
    s = str(raw).strip()
    if not s or s in ("null", "None", "0", "0.0"):
        return ""
    if not s.startswith("$"):
        s = f"${s}"
    return s


# ── Cache management ──────────────────────────────────────────────────────────

def clear_cache():
    """Reset the in-process SKU cache. Call between pipeline runs if needed."""
    global _SKU_CACHE
    _SKU_CACHE = {}


def cache_stats() -> dict:
    hits = sum(1 for v in _SKU_CACHE.values() if v.get("kdb_verified"))
    return {"cached": len(_SKU_CACHE), "hits": hits, "misses": len(_SKU_CACHE) - hits}


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    sku = sys.argv[1] if len(sys.argv) > 1 else "555088-101"

    print(f"\n[kicksdb] API key : {'set' if KICKSDB_API_KEY else 'NOT SET — add KICKSDB_API_KEY to .env'}")
    print(f"[kicksdb] Base URL: {KICKSDB_BASE_URL}")
    print(f"[kicksdb] Looking up SKU: {sku}\n")

    result = enrich(sku)
    print(json.dumps(result, indent=2))
    print(f"\n[kicksdb] Cache: {cache_stats()}")
