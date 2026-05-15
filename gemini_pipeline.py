"""
gemini_pipeline.py — SACC Vertex AI / Gemini Video Analysis
=============================================================
Receives proxy file paths and original (renamed) source filenames.
Routes to standard API or Vertex AI Batch Prediction based on file count.

Logic Router
------------
  < 50 files  → Standard API   (immediate, per-file upload + inference)
  >= 50 files → Batch API      (async JSONL job, 50% cost discount)

The threshold is controlled by BATCH_THRESHOLD (default 50).
Batch mode requires GCS_BUCKET in .env. If not set, falls back to standard.

JSON output schema
------------------
Every JSON file written by this module uses the ORIGINAL renamed filename
as its stem, making it the permanent relational key back to the hi-res master:

  Proxy uploaded : _proxy/FLM-MALL_260423_Air-Jordan-1-Chicago_iPhone15ProMax_IMG_3439.mp4
  JSON written   : json/FLM-MALL_260423_Air-Jordan-1-Chicago_iPhone15ProMax_IMG_3439.json

Environment (.env)
------------------
  GEMINI_API_KEY     → Gemini API (Phase 1/2 fallback)
  VERTEX_PROJECT_ID  → Vertex AI project (required for batch mode)
  VERTEX_LOCATION    → us-central1 (default)
  VERTEX_MODEL       → gemini-2.5-pro (default)
  GCS_BUCKET         → GCS bucket name for batch I/O (required for batch mode)
"""

import os
import json
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

# ── Client selection: Vertex AI (preferred) or Gemini API fallback ────────────
_vertex_project  = os.getenv("VERTEX_PROJECT_ID")
_vertex_location = os.getenv("VERTEX_LOCATION", "us-central1")
_gemini_key      = os.getenv("GEMINI_API_KEY")

_USE_VERTEX  = bool(_vertex_project)
_GCS_BUCKET  = os.getenv("GCS_BUCKET", "")
BATCH_THRESHOLD     = int(os.getenv("BATCH_THRESHOLD", "50"))
# Stage 5 — Async Parallel Upload. Standard-API concurrency cap.
# Gemini tolerates moderate concurrency; 3 is a safe default on most plans.
# Bump to 5-8 if you have higher quota. Set to 1 to force fully sequential.
GEMINI_PARALLEL     = max(1, int(os.getenv("GEMINI_PARALLEL", "3")))

if _USE_VERTEX:
    try:
        import vertexai
        from vertexai.generative_models import GenerativeModel, Part
        vertexai.init(project=_vertex_project, location=_vertex_location)
        _VERTEX_MODEL_NAME = os.getenv("VERTEX_MODEL", "gemini-2.5-pro")
        print(f"[gemini] Using Vertex AI — project={_vertex_project} "
              f"location={_vertex_location} model={_VERTEX_MODEL_NAME}")
    except ImportError:
        print("[gemini] WARNING — vertexai SDK not installed. "
              "Falling back to google.generativeai.")
        _USE_VERTEX = False

if not _USE_VERTEX:
    try:
        import google.generativeai as genai
        if _gemini_key:
            genai.configure(api_key=_gemini_key)
        # GEMINI_MODEL accepts either bare ID or "models/<id>" form.
        _gemini_model_env = os.getenv("GEMINI_MODEL", "gemini-2.5-pro")
        _GEMINI_MODEL_NAME = (
            _gemini_model_env if _gemini_model_env.startswith("models/")
            else f"models/{_gemini_model_env}"
        )
    except ImportError:
        genai = None

