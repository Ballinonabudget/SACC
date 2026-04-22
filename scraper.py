from __future__ import annotations
"""
StockX Jordan 1 High OG Scraper — scraper.py
─────────────────────────────────────────────
Run:  python3 scraper.py

Outputs:
  - jordan1_og_stockx.json   → raw enriched entries
  - whitelist.json           → overwrites / merges with your SACC whitelist

Requires:  pip install curl_cffi requests
"""

import json
import re
import time
import random
from curl_cffi import requests

# ─────────────────────────────────
# CONFIG
# ─────────────────────────────────
OUTPUT_RAW       = "jordan1_og_stockx.json"
WHITELIST_OUTPUT = "whitelist.json"
PAGE_LIMIT       = 40          # StockX max per page
MAX_PAGES        = 25          # 25 × 40 = up to 1000 results
DELAY_RANGE      = (1.5, 3.0)  # polite delay between requests (seconds)

QUERIES = [
    "Air Jordan 1 High OG",
    "Air Jordan 1 Retro High OG",
    "Air Jordan 1 High 85",
    "Air Jordan 1 Low OG",
]

HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "accept-language": "en-US,en;q=0.9",
    "accept-encoding": "gzip, deflate, br",
    "sec-ch-ua": '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "none",
    "upgrade-insecure-requests": "1",
    "user-agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
}

# ─────────────────────────────────
# HELPERS
# ─────────────────────────────────
EXCLUSION_KEYWORDS = [
    "mid", "cmft", "comfort", "ajko", "ko",
    "low" ,   # Low OG is handled by dedicated query; exclude from High queries
    "women",  # optional — remove if you want women's
]

HIGH_QUERY_EXCLUSIONS = ["low"]   # only exclude "low" when scraping High OG queries
LOW_QUERY_INCLUSIONS  = ["low"]


def build_url(query: str, page: int) -> str:
    q = query.replace(" ", "%20")
    return (
        f"https://stockx.com/search/sneakers"
        f"?s={q}&page={page}"
    )


def fetch_page(session, url: str) -> dict | None:
    try:
        resp = session.get(
            url,
            headers=HEADERS,
            impersonate="chrome120",
            timeout=20,
        )
        if resp.status_code != 200:
            print(f"  ⚠ HTTP {resp.status_code} for {url}")
            return None

        match = re.search(
            r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
            resp.text, re.DOTALL
        )
        if not match:
            print("  ⚠ __NEXT_DATA__ not found in page")
            return None

        return json.loads(match.group(1))

    except Exception as e:
        print(f"  ✗ Fetch error: {e}")
        return None


def extract_edges(data: dict) -> list:
    """Navigate the StockX NextJS payload to the product edges list."""
    try:
        queries = (
            data["props"]["pageProps"]["req"]
            ["appContext"]["states"]["query"]["value"]["queries"]
        )
        # query index 1 is the discovery/search query
        browse = queries[1]["state"]["data"]["browse"]
        return browse["results"]["edges"]
    except (KeyError, IndexError, TypeError):
        return []


def parse_node(node: dict) -> dict | None:
    """Extract our target schema fields from a StockX product node."""
    try:
        name     = node.get("name", "").strip()
        url_key  = node.get("urlKey", "")
        traits   = node.get("traits", [])

        style_code   = ""
        release_date = ""
        colorway     = ""
        retail_price = 0.0

        for trait in traits:
            t_name  = trait.get("name", "")
            t_value = trait.get("value", "")
            if t_name == "Style":         style_code   = t_value
            elif t_name == "Release Date": release_date = t_value
            elif t_name == "Colorway":    colorway     = t_value
            elif t_name == "Retail Price":
                try: retail_price = float(str(t_value).replace("$","").replace(",",""))
                except: retail_price = 0.0

        # Attempt style code from URL key as fallback (e.g. air-jordan-1-retro-high-og-555088-101)
        if not style_code:
            sc = re.search(r'([A-Z0-9]{6}-[0-9]{3})', url_key.upper())
            if sc:
                style_code = sc.group(1)

        # Market data for retail price fallback
        if not retail_price:
            try:
                market = node.get("market", {})
                retail_price = market.get("lowestAsk", {}).get("amount", 0) or 0
            except Exception:
                pass

        year = str(release_date)[:4] if release_date else "Unknown"

        return {
            "model_name":    name,
            "style_code":    style_code,
            "colorway_name": colorway,
            "release_date":  year,
            "retail_price":  retail_price,
            "_stockx_url":   f"https://stockx.com/{url_key}",
            "_raw_release":  release_date,
        }

    except Exception as e:
        return None


