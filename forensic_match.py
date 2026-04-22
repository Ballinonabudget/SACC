"""
SACC Forensic RAW File Matcher
================================
READ-ONLY SCRIPT — This script NEVER moves, renames, or deletes files.
It only reads file metadata (size) to cross-reference orphan compressed files
against a source directory to locate their missing RAW originals.

Usage:
    python3 forensic_match.py

Set SOURCE_OF_ORIGINALS below to the path the user provides.
"""

import os
from pathlib import Path
from collections import defaultdict

# ─────────────────────────────────────────────────────────────
# !! CONFIGURE THESE PATHS ONLY !!
# ─────────────────────────────────────────────────────────────
COMPRESSED_FILES = "/Volumes/The Final Cut X/Naagle/Final Drive 5TB/AJ1 Collection VIdeo backup/Slomo Jordan 1 collection/Jordan 1 take 69/Compressed_Files"

SOURCE_OF_ORIGINALS = ""  # ← Paste the source path here when ready. WILL NOT BE TOUCHED.

# ─────────────────────────────────────────────────────────────
# KNOWN ORPHAN COMPRESSED FILES (27 files with no RAW archive)
# These were confirmed by the earlier dedup audit
# ─────────────────────────────────────────────────────────────
ORPHAN_NAMES = [
    "555088-002_Unknown.mp4",
    "555088-015_Air_Jordan_1_Retro_High_OG_'A_Star_Is_Born'.mp4",
    "555088-106_Air_Jordan_1_High_OG_Metallic_Navy.mp4",
    "555088-126_Air_Jordan_1_High_OG_'Light_Smoke_Grey'.mp4",
    "CD6578-507_Nike_SB_x_Air_Jordan_1_High_OG_'LA_to_Chicago'.mp4",
    "None_Air_Jordan_1_Pinnacle_'Black'.mp4",
    "None_Air_Jordan_1_Retro_High_OG_CO.JP_'Midnight_Navy'.mp4",
    "None_Air_Jordan_1_Retro_High_OG_Game_Royal.mp4",
    "Not available in video_Air_Jordan_1_Retro_High_OG_'Wheat'.mp4",
    "Not available_Air_Jordan_1_High_Flyknit_'Royal'.mp4",
    "Not available_Air_Jordan_1_High_OG_'Shattered_Backboard_3.0'.mp4",
    "Not available_Air_Jordan_1_Retro_High_OG_'Prototype'.mp4",
    "Not available_Air_Jordan_1_Retro_High_OG_'Wings'.mp4",
    "Not available_SP_19_Air_Jordan_1_High_OG.mp4",
    "Not shown_Air_Jordan_1_Retro_High_Flyknit_'Bred'.mp4",
    "Not shown_Unknown.mp4",
    "Not specified_Air_Jordan_1_High_OG_'Court_Purple'.mp4",
    "Not specified_Air_Jordan_1_Retro_High_OG_Patent_'Black_Metallic_Gold'.mp4",
    "Not visible_Air_Jordan_1_High_OG_'Bred_Toe'.mp4",
    "Not visible_Air_Jordan_1_High_OG_'Pine_Green_2.0'.mp4",
    "Not visible_Air_Jordan_1_High_OG_Pollen.mp4",
    "Not visible_Air_Jordan_1_High_Zoom_Zen_Green.mp4",
    "Not visible_Air_Jordan_1_Pinnacle_'Black'.mp4",
    "Not visible_Air_Jordan_1_Retro_High_OG_'Black_Gum'.mp4",
    "Not visible_Air_Jordan_1_Retro_High_OG_'Light_Fusion_Red'.mp4",
    "Not visible_Nike_SB_x_Air_Jordan_1_Retro_High_OG_'NYC_to_Paris'.mp4",
    "Not visually available_Unknown.mp4",
]


def get_size(path):
    try:
        return os.path.getsize(path)
    except:
        return 0