# ── Prompt (shared across both backends) ─────────────────────────────────────
#
# Schema philosophy (v2.1 — updated 2026-05-15)
# ---------------------------------------------
# Gemini does "eyes only" — reports what's visible, no inferences.
# Heavy lifting (model name, colorway, MSRP, release date) is delegated to
# KicksDB via the SKU. Location is resolved before this call (Stage 2 anchor
# scan or Stage 0 GPS), so Gemini doesn't extract loc_code anymore — only
# brand/logo evidence that downstream Stage 9 cross-check can verify against
# the anchor's brand_environment.
#
# Output: a flat JSON with the v2.1 schema keys defined in _parse_response.
#
_ANALYSIS_PROMPT = """
Watch this short video clip carefully — both video and audio. You are
reporting EYES-ONLY observations, not inferences. Return ONLY a JSON
object (no markdown fences, no commentary) with exactly these fields:

CLASSIFICATION
  shoe_visible    — true if at least one shoe (on foot, on shelf, in hand,
                    or in a box) is visible in the clip; false otherwise.
  venue_visible   — true if any store signage, brand wall, shelf wall,
                    or store-environment context is visible.

PRODUCT (only populated when shoe_visible = true)
  sku_visible     — style code printed on box label / hang tag, e.g.
                    "555088-101", "DZ5485-612". Read each character
                    carefully — "I" vs "1" matters. Empty string if no
                    code is visible anywhere in the clip.
  product_hint    — free-text description of the shoe IF clearly visible
                    (e.g. "Air Jordan 1 Retro High OG"). Empty if unsure.
                    Do NOT guess from logo alone.
  colorway_dominant — primary visible color or colorway shorthand, white
                      listed first when present (e.g. "White/Black-Red").
                      Empty if no clear colorway is in frame.

BRAND (any visible brand evidence — used by Stage 9 conflict check)
  visible_brands  — list of brand marks visible on shoes, boxes, signs,
                    or apparel in the clip. Examples: ["Nike", "Jordan",
                    "Adidas", "Converse", "New Balance"]. Empty list if
                    no brand mark is visible.

VENUE (only when venue_visible = true; helps Stage 9 verify anchor)
  visible_signage — list of any store-name text on visible signage
                    (e.g. ["Nike Factory Store", "Footlocker", "Clearance"]).
                    Empty list if no readable signage.
  shelf_layout    — ONE of: "top-loading", "multi-rack", "wall-display",
                    "hash_wall", "unknown".
                    top-loading  = shoe-on-box-on-shelf (mall stores)
                    multi-rack   = open racks of mixed inventory (clearance)
                    wall-display = featured shoes mounted on walls
                    hash_wall    = colored-sticker discount wall
                    unknown      = layout not visible / ambiguous
  brand_environment — ONE of: "Nike-only", "Multi-brand", "Adidas-focused",
                      "Unknown".

PRICING (any visible pricing evidence)
  price_retail    — MSRP visible on hang tag / shelf label (e.g. "$190"). "" if none.
  price_observed  — current selling price on tag / sticker (e.g. "$59"). "" if none.
  price_audio     — any price mentioned verbally in audio (transcribe exactly). "" if silent.
  price_type      — "retail" | "outlet" | "sale" | "hash_wall" | "unknown" | ""
  is_hash_wall    — true only when colored sticker dots or a discount wall
                    are explicitly visible.

EVENTS
  drop_events     — list of moments where a shoe box is revealed, opened,
                    unboxed, or a shoe is dropped on camera. Each item:
                      timestamp_sec — float, seconds offset
                      confidence    — 0.0–1.0
                      sku           — style code if visible, else ""
                      notes         — short phrase
                    Empty list if none.

Rules:
- Report only what is visibly or audibly present. No inferences.
- If a field cannot be determined, use "" (empty string) for text fields,
  [] for lists, false for booleans, "unknown" for the enum fields where
  noted.
- Do NOT invent SKUs. A misread digit breaks the KicksDB lookup.

Example:
{
  "shoe_visible": true,
  "venue_visible": false,
  "sku_visible": "DZ4549-400",
  "product_hint": "",
  "colorway_dominant": "White/Black-Red",
  "visible_brands": ["Nike"],
  "visible_signage": [],
  "shelf_layout": "unknown",
  "brand_environment": "Unknown",
  "price_retail": "$190",
  "price_observed": "$59",
  "price_audio": "$59",
  "price_type": "hash_wall",
  "is_hash_wall": true,
  "drop_events": []
}
"""