def is_relevant(entry: dict, query: str) -> bool:
    """Filter out Mid, CMFT, AJKO and other excluded silhouettes."""
    name_lower = entry.get("model_name","").lower()

    exclusions = EXCLUSION_KEYWORDS.copy()
    # Re-allow 'low' when we're explicitly scraping Low OG
    if "low" in query.lower():
        exclusions = [k for k in exclusions if k != "low"]
    else:
        # For High queries, filter out lows
        if "low" in name_lower:
            return False

    for kw in exclusions:
        if kw in name_lower:
            return False

    # Must contain "jordan 1" or "air jordan 1"
    if "jordan 1" not in name_lower:
        return False

    return True


# ─────────────────────────────────
# MAIN SCRAPER
# ─────────────────────────────────
def main():
    session   = requests.Session()
    all_entries: list[dict] = []
    seen_codes: set = set()

    print("=" * 60)
    print("  SACC — StockX Jordan 1 Scraper")
    print("=" * 60)

    for query in QUERIES:
        print(f"\n🔍 Querying: '{query}'")

        for page in range(1, MAX_PAGES + 1):
            url = build_url(query, page)
            print(f"   Page {page:>2}  {url}")

            data = fetch_page(session, url)
            if data is None:
                print("   Stopping this query — fetch failed.")
                break

            edges = extract_edges(data)
            if not edges:
                print(f"   No more results at page {page}. Moving on.")
                break

            page_new = 0
            for edge in edges:
                node  = edge.get("node", {})
                entry = parse_node(node)
                if not entry:
                    continue
                if not is_relevant(entry, query):
                    continue

                sc = entry["style_code"]
                if sc and sc in seen_codes:
                    continue  # deduplicate
                if sc:
                    seen_codes.add(sc)

                all_entries.append(entry)
                page_new += 1

            print(f"   ✓ {page_new} new entries added (total: {len(all_entries)})")

            # Polite delay
            delay = random.uniform(*DELAY_RANGE)
            time.sleep(delay)

            if len(edges) < PAGE_LIMIT:
                print("   Last page reached (fewer results than page limit).")
                break

    # ── Sort by release year
    all_entries.sort(key=lambda x: x.get("release_date", "0000"))

    # ── Save raw full output
    with open(OUTPUT_RAW, "w", encoding="utf-8") as f:
        json.dump(all_entries, f, indent=2, ensure_ascii=False)
    print(f"\n✅  Raw results saved → {OUTPUT_RAW}  ({len(all_entries)} entries)")

    # ── Build whitelist.json (clean schema, no internal fields)
    whitelist = []
    for e in all_entries:
        whitelist.append({
            "model_name":    e["model_name"],
            "style_code":    e["style_code"],
            "colorway_name": e["colorway_name"],
            "release_date":  e["release_date"],
            "retail_price":  e["retail_price"],
        })

    with open(WHITELIST_OUTPUT, "w", encoding="utf-8") as f:
        json.dump(whitelist, f, indent=2, ensure_ascii=False)
    print(f"✅  Whitelist saved    → {WHITELIST_OUTPUT}  ({len(whitelist)} entries)")

    # ── Summary table
    print("\n" + "─" * 50)
    print(f"{'Year':<8} {'High OG':>10} {'85 Cut':>10} {'Low OG':>10} {'Total':>8}")
    print("─" * 50)
    from collections import defaultdict
    year_counts = defaultdict(lambda: {"High OG": 0, "85": 0, "Low OG": 0})
    for e in all_entries:
        n = e["model_name"].lower()
        yr = e["release_date"]
        if "85" in n or "'85" in n:
            year_counts[yr]["85"] += 1
        elif "low" in n:
            year_counts[yr]["Low OG"] += 1
        else:
            year_counts[yr]["High OG"] += 1

    grand = {"High OG": 0, "85": 0, "Low OG": 0}
    for yr in sorted(year_counts.keys()):
        c = year_counts[yr]
        t = c["High OG"] + c["85"] + c["Low OG"]
        print(f"{yr:<8} {c['High OG']:>10} {c['85']:>10} {c['Low OG']:>10} {t:>8}")
        for k in grand: grand[k] += c[k]

    print("─" * 50)
    total = sum(grand.values())
    print(f"{'TOTAL':<8} {grand['High OG']:>10} {grand['85']:>10} {grand['Low OG']:>10} {total:>8}")
    print("─" * 50)
    print("\nDone! Run the SACC dashboard to see updated results.")


if __name__ == "__main__":
    main()