def run_forensic_match():
    print("\n" + "=" * 65)
    print("  SACC FORENSIC RAW FILE MATCHER  —  READ-ONLY")
    print("=" * 65)

    if not SOURCE_OF_ORIGINALS:
        print("\n⚠️  SOURCE_OF_ORIGINALS is not set. Edit forensic_match.py and add the path.")
        return

    if not os.path.exists(SOURCE_OF_ORIGINALS):
        print(f"\n❌ Source path does not exist: {SOURCE_OF_ORIGINALS}")
        return

    print(f"\nCompressed folder : {COMPRESSED_FILES}")
    print(f"Source folder     : {SOURCE_OF_ORIGINALS}  [READ-ONLY — will not be modified]")

    # Step 1: Build a size → [filename, path] map of ALL files in the source folder
    print("\n[1/3] Indexing source folder (read-only)...")
    source_by_size = defaultdict(list)
    total_source = 0
    for f in Path(SOURCE_OF_ORIGINALS).rglob("*"):
        if f.is_file() and not f.name.startswith('.'):
            sz = get_size(str(f))
            source_by_size[sz].append(f)
            total_source += 1
    print(f"      Found {total_source} total files in source.")

    # Step 2: Get sizes of the 27 orphan compressed files
    print("\n[2/3] Loading orphan compressed file sizes...")
    orphan_sizes = {}
    for name in ORPHAN_NAMES:
        path = os.path.join(COMPRESSED_FILES, name)
        if os.path.exists(path):
            # Compressed proxy is smaller — we use it as a reference fingerprint
            # Actual RAW will be much larger (~150–200x the compressed size)
            orphan_sizes[name] = get_size(path)
        else:
            print(f"  [WARNING] Orphan not found in Compressed_Files: {name}")

    # Step 3: Try to find size-ratio matches
    # Compressed proxy files are typically 5–8 MB; RAW originals ~850MB–1.5GB
    # We expect RAW size to be roughly 150–300x the compressed proxy size
    print("\n[3/3] Cross-referencing sizes...")

    MATCHED = []
    UNMATCHED = []

    for compressed_name, comp_size in orphan_sizes.items():
        comp_mb  = comp_size / (1024 * 1024)
        min_raw  = comp_size * 100   # RAW should be at least 100x compressed
        max_raw  = comp_size * 350   # and at most 350x

        # Find source files in that size band
        matches = []
        for src_size, src_files in source_by_size.items():
            if min_raw <= src_size <= max_raw:
                for sf in src_files:
                    matches.append((sf, src_size))

        if matches:
            MATCHED.append((compressed_name, comp_mb, matches))
        else:
            UNMATCHED.append((compressed_name, comp_mb))

    # ── Report ──
    print("\n" + "─" * 65)
    print(f"  MATCHES FOUND: {len(MATCHED)} / {len(ORPHAN_NAMES)}")
    print("─" * 65)
    for cname, cmb, candidates in MATCHED:
        print(f"\n  ✅ COMPRESSED : {cname}  ({cmb:.1f} MB)")
        print(f"     CANDIDATES IN SOURCE:")
        for sf, sz in candidates:
            print(f"       → {sf.name}  ({sz/1024/1024/1024:.2f} GB)  [{sf}]")

    print("\n" + "─" * 65)
    print(f"  NO MATCH FOUND: {len(UNMATCHED)} / {len(ORPHAN_NAMES)}")
    print("─" * 65)
    for cname, cmb in UNMATCHED:
        print(f"  ❌  {cname}  ({cmb:.1f} MB)  — no RAW candidate in source folder")

    print("\n" + "=" * 65)
    print("  RESULT SUMMARY")
    print("=" * 65)
    print(f"  Total orphans checked   : {len(ORPHAN_NAMES)}")
    print(f"  Recoverable (matched)   : {len(MATCHED)}")
    print(f"  Unrecoverable (missing) : {len(UNMATCHED)}")
    print("\n  ⚠️  This script made ZERO changes to your files.")
    print("  To execute recovery, a separate confirmed-copy script")
    print("  must be approved and run manually.\n")


if __name__ == "__main__":
    run_forensic_match()