# ── Retry helper ──────────────────────────────────────────────────────────────
def _retry(fn, attempts=3, delay=5):
    """Run fn() up to `attempts` times, backing off on failure."""
    last_err = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:
            last_err = e
            if i < attempts - 1:
                wait = delay * (2 ** i)
                print(f"  [retry] attempt {i+1} failed: {e} — retrying in {wait}s")
                time.sleep(wait)
    raise last_err


# ── Core analysis ─────────────────────────────────────────────────────────────

def analyze_sneaker_video(proxy_path, original_file=None, original_path=None):
    """
    Upload proxy_path to Vertex AI / Gemini API, extract shoe metadata,
    and return a structured dict ready to be written to JSON.

    Args:
        proxy_path     : absolute path to the low-bitrate proxy .mp4
        original_file  : renamed source filename (relational key).
                         If omitted, derived from proxy_path basename.
        original_path  : absolute path to the hi-res master (optional).

    Returns:
        dict with keys: original_file, original_path, proxy_file,
                        analysed_at, proxy_deleted, Model, SKU, Size, Price
        On error: {"error": str, "original_file": ..., "proxy_file": ...}
    """
    if original_file is None:
        original_file = os.path.basename(proxy_path)

    base_result = {
        "schema_version": 2.1,
        "original_file":  original_file,
        "original_path":  original_path or "",
        "proxy_file":     os.path.basename(proxy_path),
        "analysed_at":    None,
        "proxy_deleted":  False,    # pipeline sets this True after cleanup_proxies()
    }

    if _USE_VERTEX:
        return _analyze_vertex(proxy_path, base_result)
    elif genai is not None and _gemini_key:
        return _analyze_gemini(proxy_path, base_result)
    else:
        err = ("Neither VERTEX_PROJECT_ID (Vertex AI) nor GEMINI_API_KEY "
               "(Gemini API) is configured. Set one in .env.")
        print(f"[gemini] ERROR — {err}")
        return {**base_result, "error": err}


def _analyze_vertex(proxy_path, base_result):
    """Vertex AI backend."""
    try:
        from vertexai.generative_models import GenerativeModel, Part
        import vertexai.generative_models as gm

        print(f"  [vertex] Uploading proxy: {os.path.basename(proxy_path)}")

        with open(proxy_path, "rb") as f:
            video_bytes = f.read()

        video_part = Part.from_data(data=video_bytes, mime_type="video/mp4")

        def _call():
            model    = GenerativeModel(_VERTEX_MODEL_NAME)
            response = model.generate_content(
                [video_part, _ANALYSIS_PROMPT],
                generation_config={"response_mime_type": "application/json"},
            )
            return response.text

        raw = _retry(_call)
        parsed = _parse_response(raw)
        return {**base_result, **parsed,
                "analysed_at": _utcnow(), "proxy_deleted": False}

    except Exception as e:
        print(f"  [vertex] ERROR — {e}")
        return {**base_result, "error": str(e)}


