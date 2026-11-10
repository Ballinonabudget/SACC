#!/usr/bin/env python3
"""
SACC Store Directory & Location Resolver
========================================
Integrates the canonical Outlet Plug retail store directory with historical/defunct
retail branches (such as Nike Clearance Store 192 on US-192, pre-Loop).

Features:
1. Canonical Florida retail network (active stores + historical defunct stores).
2. Spatial-temporal geofence resolution (Haversine formula with date windowing).
3. Seeding into SACC library catalogs (staging pilot & live schema compliant).
4. Zero cloud API calls, running locally on Apple Silicon.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import sqlite3
from typing import Dict, Any, List, Optional, Tuple


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two GPS coordinates in meters."""
    r = 6371000.0  # Earth mean radius in meters
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    return 2.0 * r * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


# Master Florida Store Directory
# Combines Outlet Plug live retail registry with SACC historical retail archive
STORE_REGISTRY: List[Dict[str, Any]] = [
    # --- ACTIVE CLEARANCE STORES ---
    {
        "id": "store-mkt",
        "store_id": "STORE-MKT",
        "code": "ORL-MKT-CLR",
        "label": "Nike Clearance Store - Orlando Marketplace",
        "chain": "Nike Clearance Store",
        "type": "Clearance",
        "status": "active",
        "valid_from": "2014-01-01",
        "valid_to": "2099-12-31",
        "lat": 28.468446,
        "lon": -81.451038,
        "radius_m": 450,
        "address": "5209 International Dr, Orlando, FL 32819",
        "city": "Orlando",
        "state": "FL",
        "postal_code": "32819",
        "aliases": ["Orlando Marketplace", "Marketplace Clearance", "Nike Clearance", "OMP", "store-mkt"],
    },
    {
        "id": "store-nclp",
        "store_id": "STORE-NCLP",
        "code": "KSM-NCLP-CLR",
        "label": "Nike Clearance Store at the Loop",
        "chain": "Nike Clearance Store",
        "type": "Clearance",
        "status": "active",
        "valid_from": "2019-02-01",
        "valid_to": "2099-12-31",
        "lat": 28.343809,
        "lon": -81.429050,
        "radius_m": 500,
        "address": "2617 W Osceola Pkwy, Kissimmee, FL 34741",
        "city": "Kissimmee",
        "state": "FL",
        "postal_code": "34741",
        "successor_to": "KSM-NC192-CLR",
        "aliases": ["Nike Clearance Store at the Loop", "The Loop", "Osceola Parkway", "NCLP", "KSM"],
    },
    {
        "id": "store-dap",
        "store_id": "STORE-DAP",
        "code": "DAP-CLR",
        "label": "Nike Clearance Store - Dania Pointe",
        "chain": "Nike Clearance Store",
        "type": "Clearance",
        "status": "active",
        "valid_from": "2020-01-01",
        "valid_to": "2099-12-31",
        "lat": 26.053787,
        "lon": -80.161200,
        "radius_m": 450,
        "address": "166 Sunset Dr, Dania Beach, FL 33004",
        "city": "Dania Beach",
        "state": "FL",
        "postal_code": "33004",
        "aliases": ["Dania Pointe", "Dania Beach Nike", "DAP-CLR"],
    },
    {
        "id": "store-flc",
        "store_id": "STORE-FLC",
        "code": "FLC-CLR",
        "label": "Nike Clearance Store - Florida City",
        "chain": "Nike Clearance Store",
        "type": "Clearance",
        "status": "active",
        "valid_from": "2015-01-01",
        "valid_to": "2099-12-31",
        "lat": 25.452360,
        "lon": -80.473683,
        "radius_m": 450,
        "address": "1 Outlet Blvd, Florida City, FL 33034",
        "city": "Florida City",
        "state": "FL",
        "postal_code": "33034",
        "aliases": ["Florida City Clearance", "Florida City Outlets", "FLC-CLR"],
    },

    # --- HISTORICAL / DEFUNCT CLEARANCE STORES ---
    {
        "id": "store-nc192",
        "store_id": "STORE-NC192",
        "code": "KSM-NC192-CLR",
        "label": "Nike Clearance Store 192 (US-192, defunct)",
        "chain": "Nike Clearance Store",
        "type": "Clearance",
        "status": "defunct",
        "valid_from": "2010-01-01",
        "valid_to": "2019-01-31",
        "lat": 28.318078,
        "lon": -81.468856,
        "radius_m": 450,
        "address": "5125 W Irlo Bronson Memorial Hwy, Kissimmee, FL 34746",
        "city": "Kissimmee",
        "state": "FL",
        "postal_code": "34746",
        "predecessor_to": "KSM-NCLP-CLR",
        "historical_notes": "Defunct predecessor of NCLP on US-192 corridor. Closed when relocated to The Loop in early 2019.",
        "aliases": ["Nike Clearance Store 192", "Nike Clearance 192", "US-192", "NC192", "Store 192", "Kissimmee 192"],
    },

    # --- ACTIVE FACTORY STORES ---
    {
        "id": "store-idr",
        "store_id": "STORE-IDR",
        "code": "ORL-IDR-FAC",
        "label": "Nike Factory Store - International Drive",
        "chain": "Nike Factory Store",
        "type": "Factory",
        "status": "active",
        "valid_from": "2010-01-01",
        "valid_to": "2099-12-31",
        "lat": 28.476218,
        "lon": -81.449292,
        "radius_m": 450,
        "address": "4951 International Dr, Orlando, FL 32819",
        "city": "Orlando",
        "state": "FL",
        "postal_code": "32819",
        "aliases": ["International Drive", "I-Drive Factory", "Nike I-Drive", "IDR", "ORL-IDR-FAC"],
    },
    {
        "id": "store-vld",
        "store_id": "STORE-VLD",
        "code": "ORL-VLD-FAC",
        "label": "Nike Factory Store - Orlando Vineland",
        "chain": "Nike Factory Store",
        "type": "Factory",
        "status": "active",
        "valid_from": "2010-01-01",
        "valid_to": "2099-12-31",
        "lat": 28.386173,
        "lon": -81.493748,
        "radius_m": 500,
        "address": "8200 Vineland Ave, Orlando, FL 32821",
        "city": "Orlando",
        "state": "FL",
        "postal_code": "32821",
        "aliases": ["Vineland Premium Outlets", "Vineland", "Orlando Vineland", "VLD"],
    },
    {
        "id": "store-lbv",
        "store_id": "STORE-LBV",
        "code": "ORL-LBV-FAC",
        "label": "Nike Factory Store - Lake Buena Vista",
        "chain": "Nike Factory Store",
        "type": "Factory",
        "status": "active",
        "valid_from": "2012-01-01",
        "valid_to": "2099-12-31",
        "lat": 28.350281,
        "lon": -81.485672,
        "radius_m": 450,
        "address": "15647 State Road 535, Orlando, FL 32821",
        "city": "Orlando",
        "state": "FL",
        "postal_code": "32821",
        "aliases": ["Lake Buena Vista", "Buena Vista Factory", "LBV", "ORL-LBV-FAC"],
    },
    {
        "id": "store-cel",
        "store_id": "STORE-CEL",
        "code": "KSM-CEL-FAC",
        "label": "Nike Factory Store - Celebration",
        "chain": "Nike Factory Store",
        "type": "Factory",
        "status": "active",
        "valid_from": "2015-01-01",
        "valid_to": "2099-12-31",
        "lat": 28.333939,
        "lon": -81.530637,
        "radius_m": 450,
        "address": "400 Carillon Forest Dr, Kissimmee, FL 34747",
        "city": "Kissimmee",
        "state": "FL",
        "postal_code": "34747",
        "aliases": ["Celebration", "Celebration Kissimmee", "CEL-K"],
    },
    {
        "id": "store-wgn",
        "store_id": "STORE-WGN",
        "code": "ORL-WGN-FAC",
        "label": "Nike Factory Store - Winter Garden",
        "chain": "Nike Factory Store",
        "type": "Factory",
        "status": "active",
        "valid_from": "2012-01-01",
        "valid_to": "2099-12-31",
        "lat": 28.524416,
        "lon": -81.583771,
        "radius_m": 450,
        "address": "3251 Daniels Rd, Winter Garden, FL 34787",
        "city": "Winter Garden",
        "state": "FL",
        "postal_code": "34787",
        "aliases": ["Winter Garden Village", "Winter Garden", "WGN"],
    },
    {
        "id": "store-tpa",
        "store_id": "STORE-TPA",
        "code": "TPA-LUTZ-FAC",
        "label": "Nike Factory Store - Tampa / Lutz",
        "chain": "Nike Factory Store",
        "type": "Factory",
        "status": "active",
        "valid_from": "2015-01-01",
        "valid_to": "2099-12-31",
        "lat": 28.190071,
        "lon": -82.390006,
        "radius_m": 450,
        "address": "2398 Grand Cypress Dr, Lutz, FL 33559",
        "city": "Lutz",
        "state": "FL",
        "postal_code": "33559",
        "aliases": ["Tampa Premium Outlets", "Tampa Factory", "TPA", "Lutz"],
    },
    {
        "id": "store-ell",
        "store_id": "STORE-ELL",
        "code": "ELL-FAC",
        "label": "Nike Factory Store - Ellenton",
        "chain": "Nike Factory Store",
        "type": "Factory",
        "status": "active",
        "valid_from": "2014-01-01",
        "valid_to": "2099-12-31",
        "lat": 27.535599,
        "lon": -82.507728,
        "radius_m": 450,
        "address": "5195 Factory Shops Blvd, Ellenton, FL 34222",
        "city": "Ellenton",
        "state": "FL",
        "postal_code": "34222",
        "aliases": ["Ellenton Premium Outlets", "Ellenton Factory", "ELL"],
    },
    {
        "id": "store-day",
        "store_id": "STORE-DAY",
        "code": "DAY-FAC",
        "label": "Nike Factory Store - Daytona Beach",
        "chain": "Nike Factory Store",
        "type": "Factory",
        "status": "active",
        "valid_from": "2016-01-01",
        "valid_to": "2099-12-31",
        "lat": 29.212485,
        "lon": -81.098858,
        "radius_m": 450,
        "address": "1100 Cornerstone Blvd, Daytona Beach, FL 32117",
        "city": "Daytona Beach",
        "state": "FL",
        "postal_code": "32117",
        "aliases": ["Daytona Beach Outlets", "Daytona Factory", "DAY"],
    },
    {
        "id": "store-sta",
        "store_id": "STORE-STA",
        "code": "STA-FAC",
        "label": "Nike Factory Store - St Augustine",
        "chain": "Nike Factory Store",
        "type": "Factory",
        "status": "active",
        "valid_from": "2012-01-01",
        "valid_to": "2099-12-31",
        "lat": 29.926465,
        "lon": -81.418945,
        "radius_m": 450,
        "address": "500 Outlet Mall Blvd, St. Augustine, FL 32084",
        "city": "St. Augustine",
        "state": "FL",
        "postal_code": "32084",
        "aliases": ["St Augustine Outlets", "St Augustine Factory", "STA"],
    },
    {
        "id": "store-saw",
        "store_id": "STORE-SAW",
        "code": "SAW-FAC",
        "label": "Nike Factory Store - Sawgrass Mills",
        "chain": "Nike Factory Store",
        "type": "Factory",
        "status": "active",
        "valid_from": "2010-01-01",
        "valid_to": "2099-12-31",
        "lat": 26.151941,
        "lon": -80.321429,
        "radius_m": 550,
        "address": "12801 W Sunrise Blvd, Sunrise, FL 33323",
        "city": "Sunrise",
        "state": "FL",
        "postal_code": "33323",
        "aliases": ["Sawgrass Mills", "Sawgrass Factory", "SAW"],
    },
    {
        "id": "store-dol",
        "store_id": "STORE-DOL",
        "code": "MIA-DOL-FAC",
        "label": "Nike Factory Store - Dolphin Mall",
        "chain": "Nike Factory Store",
        "type": "Factory",
        "status": "active",
        "valid_from": "2010-01-01",
        "valid_to": "2099-12-31",
        "lat": 25.787419,
        "lon": -80.382766,
        "radius_m": 500,
        "address": "11401 NW 12th St, Miami, FL 33172",
        "city": "Miami",
        "state": "FL",
        "postal_code": "33172",
        "aliases": ["Dolphin Mall", "Miami Dolphin", "DOL"],
    },

    # --- MAJOR SNEAKER SHOPPING MALL COMPLEXES ---
    {
        "id": "store-flm",
        "store_id": "STORE-FLM",
        "code": "ORL-FLM-MALL",
        "label": "The Florida Mall (Nike / JD / Foot Locker)",
        "chain": "Retail Mall",
        "type": "Mall",
        "status": "active",
        "valid_from": "2010-01-01",
        "valid_to": "2099-12-31",
        "lat": 28.446800,
        "lon": -81.396600,
        "radius_m": 600,
        "address": "8001 S Orange Blossom Trl, Orlando, FL 32809",
        "city": "Orlando",
        "state": "FL",
        "postal_code": "32809",
        "aliases": ["The Florida Mall", "Florida Mall", "FLM"],
    },
    {
        "id": "store-mam",
        "store_id": "STORE-MAM",
        "code": "ORL-MAM-MALL",
        "label": "Mall at Millenia",
        "chain": "Retail Mall",
        "type": "Mall",
        "status": "active",
        "valid_from": "2010-01-01",
        "valid_to": "2099-12-31",
        "lat": 28.489700,
        "lon": -81.431200,
        "radius_m": 600,
        "address": "4200 Conroy Rd, Orlando, FL 32839",
        "city": "Orlando",
        "state": "FL",
        "postal_code": "32839",
        "aliases": ["Mall at Millenia", "Millenia", "MAM"],
    },
    {
        "id": "store-adi",
        "store_id": "STORE-ADI",
        "code": "ORL-ADI-OUT",
        "label": "Adidas Outlet - Orlando International",
        "chain": "Adidas Outlet",
        "type": "Outlet",
        "status": "active",
        "valid_from": "2015-01-01",
        "valid_to": "2099-12-31",
        "lat": 28.475000,
        "lon": -81.448500,
        "radius_m": 400,
        "address": "4967 International Dr, Orlando, FL 32819",
        "city": "Orlando",
        "state": "FL",
        "postal_code": "32819",
        "aliases": ["Adidas Outlet", "Adidas I-Drive", "Adidas International"],
    },
]


