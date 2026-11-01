"""
release_matcher.py — SACC Release Disambiguation
=================================================
Cross-references shoe identifications from Gemini against the Master_Whitelist_v1
release database to resolve which version of a multi-retro shoe is shown in a clip.

Decision priority
-----------------
1. SKU confirmed (Gemini read it directly) → whitelist lookup, done.
2. SKU not visible, model name identified  → find all whitelist entries for that name.
3. Single match                            → done, confidence 0.85.
4. Multiple releases (retros)              → date proximity filter.
5. Date falls in multiple release windows  → flag as "ambiguous".

Match types
-----------
  sku_confirmed       — Gemini read the SKU from the video (confidence 1.0)
  name_unique         — only one release of this name in whitelist (confidence 0.85)
  date_proximal       — nearest release to shoot date within sell-through window
  carryover_suspected — video date > CARRYOVER_YEARS after all known releases;
                        no newer retro exists in the window — manual review needed
  ambiguous           — multiple releases tie on date proximity; surface for review
  no_match            — name not found in whitelist at all

Carry-over vs retro
-------------------
A video shot in 2022 showing "Jordan 1 Chicago" could be:
  A. 2015 retro carry-over stock still in store
  B. 2022 retro release with a different SKU

If Gemini reads the SKU, this is resolved definitively.
If not, the system emits `carryover_suspected` when shoot_year is beyond
CARRYOVER_YEARS of the nearest release, so the clip is queued for manual
review instead of being silently mislabelled.

Usage
-----
  from release_matcher import match_release, load_whitelist

  wl = load_whitelist("/Users/daplug/Documents/SACC/Master_Whitelist_v1")
  result = match_release(
      model_name="Air Jordan 1 Retro High OG Chicago",
      shoot_date="20220415",
      sku_hint="",           # empty = Gemini couldn't read it
      whitelist=wl,
  )
  print(result["match_type"], result["sku"], result["confidence"], result["notes"])
"""

import json
import re
from pathlib import Path
from difflib import SequenceMatcher

# ── Tuneable constants ────────────────────────────────────────────────────────

CARRYOVER_YEARS = 2     # ≥ this many years post-release → flag carry-over
PROXIMAL_YEARS  = 1     # ≤ this many years post-release → high-confidence window
MIN_NAME_SCORE  = 0.55  # minimum fuzzy match score to consider a whitelist hit


# ── Whitelist loader ──────────────────────────────────────────────────────────

def load_whitelist(path: str) -> dict:
    """
    Load Master_Whitelist_v1 (multi-document JSON) into a single flat dict.
    Handles files containing multiple concatenated JSON objects.

    Returns: { sku_string: { brand, silhouette, colorway_name, release_date, ... } }
    """
    text = Path(path).read_text(encoding="utf-8")
    decoder = json.JSONDecoder()
    result: dict = {}
    idx = 0
    while idx < len(text):
        remaining = text[idx:].lstrip()
        if not remaining:
            break
        whitespace_consumed = len(text[idx:]) - len(remaining)
        try:
            obj, advance = decoder.raw_decode(remaining)
            idx += whitespace_consumed + advance
            if not isinstance(obj, dict):
                continue
            sample_key = next(iter(obj), "")
            if re.match(r"^[A-Z0-9]{2,}-\d{3}$", sample_key):
                # Top-level keys are SKUs — flat dict
                result.update(obj)
            else:
                # Nested structure
                for sku, entry in obj.items():
                    if isinstance(entry, dict):
                        result[sku] = entry
        except json.JSONDecodeError:
            break
    return result


# ── Name normaliser ───────────────────────────────────────────────────────────

_NOISE = frozenset({"retro", "high", "low", "mid", "og", "sp", "x", "the",
                    "air", "nike", "adidas", "jordan", "brand"})