def _analyze_gemini(proxy_path, base_result):
    """Gemini API (google.generativeai) backend — current Phase 1/2."""
    try:
        print(f"  [gemini] Uploading proxy: {os.path.basename(proxy_path)}")

        def _upload():
            vf = genai.upload_file(path=proxy_path)
            for _ in range(60):
                if vf.state.name == "ACTIVE":
                    break
                if vf.state.name == "FAILED":
                    raise ValueError(f"Gemini file processing failed: {proxy_path}")
                time.sleep(2)
                vf = genai.get_file(vf.name)
            return vf

        video_file = _retry(_upload)

        def _infer():
            model    = genai.GenerativeModel(_GEMINI_MODEL_NAME)
            response = model.generate_content(
                [video_file, _ANALYSIS_PROMPT],
                request_options={"timeout": 90},
            )
            return response.text

        raw    = _retry(_infer)
        parsed = _parse_response(raw)

        # Clean up the uploaded file from Gemini storage
        try:
            genai.delete_file(video_file.name)
        except Exception:
            pass   # non-fatal

        return {**base_result, **parsed,
                "analysed_at": _utcnow(), "proxy_deleted": False}

    except Exception as e:
        print(f"  [gemini] ERROR — {e}")
        return {**base_result, "error": str(e)}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_drop_events(raw):
    """Validate and normalise the Drop_Events array from Gemini output."""
    if not isinstance(raw, list):
        return []
    out = []
    for e in raw:
        if not isinstance(e, dict):
            continue
        ts = e.get("timestamp_sec")
        if ts is None:
            continue
        try:
            ts = float(ts)
        except (TypeError, ValueError):
            continue
        conf = e.get("confidence")
        try:
            conf = round(float(conf), 3) if conf is not None else None
        except (TypeError, ValueError):
            conf = None
        out.append({
            "timestamp_sec": ts,
            "confidence":    conf,
            "sku":           str(e.get("sku")   or "").strip(),
            "notes":         str(e.get("notes") or "").strip(),
        })
    return out


def _parse_response(raw_text):
    """
    Strip markdown fences and parse the model response into the
    SACC v2.1 flat schema.

    Schema v2.1 keys (set here — pipeline adds loc_code_anchor /
    conflict_detected / needs_review / schema_version):

      shoe_visible        bool
      venue_visible       bool
      sku_visible         str   — style code (relational key for KicksDB)
      product_hint        str   — free-text shoe description if confidently visible
      colorway_dominant   str   — primary colorway shorthand (white-first)
      visible_brands      list  — brand marks seen (Stage 9 conflict input)
      visible_signage     list  — store-name text from signage
      shelf_layout        str   — top-loading | multi-rack | wall-display | hash_wall | unknown
      brand_environment   str   — Nike-only | Multi-brand | Adidas-focused | Unknown
      price_retail        str   — MSRP if visible
      price_observed      str   — current selling price
      price_audio         str   — price spoken in audio
      price_type          str   — retail | outlet | sale | hash_wall | unknown | ""
      is_hash_wall        bool
      drop_events         list  — {timestamp_sec, confidence, sku, notes}

    Accepts both v2.1 snake_case keys AND v1 PascalCase keys from older
    Gemini responses (legacy compat — keeps the 138 already-analysed
    JSONs reprocessable through this parser if needed).
    """
    import re as _re
    cleaned = _re.sub(r"^```(?:json)?\s*", "", raw_text.strip())
    cleaned = _re.sub(r"```\s*$", "", cleaned).strip()
    data    = json.loads(cleaned)

    def _str(v):
        return str(v).strip() if v not in (None, "", "null") else ""
    def _bool(v):
        if isinstance(v, bool): return v
        if isinstance(v, str):  return v.strip().lower() in ("true", "1", "yes")
        return bool(v)
    def _list(v):
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
        return []
    def _enum(v, allowed, default):
        s = _str(v).lower().replace(" ", "_").replace("-", "_")
        # Normalize known variants — Gemini sometimes drops hyphens or uses spaces
        alias = {
            "top_loading":   "top-loading",
            "multi_rack":    "multi-rack",
            "wall_display":  "wall-display",
            "hash_wall":     "hash_wall",
            "nike_only":     "Nike-only",
            "multi_brand":   "Multi-brand",
            "adidas_focused":"Adidas-focused",
            "unknown":       "unknown",
        }
        canon = alias.get(s, _str(v))
        return canon if canon in allowed else default

    return {
        # Classification
        "shoe_visible":      _bool(data.get("shoe_visible")  or data.get("Shoe_Visible")),
        "venue_visible":     _bool(data.get("venue_visible") or data.get("Venue_Visible")),

        # Product
        "sku_visible":       _str(data.get("sku_visible") or data.get("SKU") or data.get("sku")),
        "product_hint":      _str(data.get("product_hint") or data.get("Product_Hint")),
        "colorway_dominant": _str(data.get("colorway_dominant") or data.get("Colorway_Dominant")),

        # Brand evidence (input to Stage 9 conflict check)
        "visible_brands":    _list(data.get("visible_brands") or data.get("brand_logos")),

        # Venue evidence
        "visible_signage":   _list(data.get("visible_signage") or data.get("store_signage")),
        "shelf_layout":      _enum(
            data.get("shelf_layout"),
            {"top-loading","multi-rack","wall-display","hash_wall","unknown"},
            "unknown",
        ),
        "brand_environment": _enum(
            data.get("brand_environment"),
            {"Nike-only","Multi-brand","Adidas-focused","Unknown"},
            "Unknown",
        ),

        # Pricing
        "price_retail":      _str(data.get("price_retail")   or data.get("Price_Retail")),
        "price_observed":    _str(data.get("price_observed") or data.get("Price_Observed") or data.get("Price")),
        "price_audio":       _str(data.get("price_audio")    or data.get("Price_Audio")),
        "price_type":        _str(data.get("price_type")     or data.get("Price_Type")),
        "is_hash_wall":      _bool(data.get("is_hash_wall")  or data.get("Is_Hash_Wall")),

        # Events
        "drop_events":       _parse_drop_events(data.get("drop_events") or data.get("Drop_Events")),
    }