def seed_store_directory(con: sqlite3.Connection, directory_id: str = "dir-outletplug-fl") -> int:
    """
    Seed the canonical Florida store directory into library_stores.
    Idempotent: Uses INSERT OR REPLACE.
    """
    # 1. Ensure directory record
    con.execute(
        """
        INSERT OR REPLACE INTO library_directories (id, payload_json, reviewer, evidence)
        VALUES (?, ?, 'agent:antigravity', 'Outlet Plug Master Retail Directory + SACC Historical Archive')
        """,
        (
            directory_id,
            json.dumps({
                "source": "Outlet Plug Retail Directory + SACC Retail Archive",
                "total_stores": len(STORE_REGISTRY),
                "generated_at": "2026-11-09T20:28:00Z",
            }),
        ),
    )

    # 2. Insert stores
    rows = []
    for s in STORE_REGISTRY:
        payload = {
            "lat": s["lat"],
            "lon": s["lon"],
            "radius_m": s.get("radius_m", 450),
            "address": s.get("address", ""),
            "city": s.get("city", ""),
            "state": s.get("state", "FL"),
            "postal_code": s.get("postal_code", ""),
            "chain": s.get("chain", ""),
            "type": s.get("type", ""),
            "status": s.get("status", "active"),
            "predecessor_to": s.get("predecessor_to"),
            "successor_to": s.get("successor_to"),
            "historical_notes": s.get("historical_notes"),
        }
        rows.append((
            s["id"],
            s["store_id"],
            s["code"],
            s["label"],
            s["valid_from"],
            s["valid_to"],
            json.dumps(s.get("aliases", [])),
            json.dumps(payload),
            directory_id,
        ))

    con.executemany(
        """
        INSERT OR REPLACE INTO library_stores (
            id, store_id, code, label, valid_from, valid_to, aliases_json, payload_json, directory_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    con.commit()
    return len(rows)


def resolve_store_for_occurrence(
    lat: Optional[float],
    lon: Optional[float],
    capture_date: Optional[str] = None,
    max_radius_m: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    """
    Resolve GPS coordinates and capture date to a canonical store entry.
    Handles temporal validity (e.g. US-192 NC192 pre-2019 vs The Loop NCLP 2019+).
    """
    if lat is None or lon is None:
        return None

    best_match = None
    min_distance = float("inf")

    for s in STORE_REGISTRY:
        s_radius = max_radius_m if max_radius_m is not None else s.get("radius_m", 450)
        dist = haversine_m(lat, lon, s["lat"], s["lon"])
        if dist <= s_radius:
            # Check temporal validity if capture_date is available (YYYY-MM-DD)
            if capture_date:
                cd = capture_date[:10]
                if s["valid_from"] and cd < s["valid_from"]:
                    continue
                if s["valid_to"] and cd > s["valid_to"]:
                    continue

            if dist < min_distance:
                min_distance = dist
                best_match = {
                    "store": s,
                    "distance_m": round(dist, 1),
                }

    return best_match


if __name__ == "__main__":
    pilot_db = Path("/Users/daplug/Documents/SACC_Data/library/staging/sacc-library-pilot.sqlite3")
    if pilot_db.exists():
        con = sqlite3.connect(pilot_db)
        count = seed_store_directory(con)
        con.close()
        print(f"Successfully seeded {count} canonical stores into {pilot_db}")
