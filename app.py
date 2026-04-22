"""
Sneaker Archive Command Center (SACC) — app.py
Run: streamlit run app.py
"""

import streamlit as st
import pandas as pd
import json
import os
import re
import time
import sys
from pathlib import Path

# Bring in the external modules
sys.path.append("/Users/miniman/Documents/Sneaker_Scripts")
try:
    from compress_jordans import run_compression
except ImportError:
    pass # Handle gracefully if missing

from gemini_pipeline import analyze_sneaker_video

# ─────────────────────────────────────────────
# PAGE CONFIG
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="SACC — Sneaker Archive Command Center",
    page_icon="👟",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────
# GLOBAL CSS
# ─────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

html, body, [class*="css"]  { font-family: 'Inter', sans-serif; }

/* Override pure dark mode components */
.stApp { background-color: #F8FAFC; }
.stMarkdown { color: #1E293B; }
h1, h2, h3, h4, h5, h6 { color: #0F172A !important; }

/* Sidebar */
section[data-testid="stSidebar"] { background: #FFFFFF; border-right: 1px solid #E2E8F0; }
section[data-testid="stSidebar"] * { color: #475569 !important; }

/* Intake Station */
.intake-station {
    border: 2px dashed #10B981;
    border-radius: 16px;
    background-color: #ECFDF5;
    padding: 30px;
    text-align: center;
    margin-bottom: 5px;
    box-shadow: 0 4px 6px -1px rgba(16, 185, 129, 0.1);
}
.intake-title { font-weight: 700; font-size: 1.3em; color: #047857; margin-bottom: 5px; }

/* Cards */
.metric-card-emerald {
    background: linear-gradient(135deg, #059669, #047857);
    border-radius: 16px;
    padding: 24px;
    box-shadow: 0 10px 15px -3px rgba(5, 150, 105, 0.3);
    height: 140px;
}
.metric-card-emerald .metric-val { font-size: 2.8em; font-weight:700; color:#FFFFFF; line-height: 1; margin-bottom:8px;}
.metric-card-emerald .metric-lbl { font-size: 0.9em; font-weight:600; color:#D1FAE5; margin-top: 8px; }

.metric-card {
    background: #FFFFFF;
    border: 1px solid #E2E8F0;
    border-radius: 16px;
    padding: 24px;
    box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
    height: 140px;
}
.metric-card .metric-val { font-size: 2.8em; font-weight:700; color:#0F172A; line-height: 1; margin-bottom:8px;}
.metric-card .metric-lbl { font-size: 0.9em; font-weight:600; color:#64748B; margin-top: 8px; }

/* Status Badges */
.status-pill {
    padding: 6px 12px; border-radius: 20px;
    font-weight: 600; font-size: 0.85em; display: inline-block;
}
.pill-success { background:#D1FAE5; color:#065F46; }
.pill-processing { background:#FEF3C7; color:#92400E; }
.pill-error { background:#FEE2E2; color:#991B1B; }
.pill-pending { background:#F1F5F9; color:#475569; }

/* Queue rows */
.queue-row {
    background: #FFFFFF;
    border: 1px solid #E2E8F0;
    border-radius: 8px;
    padding: 12px 16px;
    margin-bottom: 8px;
    display: flex;
    justify-content: space-between;
    align-items: center;
}
.queue-file { font-weight: 600; color: #1E293B; font-size: 14px; }
.queue-state { font-size: 13px; color: #64748B; }

</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────
# SIDEBAR — CONFIGURATION
# ─────────────────────────────────────────────
with st.sidebar:
    st.markdown("## ⚙️ Configuration")
    st.markdown("---")

    nike_dir = st.text_input(
        "Nike JSON Directory",
        value="",
        help="Path to folder containing your Nike JSON files (optional)"
    )
    whitelist_path = st.text_input(
        "Whitelist JSON Path",
        value="/Users/miniman/SACC/whitelist.json",
        help="Path to your whitelist.json file"
    )
    st.markdown("---")
    st.markdown("**Filter Options**")
    model_filter = st.multiselect(
        "Model Type",
        ["Air Jordan 1 High OG", "Air Jordan 1 High '85", "Air Jordan 1 Low OG"],
        default=[]
    )
    year_range = st.slider("Release Year Range", 2010, 2026, (2010, 2026))

# ─────────────────────────────────────────────
# DATA LOADERS
# ─────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def load_whitelist(path):
    try:
        with open(path, "r") as f:
            return pd.DataFrame(json.load(f))
    except Exception as e:
        return pd.DataFrame()

@st.cache_data(show_spinner=False)
def load_json_collection(directory):
    """
    Recursively walk a directory, load every .json file,
    and attempt to extract sneaker metadata from multiple
    possible schema shapes (StockX, GOAT, Nike, custom).
    Returns a DataFrame of found records.
    """
    records = []
    if not directory or not os.path.exists(directory):
        return pd.DataFrame()

    json_files = list(Path(directory).rglob("*.json"))

    for jf in json_files:
        try:
            with open(jf, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception:
            continue

        # Handle list payloads (e.g. raw dump arrays)
        items = payload if isinstance(payload, list) else [payload]

        for item in items:
            if not isinstance(item, dict):
                continue

            # ── Common field aliases across StockX / GOAT / Nike schemas ──
            name         = (item.get("name") or item.get("title") or
                            item.get("model_name") or item.get("shoe") or "Unknown")
            style_code   = (item.get("styleId") or item.get("style_code") or
                            item.get("sku") or item.get("style") or "")
            colorway     = (item.get("colorway") or item.get("colorway_name") or
                            item.get("color") or "")
            release_date = (item.get("releaseDate") or item.get("release_date") or
                            item.get("year") or "")
            retail_price = (item.get("retailPrice") or item.get("retail_price") or
                            item.get("msrp") or item.get("price") or 0)
            brand        = (item.get("brand") or item.get("make") or "Jordan")

            # Pull from nested traits list (StockX browse schema)
            if isinstance(item.get("traits"), list):
                for trait in item["traits"]:
                    if trait.get("name") == "Release Date":
                        release_date = release_date or trait.get("value", "")
                    if trait.get("name") == "Style":
                        style_code = style_code or trait.get("value", "")
                    if trait.get("name") == "Colorway":
                        colorway = colorway or trait.get("value", "")

            # Try to extract style code from the filename itself as fallback
            if not style_code:
                sc_match = re.search(r'([A-Za-z0-9]{6}-[A-Za-z0-9]{3})', jf.stem)
                if sc_match:
                    style_code = sc_match.group(1).upper()

            # Normalise release year
            year_str = str(release_date)[:4] if release_date else ""

            records.append({
                "source_file": jf.name,
                "model_name":  name,
                "style_code":  style_code.upper() if style_code else "",
                "colorway":    colorway,
                "release_year": year_str,
                "retail_price": retail_price,
                "brand":       brand,
            })

    return pd.DataFrame(records) if records else pd.DataFrame()


def run_preflight_dedup(source_folder):
    """
    Pre-flight duplicate scanner.
    Step 1: Group by exact file size (fast)
    Step 2: Hash first+last 1MB of same-size files to confirm true duplicates
    Returns: list of confirmed duplicate groups [{size_mb, files:[...]}]
    """
    import hashlib
    from collections import defaultdict

    if not source_folder or not os.path.exists(source_folder):
        return []

    all_files = [f for f in Path(source_folder).iterdir()
                 if f.suffix.lower() in ('.mp4', '.mov') and not f.name.startswith('.')]

    by_size = defaultdict(list)
    for f in all_files:
        try:
            by_size[f.stat().st_size].append(f)
        except:
            pass

    confirmed = []
    for size, files in by_size.items():
        if len(files) < 2:
            continue
        # Fast partial hash
        hashes = defaultdict(list)
        chunk = 1024 * 1024  # 1MB
        for f in files:
            h = hashlib.md5()
            try:
                with open(f, 'rb') as fh:
                    h.update(fh.read(chunk))
                    fh.seek(-min(chunk, size - chunk), 2)
                    h.update(fh.read(chunk))
                hashes[h.hexdigest()].append(f.name)
            except:
                pass
        for digest, names in hashes.items():
            if len(names) > 1:
                confirmed.append({"size_mb": round(size / 1024 / 1024, 1), "files": names})
    return confirmed



# Emptying the old duplicate LOAD DATA block to resolve NameError

st.markdown("""
<div style='display:flex; align-items:center; margin-bottom:20px;'>
  <div style='background: linear-gradient(135deg, #10B981, #047857); padding: 12px; border-radius: 12px; margin-right: 16px; box-shadow: 0 4px 6px -1px rgba(16, 185, 129, 0.2);'>
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"></path>
          <polyline points="3.27 6.96 12 12.01 20.73 6.96"></polyline>
          <line x1="12" y1="22.08" x2="12" y2="12"></line>
      </svg>
  </div>
  <div>
      <h1 style='color:#0F172A; font-size:2.2em; margin:0; line-height: 1.1;'>Command Center</h1>
      <p style='color:#64748B; margin: 4px 0 0 0; font-weight:500;'>Sneaker Archive Pipeline Visualization</p>
  </div>
</div>
""", unsafe_allow_html=True)

st.markdown("""
<div class='intake-station'>
    <svg width="68" height="68" viewBox="0 0 24 24" fill="none" stroke="#10B981" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" style="margin-bottom: 12px;">
        <rect x="2" y="3" width="20" height="14" rx="2" ry="2"></rect><line x1="8" y1="21" x2="16" y2="21"></line><line x1="12" y1="17" x2="12" y2="21"></line>
    </svg>
    <div class='intake-title'>Direct External Drive Pipeline</div>
    <div style='color:#065F46; font-size: 0.95em; font-weight: 500;'>
        Files will be modified <b>in-place</b> directly on your external FCP Hard Drives. Absolutely no copies will be buffered.
    </div>
</div>
""", unsafe_allow_html=True)

asset_dir = st.session_state.get("sacc_target_path", "")

st.write("---")

# ─────────────────────────────────────────────
# LOAD DATA & INDEXING
# ─────────────────────────────────────────────
whitelist_df = load_whitelist(whitelist_path)

with st.spinner("Indexing JSON collections from the Ingestion Pipeline…"):
    jordan_df = load_json_collection(asset_dir)
    nike_df   = load_json_collection(nike_dir) if nike_dir else pd.DataFrame()

# Merge both collections
collection_df = pd.concat([jordan_df, nike_df], ignore_index=True) if not nike_df.empty else jordan_df

# Apply sidebar filters
if not collection_df.empty:
    if model_filter:
        collection_df = collection_df[collection_df["model_name"].isin(model_filter)]
    if "release_year" in collection_df.columns:
        collection_df = collection_df[
            collection_df["release_year"].apply(
                lambda y: year_range[0] <= int(y) <= year_range[1] if y.isdigit() else True
            )
        ]

# ─────────────────────────────────────────────
# TABS
# ─────────────────────────────────────────────
tab_hud, tab_search, tab_verify, tab_review, tab_renamer = st.tabs([
    "Dashboard",
    "Search & Index",
    "Verification View",
    "Architect's Review",
    "Vibe Renamer",
])

# ══════════════════════════════════════════════
# TAB 1 — HUD DASHBOARD
# ══════════════════════════════════════════════
with tab_hud:
    # ── KPI METRICS ROW ──
    col1, col2, col3, col4 = st.columns(4)
    total_wl  = len(whitelist_df) if not whitelist_df.empty else 0
    total_col = len(collection_df)

    if not whitelist_df.empty and not collection_df.empty:
        matched = collection_df[collection_df["style_code"].isin(whitelist_df["style_code"].str.upper())]
        unmatched = collection_df[~collection_df["style_code"].isin(whitelist_df["style_code"].str.upper())]
    else:
        matched, unmatched = pd.DataFrame(), collection_df

    with col1:
        st.markdown(f"""<div class='metric-card-emerald'>
            <div class='metric-val'>{total_wl}</div>
            <div class='metric-lbl'>Total Masters</div>
        </div>""", unsafe_allow_html=True)
    with col2:
        st.markdown(f"""<div class='metric-card'>
            <div class='metric-val'>{total_col}</div>
            <div class='metric-lbl'>Indexed Records</div>
        </div>""", unsafe_allow_html=True)
    with col3:
        st.markdown(f"""<div class='metric-card'>
            <div class='metric-val' style='color:#059669;'>{len(matched)}</div>
            <div class='metric-lbl'>Verified Matches</div>
        </div>""", unsafe_allow_html=True)
    with col4:
        st.markdown(f"""<div class='metric-card'>
            <div class='metric-val' style='color:#DC2626;'>{len(unmatched)}</div>
            <div class='metric-lbl'>Action Required</div>
        </div>""", unsafe_allow_html=True)

    st.write("---")

    # ── PRE-FLIGHT DEDUP SCAN ──
    pf_col1, pf_col2 = st.columns([2, 8])
    with pf_col1:
        scan_btn = st.button("Run Pre-Flight Scan", use_container_width=True)
    if scan_btn and asset_dir:
        with st.spinner("Scanning for duplicates before batch starts..."):
            dupes = run_preflight_dedup(asset_dir)
        if not dupes:
            st.success(f"Pre-flight clear — no duplicate footage detected in `{asset_dir}`. Safe to start batch.")
        else:
            st.warning(f"Found {len(dupes)} confirmed duplicate group(s). Review before processing to avoid wasting API calls!")
            for g in dupes:
                st.markdown(f"**[{g['size_mb']} MB — exact match]**")
                for fname in g['files']:
                    st.markdown(f"  - `{fname}`")

    st.write("---")

    # ── BATCH PIPELINE LOGIC ──
    col_play, col_pad = st.columns([3, 7])
    with col_play:
        run_btn = st.button("Start Batch Processing", type="primary", use_container_width=True)
        
    if run_btn:
        # Phase 1: Compressor
        try:
            compression_results = run_compression(asset_dir)
        except Exception as e:
            st.error("Failed to run Apple Compressor script.")
            compression_results = []
        
        if not compression_results:
            st.warning("No uncompressed video files queued for Apple Compressor.")
        else:
            total_files = len(compression_results)
            
            # Master live view
            st.markdown("### Active Project Progress")
            
            prog_col1, prog_col2 = st.columns([1, 2])
            with prog_col1:
                metric_pct = st.empty()
            with prog_col2:
                metric_status = st.empty()
            
            pb = st.progress(0)
            
            # File queue expander
            with st.expander("View Full Queue Detailed Status", expanded=True):
                queue_container = st.empty()
            
            st.markdown("### Export Results (Live Updating)")
            live_table = st.empty()
            
            final_stats = []
            
            for i, item in enumerate(compression_results):
                fp_original = item["original"]
                fp_compressed = item["compressed_path"]
                
                pct_done = int((i / total_files) * 100)
                metric_pct.markdown(f"<h2 style='margin:0; color:#059669;'>{pct_done}%</h2><p style='color:#64748B;'>Batch Completed ({i} / {total_files})</p>", unsafe_allow_html=True)
                
                # Wait for compressor
                timeout = 600
                slept = 0
                while not os.path.exists(fp_compressed) and slept < timeout:
                    metric_status.info(f"**Compressing [{fp_original}]** — Apple Compressor running on {asset_dir} ({slept}s elapsed)")
                    # Update queue vis
                    q_html = ""
                    for j, qitem in enumerate(compression_results):
                        state = "Pending" if j > i else ("Compressing..." if j == i else "Completed")
                        pill_class = "pill-processing" if j == i else ("pill-success" if j < i else "pill-pending")
                        q_html += f"<div class='queue-row'><div class='queue-file'>{qitem['original']}</div><div class='queue-state'><span class='status-pill {pill_class}'>{state}</span></div></div>"
                    queue_container.markdown(q_html, unsafe_allow_html=True)
                    time.sleep(2)
                    slept += 2
                
                if not os.path.exists(fp_compressed):
                    final_stats.append({"File": fp_original, "Status": "Compression Timeout", "SKU": "—", "Gemini_Model": "—"})
                    continue
                
                # Gemini Analysis
                metric_status.warning(f"**Analyzing [{fp_original}]** — Gemini API Multimodal Inference in progress...")
                parsed_json = analyze_sneaker_video(fp_compressed)
                    
                if "error" in parsed_json:
                    final_stats.append({"File": fp_original, "Status": f"Gemini Error", "SKU": "—", "Gemini_Model": "—"})
                    continue
                
                sku = parsed_json.get("SKU", "—")
                model_name = parsed_json.get("Model", "Unknown")
                
                verified = sku and not whitelist_df.empty and sku in whitelist_df["style_code"].str.upper().values
                status = "✅ Verified" if verified else "❌ Unmatched"
                
                if sku != "—":
                    new_filename = f"{sku}_{model_name.replace(' ', '_')}.mp4"
                    new_filepath = os.path.join(os.path.dirname(fp_compressed), new_filename)
                    try:
                        # Rename the compressed file
                        os.rename(fp_compressed, new_filepath)
                        
                        # Generate the Missing Metadata JSON File
                        json_payload = {
                            "source_file": new_filename,
                            "style_code": sku,
                            "model_name": model_name,
                            "verified_against_whitelist": verified
                        }
                        
                        # Enrich JSON with Whitelist data if matched
                        if verified:
                            match_row = whitelist_df[whitelist_df["style_code"].str.upper() == sku.upper()].iloc[0]
                            json_payload["colorway"] = match_row.get("colorway", match_row.get("colorway_name", ""))
                            json_payload["release_year"] = str(match_row.get("release_date", match_row.get("release_year", "")))
                            json_payload["retail_price"] = str(match_row.get("retail_price", match_row.get("price", "")))
                            json_payload["brand"] = match_row.get("brand", "Jordan")
                        else:
                            json_payload["colorway"] = ""
                            json_payload["release_year"] = ""
                            json_payload["retail_price"] = ""
                            json_payload["brand"] = "Unknown"
                            json_payload["needs_review"] = True
                            
                        # Save JSON side-by-side with the renamed MP4!
                        json_filepath = os.path.join(os.path.dirname(fp_compressed), f"{sku}_{model_name.replace(' ', '_')}.json")
                        with open(json_filepath, 'w') as jf:
                            json.dump(json_payload, jf, indent=4)
                        
                        # Move the original RAW file — name it after the shoe, NO RAW_ prefix
                        raw_complete_dir = os.path.join(asset_dir, "Processed_RAW")
                        if not os.path.exists(raw_complete_dir):
                            os.makedirs(raw_complete_dir)

                        orig_filepath = os.path.join(asset_dir, fp_original)
                        # Archive name = just the shoe name, same as the compressed file
                        archived_raw_name = new_filename  # e.g. 555088-015_Air_Jordan_1.mp4
                        new_orig_filepath = os.path.join(raw_complete_dir, archived_raw_name)

                        if os.path.exists(orig_filepath):
                            os.rename(orig_filepath, new_orig_filepath)
                            
                    except Exception as e:
                        pass
                
                final_stats.append({"File": fp_original, "Status": status, "SKU": sku, "Gemini_Model": model_name})
                
                # Update the live table to show passed/failed instantly!
                live_table.dataframe(pd.DataFrame(final_stats), hide_index=True, use_container_width=True)
                
                pb.progress((i + 1) / len(compression_results))
                
            metric_pct.markdown(f"<h2 style='margin:0; color:#059669;'>100%</h2><p style='color:#64748B;'>Project Ended ({total_files} / {total_files})</p>", unsafe_allow_html=True)
            metric_status.success("All processing finished completely!")
            
            # Final Queue Render
            q_html = ""
            for item in compression_results:
                q_html += f"<div class='queue-row'><div class='queue-file'>{item['original']}</div><div class='queue-state'><span class='status-pill pill-success'>Completed</span></div></div>"
            queue_container.markdown(q_html, unsafe_allow_html=True)

# ══════════════════════════════════════════════
# TAB 2 — SEARCH & INDEX
# ══════════════════════════════════════════════
with tab_search:
    st.markdown("### 🔍 Search Your JSON Collection")
    st.caption(f"Indexing **{total_col}** records across Jordan & Nike archives")

    col_s1, col_s2 = st.columns([8, 2])
    with col_s1:
        query = st.text_input("Search Query", placeholder="Search by name, style code, or colorway (e.g. Chicago, 555088-101)", label_visibility="collapsed")
    with col_s2:
        st.button("🔍 Search", use_container_width=True, type="primary")

    col_a, col_b, col_c = st.columns(3)
    with col_a:
        brand_filter = st.selectbox("Brand", ["All", "Jordan", "Nike"], index=0)
    with col_b:
        sort_by = st.selectbox("Sort By", ["model_name", "release_year", "retail_price"], index=1)
    with col_c:
        sort_dir = st.radio("Direction", ["Ascending", "Descending"], horizontal=True)

    # Apply search
    results_df = collection_df.copy()
    if query:
        mask = (
            results_df["model_name"].str.contains(query, case=False, na=False) |
            results_df["style_code"].str.contains(query, case=False, na=False) |
            results_df["colorway"].str.contains(query, case=False, na=False)
        )
        results_df = results_df[mask]

    if brand_filter != "All":
        results_df = results_df[results_df["brand"].str.contains(brand_filter, case=False, na=False)]

    if sort_by in results_df.columns:
        results_df = results_df.sort_values(
            sort_by, ascending=(sort_dir == "Ascending")
        ).reset_index(drop=True)

    st.markdown(f"**{len(results_df)}** results found")

    # Tag metadata verification column
    if not results_df.empty:
        def verify_metadata(row):
            issues = []
            if not row.get("style_code"): issues.append("Missing style code")
            if not row.get("colorway"):   issues.append("Missing colorway")
            if not row.get("release_year"): issues.append("Missing year")
            return "✅ OK" if not issues else "⚠️ " + ", ".join(issues)

        results_df["Metadata Status"] = results_df.apply(verify_metadata, axis=1)

    st.dataframe(
        results_df[["model_name","style_code","colorway","release_year","retail_price","brand","Metadata Status"]]
        if not results_df.empty and "Metadata Status" in results_df.columns
        else results_df,
        hide_index=True,
        use_container_width=True,
    )

    if not results_df.empty:
        csv = results_df.to_csv(index=False).encode("utf-8")
        st.download_button("⬇️ Export Results to CSV", csv, "sacc_search_results.csv", "text/csv")

# ══════════════════════════════════════════════
# TAB 3 — VERIFICATION VIEW
# ══════════════════════════════════════════════
with tab_verify:
    st.markdown("### ✅ Whitelist Verification View")
    st.caption("Compares your existing collection against the whitelist to identify missing models.")

    if whitelist_df.empty:
        st.error("Whitelist not loaded. Check the path in the sidebar.")
    else:
        wl = whitelist_df.copy()
        wl["style_code_upper"] = wl["style_code"].str.upper()

        col_df = collection_df.copy()
        col_style_codes = set(col_df["style_code"].str.upper().dropna().tolist()) if not col_df.empty else set()

        wl["Status"] = wl["style_code_upper"].apply(
            lambda sc: "✅ Found" if sc in col_style_codes else "❌ Missing"
        )

        # Summary
        found_count   = (wl["Status"] == "✅ Found").sum()
        missing_count = (wl["Status"] == "❌ Missing").sum()
        coverage_pct  = round(found_count / len(wl) * 100, 1) if len(wl) else 0

        cv1, cv2, cv3 = st.columns(3)
        cv1.metric("Whitelist Total", len(wl))
        cv2.metric("Found in Collection", found_count, delta=f"{coverage_pct}% coverage")
        cv3.metric("Still Missing", missing_count, delta=f"-{missing_count}", delta_color="inverse")

        st.progress(coverage_pct / 100, text=f"Collection coverage: {coverage_pct}%")
        st.markdown("---")

        view_mode = st.radio(
            "Show:", ["All", "✅ Found Only", "❌ Missing Only"],
            horizontal=True
        )
        display_wl = wl.copy()
        if view_mode == "✅ Found Only":
            display_wl = display_wl[display_wl["Status"] == "✅ Found"]
        elif view_mode == "❌ Missing Only":
            display_wl = display_wl[display_wl["Status"] == "❌ Missing"]

        # Optionally filter by model type
        model_types = display_wl["model_name"].unique().tolist() if "model_name" in display_wl else []
        if model_types:
            model_pick = st.multiselect("Filter by Model", model_types, default=model_types)
            display_wl = display_wl[display_wl["model_name"].isin(model_pick)]

        cols_show = [c for c in ["model_name","style_code","colorway_name","release_date","retail_price","Status"]
                     if c in display_wl.columns]
        st.dataframe(display_wl[cols_show].reset_index(drop=True), hide_index=True, use_container_width=True)

        # Year breakdown chart
        st.markdown("#### Missing Models by Year")
        missing_df = wl[wl["Status"] == "❌ Missing"]
        if not missing_df.empty and "release_date" in missing_df.columns:
            year_counts = missing_df["release_date"].value_counts().sort_index()
            st.bar_chart(year_counts)

        # Export missing
        if not missing_df.empty:
            csv_miss = missing_df.to_csv(index=False).encode("utf-8")
            st.download_button("⬇️ Export Missing List", csv_miss, "sacc_missing_models.csv", "text/csv")

# ══════════════════════════════════════════════
# TAB 4 — ARCHITECT'S REVIEW
# ══════════════════════════════════════════════
with tab_review:
    st.markdown("### 🏗️ The Architect's Review")
    st.caption("Files / records that failed validation, lack style codes, or have incomplete metadata.")

    if collection_df.empty:
        st.warning("No JSON records loaded. Check your directory paths in the sidebar.")
    else:
        problems = []
        for _, row in collection_df.iterrows():
            issues = []
            if not row.get("style_code"):       issues.append("No style code")
            if not row.get("colorway"):         issues.append("No colorway")
            if not row.get("release_year"):     issues.append("No release year")
            if str(row.get("retail_price","0")) in ["0","0.0",""]: issues.append("No retail price")
            if issues:
                problems.append({
                    "Source File":   row.get("source_file",""),
                    "Model Name":    row.get("model_name",""),
                    "Style Code":    row.get("style_code","—"),
                    "Issues":        " | ".join(issues),
                })

        if not problems:
            st.success("🎉 All records passed metadata validation. Nothing to review.")
        else:
            st.error(f"{len(problems)} records require your manual verification.")
            problem_df = pd.DataFrame(problems)
            st.dataframe(problem_df, hide_index=True, use_container_width=True)
            
            st.markdown("### Manual Metadata Patcher")
            st.info("Pick a file from the problem list above to manually patch its missing data. The system will permanently update the underlying JSON file on your drive.")
            
            with st.form("patch_metadata_form"):
                file_options = problem_df["Source File"].tolist()
                selected_file = st.selectbox("Select File to Patch:", file_options)
                
                # Fetch existing data to assist the user
                existing_row = collection_df[collection_df["source_file"] == selected_file].iloc[0] if not collection_df.empty else None
                known_model = existing_row.get("model_name", "") if existing_row is not None else ""
                known_style = existing_row.get("style_code", "") if existing_row is not None else ""
                
                st.markdown(f"**Google Fast-Search Link:**  [Search Google for {known_model} {known_style}](https://www.google.com/search?q={known_style}+stockx+retail+price+colorway)  *(opens in new tab)*")
                
                col_p1, col_p2, col_p3 = st.columns(3)
                patch_colorway = col_p1.text_input("Colorway (e.g. Chicago, Bred)", value="")
                patch_year = col_p2.text_input("Release Year (e.g. 2015)", value="")
                patch_price = col_p3.text_input("Retail Price (e.g. 180)", value="")
                
                submit_patch = st.form_submit_button("Patch & Save JSON to Drive", type="primary")
                
                if submit_patch:
                    # Find the exact json file path
                    target_json_path = ""
                    for f in Path(asset_dir).rglob(selected_file):
                        target_json_path = str(f)
                        break
                        
                    if target_json_path and os.path.exists(target_json_path):
                        with open(target_json_path, "r") as jf:
                            payload = json.load(jf)
                            
                        # Update it!
                        if patch_colorway: payload["colorway"] = patch_colorway
                        if patch_year: payload["release_year"] = patch_year
                        if patch_price: payload["retail_price"] = patch_price
                        payload["needs_review"] = False
                        
                        with open(target_json_path, "w") as jf:
                            json.dump(payload, jf, indent=4)
                        
                        st.success(f"Successfully patched {selected_file}! Refresh to see it vanish from the review queue.")
                    else:
                        st.error(f"Could not locate the physical JSON file for {selected_file} in {asset_dir}.")

# ══════════════════════════════════════════════
# TAB 5 — VIBE RENAMER
# ══════════════════════════════════════════════
try:
    from renamer_logic import LOCATION_DATA, run_vibe_renamer
except ImportError:
    LOCATION_DATA = {}
    def run_vibe_renamer(*args, **kwargs):
        return {"error": "renamer_logic.py not found."}

import streamlit.components.v1 as components

with tab_renamer:
    st.markdown("### 🎬 Vibe Batch Renamer")
    st.caption("Predictive No-Mouse Interface: Ghost-text search instantly processes heavy ingestions locally.")
    
    # Render Native App Picker and Target Path ONLY in this tab
    st.markdown("#### 1. Select Target Directory")
    col_path1, col_path2 = st.columns([8, 2])
    with col_path1:
        asset_dir_input = st.text_input("Renamer Target Path", value=st.session_state.get("sacc_target_path", ""), placeholder="e.g. /Volumes/Final_Drive_5TB/RAW_Footage", label_visibility="collapsed")
    with col_path2:
        if st.button("📁 Native App Picker", use_container_width=True):
            import subprocess
            cmd = """osascript -e 'tell application (path to frontmost application as text)' -e 'set myFolder to choose folder with prompt "Select the Target Directory for Processing"' -e 'return POSIX path of myFolder' -e 'end tell'"""
            res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            if res.returncode == 0 and res.stdout.strip():
                st.session_state["sacc_target_path"] = res.stdout.strip()
                st.rerun()
                
    if asset_dir_input != st.session_state.get("sacc_target_path"):
        st.session_state["sacc_target_path"] = asset_dir_input
        
    st.write("---")
    st.markdown("#### 2. Execute Vibe Renamer")
    
    # Trigger variables
    qp = st.query_params
    triggered = False
    loc = None
    target_id = None
    
    # Check JS Query Param Trigger
    if "renamer_trigger" in qp:
        loc = qp.get("loc")
        target_id = qp.get("id")
        triggered = True
        st.query_params.clear()
        
    # Check Native Form Trigger
    if st.session_state.get("native_renamer_trigger"):
        loc = st.session_state.get("native_loc")
        target_id = st.session_state.get("native_id")
        triggered = True
        st.session_state["native_renamer_trigger"] = False
        
    if triggered and loc and target_id:
        st.markdown(f"**Processing videos into {loc} with {target_id}...**")
        
        progress_bar = st.progress(0)
        status_text = st.empty()
        log_container = st.empty()
        
        logs = []
        final_res = None
        
        # Consume Generator
        for status in run_vibe_renamer(asset_dir, loc, target_id):
            if "error" in status:
                st.error(status["error"])
                break
                
            if status.get("done"):
                final_res = status
                break
                
            current = status["current"]
            total = status["total"]
            pct = current / total
            
            progress_bar.progress(pct)
            status_text.markdown(f"Renaming file **{current}** of **{total}** ({(pct*100):.0f}%)")
            
            logs.append(f"[{current}/{total}] {status['original']} ➔ {status['new']}")
            
            # Throttle UI updates to prevent "boggling"
            if current % 5 == 0 or current == total:
                log_container.code("\n".join(logs[-15:]), language="bash")
                
        if final_res:
            st.success(f"✨ Successfully processed {final_res['processed_count']} files in {final_res['elapsed_seconds']}s!")
            with st.expander("View Detailed Rename Audit Log"):
                for r in final_res.get("results", []):
                    st.write(f"✅ `{r['new']}`")
                    
    tab_js, tab_native = st.tabs(["⚡ Ghost-Text Interface", "🛠️ Manual Entry"])
    
    with tab_native:
        with st.form("native_renamer_form"):
            col_n1, col_n2 = st.columns(2)
            loc_options = [f"{c} — {d['name']}" for c, d in LOCATION_DATA.items()]
            sel_loc = col_n1.selectbox("Location Code", loc_options)
            sel_id = col_n2.text_input("Identifier", placeholder="e.g. Kobe12")
            
            submit_native = st.form_submit_button("▶ Run Batch Renamer", type="primary", use_container_width=True)
            if submit_native and sel_loc and sel_id:
                st.session_state["native_renamer_trigger"] = True
                st.session_state["native_loc"] = sel_loc.split(" — ")[0]
                st.session_state["native_id"] = sel_id
                st.rerun()

    with tab_js:

        # Build Javascript component
        loc_array = [{"code": c, "name": d["name"], "type": d["type"], "region": d.get("region", "")} for c, d in LOCATION_DATA.items()]
        js_locs = json.dumps(loc_array)
        
        html_code = f"""
        <!DOCTYPE html>
        <html>
        <head>
        <style>
        body {{ font-family: 'Inter', sans-serif; margin: 0; padding: 10px; background: transparent; }}
        .container {{ display: flex; gap: 15px; align-items: flex-start; }}
        .input-column {{ flex: 1; display: flex; flex-direction: column; gap: 8px; }}
        .input-wrapper {{ position: relative; width: 100%; }}
        .search-input {{ 
            width: 100%; padding: 14px 18px; font-size: 16px; border: 2px solid #E2E8F0; 
            border-radius: 8px; background: white; color: #1E293B; outline: none;
            box-sizing: border-box; transition: border 0.2s; font-family: 'Inter', sans-serif;
        }}
        .search-input:focus {{ border-color: #10B981; box-shadow: 0 4px 6px -1px rgba(16,185,129,0.1); background: #FAFAFA; }}
        
        .suggestion-box {{
            padding: 0 4px; font-size: 15px; color: #047857; font-weight: 600; 
            display: none; align-items: center; gap: 8px; font-family: 'Inter', sans-serif;
        }}
        .suggestion-hint {{ color: #94A3B8; font-size: 12px; font-weight: 500; background: #F1F5F9; padding: 3px 6px; border-radius: 4px; }}
    
        .tag {{
            position: absolute; right: 12px; top: 14px; font-size: 11px; padding: 4px 10px;
            border-radius: 20px; background: #059669; color: #ffffff; font-weight: 700;
            display: none; letter-spacing: 0.5px; z-index: 3; font-family: 'Inter', sans-serif;
        }}
        </style>
        </head>
        <body onload="document.getElementById('search').focus()">
        <div class="container">
            <div class="input-column">
                <div class="input-wrapper">
                    <input type="text" id="search" class="search-input" placeholder="Search by name, code, or region (e.g. Miami)" autocomplete="off" spellcheck="false">
                    <span id="typeTag" class="tag">MALL</span>
                </div>
                <div id="suggestionBox" class="suggestion-box">
                    <span id="ghostText">Florida Mall</span>
                    <span class="suggestion-hint">Press Tab or →</span>
                </div>
            </div>
            <div class="input-column">
                <div class="input-wrapper">
                    <input type="text" id="identifier" class="search-input" placeholder="Identifier (e.g. Kobe12)">
                </div>
            </div>
            <div>
                <button id="runBtn" style="height: 52px; padding: 0 24px; font-size: 16px; border: none; border-radius: 8px; background: #10B981; color: white; font-weight: 600; cursor: pointer; font-family: 'Inter', sans-serif; transition: background 0.2s;">▶ Run Renamer</button>
            </div>
        </div>
        <script>
        const locs = {js_locs};
        const search = document.getElementById('search');
        const ghost = document.getElementById('ghostText');
        const suggestionBox = document.getElementById('suggestionBox');
        const tag = document.getElementById('typeTag');
        const identifier = document.getElementById('identifier');
        let currentMatch = null;
        
        function levenshtein(a, b) {{
            if(a.length === 0) return b.length;
            if(b.length === 0) return a.length;
            var matrix = [];
            for(let i = 0; i <= b.length; i++){{ matrix[i] = [i]; }}
            for(let j = 0; j <= a.length; j++){{ matrix[0][j] = j; }}
            for(let i = 1; i <= b.length; i++){{
                for(let j = 1; j <= a.length; j++){{
                    if(b.charAt(i-1) == a.charAt(j-1)){{
                        matrix[i][j] = matrix[i-1][j-1];
                    }} else {{
                        matrix[i][j] = Math.min(matrix[i-1][j-1] + 1, Math.min(matrix[i][j-1] + 1, matrix[i-1][j] + 1));
                    }}
                }}
            }}
            return matrix[b.length][a.length];
        }}
    
        search.addEventListener('input', (e) => {{
            const val = e.target.value.trim().toLowerCase();
            currentMatch = null;
            tag.style.display = 'none';
            
            if (!val) {{ suggestionBox.style.display = 'none'; return; }}
            
            let bestMatch = null;
            let lowestScore = 999;
            
            locs.forEach(l => {{
                const n = l.name.toLowerCase();
                const c = l.code.toLowerCase();
                const r = l.region.toLowerCase();
                
                let score = 999;
                
                if (n.includes(val) || c.includes(val) || r.includes(val)) {{
                    score = -10; 
                }} else {{
                    let distName = levenshtein(val, n.substring(0, val.length));
                    let distCode = levenshtein(val, c.substring(0, val.length));
                    let distRegion = levenshtein(val, r.substring(0, val.length));
                    score = Math.min(distName, distCode, distRegion);
                }}
                
                if (score < lowestScore) {{
                    lowestScore = score;
                    bestMatch = l;
                }}
            }});
            
            // Ensure distance is within reason (up to 3 character typos depending on word length)
            if (bestMatch && (lowestScore === -10 || lowestScore <= Math.max(2, Math.floor(val.length / 2)))) {{
                currentMatch = bestMatch;
                ghost.textContent = `${{bestMatch.code}} — ${{bestMatch.name}}`;
                tag.textContent = bestMatch.type;
                
                suggestionBox.style.display = 'flex';
                tag.style.display = 'block';
            }} else {{ 
                suggestionBox.style.display = 'none'; 
            }}
        }});
        
        search.addEventListener('keydown', (e) => {{
            if ((e.key === 'ArrowRight' || e.key === 'Tab') && currentMatch) {{
                e.preventDefault();
                search.value = `${{currentMatch.code}} — ${{currentMatch.name}}`;
                suggestionBox.style.display = 'none';
            }}
            if (e.key === 'Enter' && currentMatch) {{
                e.preventDefault();
                search.value = `${{currentMatch.code}} — ${{currentMatch.name}}`;
                suggestionBox.style.display = 'none';
                identifier.focus();
            }}
        }});
        
        identifier.addEventListener('keydown', (e) => {{
            if (e.key === 'Enter' && identifier.value && currentMatch) {{
                e.preventDefault();
                parent.window.location.search = `?renamer_trigger=1&loc=${{encodeURIComponent(currentMatch.code)}}&id=${{encodeURIComponent(identifier.value)}}`;
            }}
        }});
        
        document.getElementById('runBtn').addEventListener('click', () => {{
            if (identifier.value && currentMatch) {{
                parent.window.location.search = `?renamer_trigger=1&loc=${{encodeURIComponent(currentMatch.code)}}&id=${{encodeURIComponent(identifier.value)}}`;
            }} else {{
                alert('Please select a valid location from the search suggestions and enter an identifier.');
            }}
        }});
        </script>
        </body>
        </html>
        """
        
        components.html(html_code, height=90, scrolling=False)