def _utcnow():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


# ── Logic Router ─────────────────────────────────────────────────────────────
#
#  route_analysis() is the single entry point for Stage 8.
#  It inspects the file count and dispatches to the correct backend:
#
#    n < BATCH_THRESHOLD  →  _standard_batch()   immediate, per-file
#    n >= BATCH_THRESHOLD →  _vertex_batch()      async JSONL, 50% cheaper
#
#  Both paths return the same list-of-dicts format so stage_vertex() in
#  sacc_pipeline.py doesn't need to know which path ran.
#
#  original_map: { proxy_path: (original_file, original_path) }
#

def route_analysis(proxy_files: list, original_map: dict) -> list:
    """
    Dispatch proxy files to standard or batch Vertex AI analysis.

    Args:
        proxy_files  : list of absolute paths to proxy .mp4 files
        original_map : { proxy_path: (original_file, original_path) }

    Returns:
        list of result dicts — same schema as analyze_sneaker_video()
    """
    n = len(proxy_files)
    if n == 0:
        return []

    can_batch = bool(_GCS_BUCKET and _vertex_project)

    if n < BATCH_THRESHOLD or not can_batch:
        reason = f"n={n} < threshold={BATCH_THRESHOLD}" if n < BATCH_THRESHOLD \
                 else "GCS_BUCKET or VERTEX_PROJECT_ID not set"
        print(f"\n[router] {n} file(s) → Standard API  ({reason})")
        return _standard_batch(proxy_files, original_map)
    else:
        print(f"\n[router] {n} file(s) → Vertex AI Batch Prediction"
              f"  (threshold={BATCH_THRESHOLD}, ~50% cost saving)")
        try:
            return _vertex_batch(proxy_files, original_map)
        except Exception as e:
            print(f"[router] Batch job failed: {e}")
            print("[router] Falling back to Standard API")
            return _standard_batch(proxy_files, original_map)


# ── Standard path ─────────────────────────────────────────────────────────────

