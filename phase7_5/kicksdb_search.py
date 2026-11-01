"""KicksDB description search + gallery URL extraction.

Extends the existing kicksdb_enricher with free-text search to support
Path B's description-to-SKU resolution.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import requests

# Reuse env + config from the existing enricher
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from kicksdb_enricher import (  # noqa: E402
    KICKSDB_API_KEY,
    KICKSDB_BASE_URL,
    REMOTE_API_ENABLED,
)

_DESC_CACHE: dict[str, list[dict]] = {}
_GALLERY_CACHE: dict[str, list[str]] = {}

_HEADERS = {
    "Authorization": f"Bearer {KICKSDB_API_KEY}",
    "Accept": "application/json",
    "User-Agent": "SACC-Pipeline/2.0",
}


def search_by_description(query: str, max_results: int = 5,
                          source: str = "stockx") -> list[dict]:
    """
    Free-text product search. Returns up to max_results raw product dicts.
    Cached by (source, query) for the lifetime of the process.

    source: "stockx" or "goat" (KicksDB v3 supports both)
    """
    if not query or not KICKSDB_API_KEY or not REMOTE_API_ENABLED:
        return []
    key = f"{source}::{query.strip().lower()}"
    if key in _DESC_CACHE:
        return _DESC_CACHE[key][:max_results]

    try:
        resp = requests.get(
            f"{KICKSDB_BASE_URL}/{source}/products",
            params={"query": query, "limit": max_results},
            headers=_HEADERS,
            timeout=10,
        )
        if resp.status_code != 200:
            _DESC_CACHE[key] = []
            return []
        data = resp.json()
        inner = data.get("data") or data.get("results") or data.get("products") or []
        products = inner if isinstance(inner, list) else [inner]
        _DESC_CACHE[key] = products
        return products[:max_results]
    except Exception:
        _DESC_CACHE[key] = []
        return []


def gallery_urls(product: dict, max_urls: int = 5) -> list[str]:
    """Extract image URLs from a product dict. Cached by SKU."""
    sku = (product.get("sku") or product.get("style_id") or "").upper()
    if sku and sku in _GALLERY_CACHE:
        return _GALLERY_CACHE[sku][:max_urls]

    urls: list[str] = []
    for k in ("image", "image_url", "thumbnail"):
        v = product.get(k)
        if isinstance(v, str) and v.startswith("http"):
            urls.append(v)
    gallery = product.get("gallery") or product.get("images") or []
    if isinstance(gallery, list):
        for item in gallery:
            if isinstance(item, str) and item.startswith("http"):
                urls.append(item)
            elif isinstance(item, dict):
                u = item.get("url") or item.get("image") or item.get("src")
                if isinstance(u, str) and u.startswith("http"):
                    urls.append(u)

    seen = set()
    out: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)

    if sku:
        _GALLERY_CACHE[sku] = out
    return out[:max_urls]


def fetch_image(url: str, timeout: int = 10) -> bytes | None:
    """Download an image. Returns bytes or None on failure."""
    try:
        r = requests.get(url, timeout=timeout)
        if r.status_code == 200:
            return r.content
    except Exception:
        pass
    return None


def cache_stats() -> dict:
    return {
        "description_queries": len(_DESC_CACHE),
        "gallery_skus": len(_GALLERY_CACHE),
    }