def _normalise(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[''\"()\[\]]", "", s)
    s = re.sub(r"[\s\-/]+", " ", s)
    return " ".join(w for w in s.split() if w not in _NOISE).strip()


def _name_score(gemini_name: str, silhouette: str, colorway: str) -> float:
    """
    Fuzzy similarity between a Gemini model name and a whitelist entry.
    Weighted: 60% sequence ratio + 40% colorway word overlap.
    """
    a = _normalise(gemini_name)
    b = _normalise(f"{silhouette} {colorway}")
    ratio = SequenceMatcher(None, a, b).ratio()
    colorway_words = set(_normalise(colorway).split())
    name_words     = set(a.split())
    overlap = len(colorway_words & name_words) / max(len(colorway_words), 1)
    return round(ratio * 0.6 + overlap * 0.4, 3)


# ── Date helpers ──────────────────────────────────────────────────────────────

def _shoot_year(shoot_date: str):
    """Extract year int from YYYYMMDD, YYYY-MM-DD, or YYYY. Returns None if unparseable."""
    if not shoot_date:
        return None
    digits = re.sub(r"\D", "", shoot_date)
    return int(digits[:4]) if len(digits) >= 4 else None


def _release_year(release_date: str):
    """Extract year int from whitelist release_date (e.g. '2015', '2015-02-14')."""
    if not release_date:
        return None
    m = re.search(r"\b(19|20)\d{2}\b", str(release_date))
    return int(m.group()) if m else None


# ── Core match function ───────────────────────────────────────────────────────

def match_release(
    model_name: str,
    shoot_date: str,
    sku_hint: str = "",
    whitelist: dict = None,
) -> dict:
    """
    Resolve which release of a shoe is shown in a clip.

    Args:
        model_name  : Gemini-identified shoe name
        shoot_date  : ffprobe creation_time (YYYYMMDD or YYYY-MM-DD)
        sku_hint    : SKU from Gemini if visible on box/tag, else ""
        whitelist   : loaded whitelist dict from load_whitelist()

    Returns dict:
        match_type   — one of the types listed in module docstring
        sku          — best matching SKU (None for no_match)
        release_year — int or None
        confidence   — 0.0–1.0
        candidates   — list of all matching SKUs considered
        notes        — human-readable explanation for review queues / audit log
    """
    if whitelist is None:
        whitelist = {}

    _null = {
        "match_type": "no_match", "sku": None, "release_year": None,
        "confidence": 0.0, "candidates": [], "notes": "",
    }

    # ── Layer 1: SKU confirmed by Gemini ─────────────────────────────────────
    if sku_hint:
        sku_clean = sku_hint.strip().upper()
        entry = whitelist.get(sku_clean)
        if entry:
            return {
                "match_type":   "sku_confirmed",
                "sku":          sku_clean,
                "release_year": _release_year(entry.get("release_date", "")),
                "confidence":   1.0,
                "candidates":   [sku_clean],
                "notes":        f"SKU {sku_clean} read directly from video",
            }
        # SKU visible but not in local whitelist — still trust it
        return {
            "match_type":   "sku_confirmed",
            "sku":          sku_clean,
            "release_year": None,
            "confidence":   0.9,
            "candidates":   [sku_clean],
            "notes":        f"SKU {sku_clean} visible in video; not in local whitelist",
        }

    if not model_name:
        return {**_null, "notes": "no model name or SKU available"}

    # ── Layer 2: Name-based candidate search ─────────────────────────────────
    candidates = []
    for sku, entry in whitelist.items():
        score = _name_score(
            model_name,
            entry.get("silhouette", ""),
            entry.get("colorway_name", ""),
        )
        if score >= MIN_NAME_SCORE:
            candidates.append({
                "sku":          sku,
                "score":        score,
                "release_year": _release_year(entry.get("release_date", "")),
                "entry":        entry,
            })

    if not candidates:
        return {
            **_null,
            "notes": f"'{model_name}' matched nothing in whitelist "
                     f"(min_score={MIN_NAME_SCORE})",
        }

    candidates.sort(key=lambda c: (-c["score"], -(c["release_year"] or 0)))

    if len(candidates) == 1:
        c = candidates[0]
        return {
            "match_type":   "name_unique",
            "sku":          c["sku"],
            "release_year": c["release_year"],
            "confidence":   round(c["score"] * 0.85, 3),
            "candidates":   [c["sku"]],
            "notes":        f"single whitelist match (name score {c['score']})",
        }

    # ── Layer 3: Date proximity (multi-release disambiguation) ───────────────
    video_year = _shoot_year(shoot_date)

    if video_year is None:
        best = candidates[0]
        return {
            "match_type":   "ambiguous",
            "sku":          best["sku"],
            "release_year": best["release_year"],
            "confidence":   round(best["score"] * 0.5, 3),
            "candidates":   [c["sku"] for c in candidates],
            "notes":        f"{len(candidates)} releases found; no shoot date to disambiguate",
        }

    def _proximity_score(c) -> float:
        ry = c["release_year"]
        if ry is None:
            return -999.0
        delta = video_year - ry
        if delta < 0:
            # Filmed before official release — press/preview event
            return 10.0 - abs(delta) * 0.5
        if delta <= PROXIMAL_YEARS:
            return 10.0          # primary sell-through window
        if delta <= CARRYOVER_YEARS:
            return 10.0 - delta  # carry-over window, still plausible
        return float(-delta)     # beyond carry-over — penalise proportionally

    for c in candidates:
        c["proximity"] = _proximity_score(c)

    candidates.sort(key=lambda c: (-c["proximity"], -c["score"]))
    best   = candidates[0]
    ry     = best["release_year"]
    delta  = (video_year - ry) if ry is not None else None

    # Ambiguity: multiple candidates share the top proximity score
    top_prox = best["proximity"]
    tied = [c for c in candidates if c["proximity"] == top_prox]
    if len(tied) > 1:
        return {
            "match_type":   "ambiguous",
            "sku":          best["sku"],
            "release_year": ry,
            "confidence":   round(best["score"] * 0.5, 3),
            "candidates":   [c["sku"] for c in tied],
            "notes":        (f"{len(tied)} releases tie at proximity={top_prox} "
                             f"for video year {video_year}; verify SKU"),
        }

    # Carry-over detection: video is beyond carry-over window for best match
    if delta is not None and delta > CARRYOVER_YEARS:
        newer_in_window = [
            c for c in candidates
            if c["release_year"]
            and c["release_year"] > ry
            and (video_year - c["release_year"]) <= CARRYOVER_YEARS
        ]
        if not newer_in_window:
            return {
                "match_type":   "carryover_suspected",
                "sku":          best["sku"],
                "release_year": ry,
                "confidence":   round(best["score"] * 0.55, 3),
                "candidates":   [c["sku"] for c in candidates],
                "notes":        (f"video {video_year} is {delta}y after {ry} release; "
                                 f"no newer retro in window — carry-over stock suspected; "
                                 f"verify SKU to confirm"),
            }

    conf_multiplier = 0.9 if (delta is not None and delta <= PROXIMAL_YEARS) else 0.72
    return {
        "match_type":   "date_proximal",
        "sku":          best["sku"],
        "release_year": ry,
        "confidence":   round(best["score"] * conf_multiplier, 3),
        "candidates":   [c["sku"] for c in candidates],
        "notes":        (f"video {video_year}, nearest release {ry} "
                         f"(Δ{delta}y) — "
                         f"{'within primary window' if delta is not None and delta <= PROXIMAL_YEARS else 'carry-over window'}"),
    }


# ── Batch enrichment helper ───────────────────────────────────────────────────

def enrich_clip(clip: dict, whitelist: dict) -> dict:
    """
    Take a clip record (from db.py clips table or a Gemini result dict) and
    attach release_match fields. Non-destructive — original fields preserved.

    Input clip fields used: model, sku (or SKU), shoot_date, analysed_at
    Added fields: release_match (nested dict with all match_release output)
    """
    model      = clip.get("model") or clip.get("Model") or ""
    sku_hint   = clip.get("sku")   or clip.get("SKU")   or ""
    shoot_date = clip.get("shoot_date") or clip.get("analysed_at") or ""

    result = match_release(model, shoot_date, sku_hint, whitelist)
    return {**clip, "release_match": result}


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys, os

    wl_path = os.path.join(os.path.dirname(__file__), "Master_Whitelist_v1")
    print(f"Loading whitelist: {wl_path}")
    wl = load_whitelist(wl_path)
    print(f"Loaded {len(wl)} entries\n")

    test_cases = [
        # (model_name, shoot_date, sku_hint, description)
        ("Air Jordan 1 Retro High OG Chicago", "20220415", "",           "2022 shoot, no SKU — should check proximity"),
        ("Air Jordan 1 Retro High OG Chicago", "20150301", "555088-101", "2015 shoot, SKU confirmed — definitive"),
        ("Air Jordan 1 Retro High OG Chicago", "20180601", "",           "2018 shoot, no SKU — carry-over suspected"),
        ("Nike Dunk Low Pro B",                "20231001", "",           "single release — name_unique expected"),
        ("",                                   "20220101", "",           "no data — no_match expected"),
    ]

    for model, date, sku, desc in test_cases:
        r = match_release(model, date, sku, wl)
        print(f"  [{desc}]")
        print(f"    model       : {model or '(empty)'}")
        print(f"    shoot_date  : {date}   sku_hint: '{sku}'")
        print(f"    → match_type: {r['match_type']}")
        print(f"    → sku       : {r['sku']}")
        print(f"    → confidence: {r['confidence']}")
        print(f"    → notes     : {r['notes']}")
        print()