def _standard_batch(proxy_files: list, original_map: dict) -> list:
    """
    Stage 5 — Async Parallel Upload via thread pool.

    Concurrency = GEMINI_PARALLEL (env, default 3). Output preserves input
    order so downstream index-based lookups stay valid.

    Threading instead of asyncio: the google.generativeai / vertexai
    clients are sync; threading lets us parallelise without rewriting
    analyze_sneaker_video. Calls are network-I/O-bound so the GIL is
    released during waits.
    """
    n = len(proxy_files)
    if n == 0:
        return []
    workers = min(GEMINI_PARALLEL, n)
    if workers == 1:
        # Skip the pool overhead for tiny batches / forced-sequential mode
        results = []
        for i, p in enumerate(proxy_files, 1):
            orig_file, orig_path = original_map.get(p, (None, None))
            print(f"  [{i}/{n}] {Path(p).name}")
            results.append(analyze_sneaker_video(p, orig_file, orig_path))
        return results

    print(f"  [parallel] {workers} workers, {n} clip(s)")
    results: list = [None] * n   # type: ignore[list-item]
    completed = 0

    def _job(idx_path):
        i, p = idx_path
        orig_file, orig_path = original_map.get(p, (None, None))
        return i, analyze_sneaker_video(p, orig_file, orig_path)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(_job, (i, p)): (i, p)
                   for i, p in enumerate(proxy_files)}
        for fut in as_completed(futures):
            i, p = futures[fut]
            completed += 1
            try:
                idx, result = fut.result()
                results[idx] = result
                tag = "ERR" if result.get("error") else "OK"
            except Exception as e:
                results[i] = {"error": str(e), "proxy_file": Path(p).name}
                tag = "ERR"
            print(f"  [{completed}/{n}] {tag}  {Path(p).name}")
    return results


# ── Batch Prediction path ─────────────────────────────────────────────────────

def _vertex_batch(proxy_files: list, original_map: dict) -> list:
    """
    Vertex AI Batch Prediction:
      1. Upload proxies to GCS
      2. Write JSONL requests file to GCS
      3. Submit BatchPredictionJob (async)
      4. Poll until terminal state
      5. Parse output JSONL from GCS
      6. Return results list
    """
    try:
        from google.cloud import storage as gcs_lib
        import google.cloud.aiplatform as aip
    except ImportError as e:
        raise RuntimeError(
            f"Batch mode requires google-cloud-storage and google-cloud-aiplatform: {e}\n"
            "  pip install google-cloud-storage google-cloud-aiplatform"
        )

    job_id  = f"sacc-{int(time.time())}"
    prefix  = f"sacc-batch/{job_id}"
    bucket_name = _GCS_BUCKET

    gcs_client = gcs_lib.Client(project=_vertex_project)
    bucket     = gcs_client.bucket(bucket_name)

    # ── Step 1: Upload proxies to GCS ────────────────────────────────────────
    print(f"[batch] Uploading {len(proxy_files)} proxies → gs://{bucket_name}/{prefix}/input/")
    gcs_uris = {}
    for proxy_path in proxy_files:
        blob_name = f"{prefix}/input/{Path(proxy_path).name}"
        blob = bucket.blob(blob_name)
        blob.upload_from_filename(str(proxy_path), content_type="video/mp4")
        gcs_uris[proxy_path] = f"gs://{bucket_name}/{blob_name}"
        print(f"  ↑ {Path(proxy_path).name}")

    # ── Step 2: Build JSONL ───────────────────────────────────────────────────
    lines = []
    for proxy_path in proxy_files:
        lines.append(json.dumps({
            "request": {
                "contents": [{
                    "role": "user",
                    "parts": [
                        {"fileData": {
                            "mimeType": "video/mp4",
                            "fileUri":  gcs_uris[proxy_path],
                        }},
                        {"text": _ANALYSIS_PROMPT},
                    ],
                }],
                "generationConfig": {"responseMimeType": "application/json"},
            }
        }))

    jsonl_blob = f"{prefix}/requests.jsonl"
    bucket.blob(jsonl_blob).upload_from_string(
        "\n".join(lines), content_type="application/jsonl"
    )
    input_uri  = f"gs://{bucket_name}/{jsonl_blob}"
    output_uri = f"gs://{bucket_name}/{prefix}/output/"
    print(f"[batch] JSONL ready → {input_uri}  ({len(lines)} requests)")

    # ── Step 3: Submit job ────────────────────────────────────────────────────
    model_name = (f"projects/{_vertex_project}/locations/{_vertex_location}"
                  f"/publishers/google/models/"
                  f"{os.getenv('VERTEX_MODEL', 'gemini-2.5-pro')}")

    aip.init(project=_vertex_project, location=_vertex_location)
    job = aip.BatchPredictionJob.create(
        job_display_name = job_id,
        model_name       = model_name,
        instances_format = "jsonl",
        predictions_format = "jsonl",
        gcs_source       = [input_uri],
        gcs_destination_prefix = output_uri,
        sync             = False,
    )
    print(f"[batch] Job submitted → {job.name}")

    # ── Step 4: Poll ──────────────────────────────────────────────────────────
    _TERMINAL = {"JOB_STATE_SUCCEEDED", "JOB_STATE_FAILED",
                 "JOB_STATE_CANCELLED", "JOB_STATE_EXPIRED"}
    max_wait, poll_interval, elapsed = 7200, 60, 0
    while elapsed < max_wait:
        job.refresh()
        state = job.state.name
        pct   = getattr(job, "completion_stats", None)
        print(f"  [batch] {state}  elapsed={elapsed}s"
              + (f"  {pct}" if pct else ""))
        if state in _TERMINAL:
            break
        time.sleep(poll_interval)
        elapsed += poll_interval

    if job.state.name != "JOB_STATE_SUCCEEDED":
        raise RuntimeError(f"Batch job ended with state: {job.state.name}")

    print(f"[batch] Job complete — parsing results from {output_uri}")

    # ── Step 5: Parse output JSONL ────────────────────────────────────────────
    blobs = list(gcs_client.list_blobs(bucket_name, prefix=f"{prefix}/output/"))
    raw_lines = []
    for blob in blobs:
        if blob.name.endswith((".jsonl", ".json")):
            raw_lines.extend(
                [l for l in blob.download_as_text().splitlines() if l.strip()]
            )

    results = []
    for i, line in enumerate(raw_lines):
        proxy_path = proxy_files[i] if i < len(proxy_files) else None
        orig_file, orig_path = original_map.get(proxy_path, (None, None))
        base = {
            "original_file": orig_file or (Path(proxy_path).name if proxy_path else ""),
            "original_path": orig_path or "",
            "proxy_file":    Path(proxy_path).name if proxy_path else "",
            "analysed_at":   _utcnow(),
            "proxy_deleted": False,
        }
        try:
            obj  = json.loads(line)
            # Vertex batch output: {"request":{...}, "response":{"candidates":[...]}}
            text = (obj.get("response", {})
                       .get("candidates", [{}])[0]
                       .get("content", {})
                       .get("parts", [{}])[0]
                       .get("text", ""))
            results.append({**base, **_parse_response(text)})
        except Exception as e:
            results.append({**base, "error": str(e)})

    print(f"[batch] {len(results)} result(s) parsed")
    return results


# ── CLI test ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    can_batch = bool(_GCS_BUCKET and _vertex_project)
    print("[gemini] Pipeline initialised.")
    print(f"  Backend        : {'Vertex AI' if _USE_VERTEX else 'Gemini API'}")
    print(f"  Vertex project : {_vertex_project or '(not set)'}")
    print(f"  Gemini key     : {'set' if _gemini_key else '(not set)'}")
    print(f"  GCS bucket     : {_GCS_BUCKET or '(not set — batch mode disabled)'}")
    print(f"  Batch threshold: {BATCH_THRESHOLD} files")
    print(f"  Batch mode     : {'ENABLED' if can_batch else 'DISABLED (set GCS_BUCKET + VERTEX_PROJECT_ID)'}")
    print()
    print("  Router logic:")
    print(f"    n < {BATCH_THRESHOLD}  → Standard API  (immediate)")
    print(f"    n >= {BATCH_THRESHOLD} → Vertex AI Batch Prediction  (~50% cheaper)")
