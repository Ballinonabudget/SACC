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
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

# ── Client selection: Vertex AI (preferred) or Gemini API fallback ────────────
_vertex_project  = os.getenv("VERTEX_PROJECT_ID")
_vertex_location = os.getenv("VERTEX_LOCATION", "us-central1")
_gemini_key      = os.getenv("GEMINI_API_KEY")

_USE_VERTEX  = bool(_vertex_project)
_GCS_BUCKET  = os.getenv("GCS_BUCKET", "")
BATCH_THRESHOLD = int(os.getenv("BATCH_THRESHOLD", "50"))

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
        _GEMINI_MODEL_NAME = "models/gemini-2.5-pro"
    except ImportError:
        genai = None

# ── Prompt (shared across both backends) ─────────────────────────────────────
#
# Location detection methodology (updated 2026-04-23)
# ----------------------------------------------------
# GPS-based geofencing was rescinded due to coordinate inaccuracy.
# [Custom Name] / location is now determined here, at Stage 8, by asking
# the model to read visual signage and listen to the audio transcript.
#
# Visual signals to read:
#   - Store entrance / exterior signage (Nike, Foot Locker, etc.)
#   - Mall directory boards, wayfinding signs, pylon signs
#   - Shopping bags carried by staff or customers
#   - Employee uniforms, lanyards, name badges
#   - Storefront banners, window graphics, brand logos
#
# Audio signals to transcribe:
#   - Staff announcing the store name on camera
#   - PA system announcements naming the mall or store
#   - Customer / operator verbal references to location
#
# The model maps its observation to one of the SACC location codes below.
# If no match is possible, it returns null and sets confidence = "low".
#
_LOCATION_HINT = """\
Known SACC location codes (Florida retail network):
  FLM=Florida Mall, MAM=Mall at Millenia, OFS=Orlando Fashion Square,
  WOM=West Oaks Mall, VLD=Vineland Premium Outlets, IDR=International Drive,
  LBV=Lake Buena Vista, WFL=Waterford Lakes, WGN=Winter Garden Village,
  OMP=Orlando Marketplace, SEM=Seminole Towne Center, LKL=Lakeland Square Mall,
  PDM=Paddock Mall (Ocala), THL=Tallahassee Mall, BRN=Brandon Exchange,
  INP=International Plaza (Tampa), UNM=University Mall (Tampa),
  TPA=Tampa Premium Outlets, HVP=Hyde Park Village (Tampa),
  AVE=Aventura Mall, LCN=Lincoln Road, DOL=Dolphin Mall,
  GVA=Gainesville Celebration Pointe, CEL-K=Celebration Kissimmee,
  KSM=Kissimmee Osceola Pkwy"""

_ANALYSIS_PROMPT = f"""
Watch this short video clip carefully — both video and audio.
Extract and return a strictly formatted JSON object with exactly these fields:

SNEAKER FIELDS
  Model    — full marketing name of the shoe (e.g. "Air Jordan 1 Retro High OG Chicago")
  SKU      — the style code / product code (e.g. "555088-101")
  Size     — visible size label if shown (e.g. "10.5"), otherwise null
  Price    — visible retail price if shown (e.g. "$180"), otherwise null

LOCATION FIELDS
  Location_Visual    — name of the store or retail location identified from
                       visible signage, storefronts, mall directories, banners,
                       uniforms, or shopping bags. Use the most specific name
                       visible (e.g. "Nike Factory Store Vineland Premium Outlets").
                       Return null if no signage is readable.
  Location_Audio     — store or location name mentioned verbally in the audio
                       (staff speech, PA announcements, operator narration).
                       Transcribe the exact phrase used.  Return null if silent
                       or location is not mentioned.
  Location_Code      — map your observation to one of these SACC codes:
{_LOCATION_HINT}
                       Return the best matching code (e.g. "VLD"), or null if
                       no confident match is possible.
  Location_Confidence — "high"   (clear, unambiguous signage or verbal confirmation)
                         "medium" (partial signage, indirect branding cues)
                         "low"    (inference only — no direct evidence)
                         null     (location completely unidentifiable)

Rules:
- Base all extractions purely on what is visible or audible in the video.
- Return ONLY the JSON object. No markdown fences, no commentary.
- If a field cannot be determined, use null.
- For Location_Code, prefer visual evidence over audio when they conflict.

Example:
{{
  "Model": "Air Jordan 1 Retro High OG Chicago",
  "SKU": "555088-101",
  "Size": "10.5",
  "Price": "$180",
  "Location_Visual": "Nike Factory Store at Vineland Premium Outlets",
  "Location_Audio": "we're here at Vineland",
  "Location_Code": "VLD",
  "Location_Confidence": "high"
}}
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
        "original_file": original_file,
        "original_path": original_path or "",
        "proxy_file":    os.path.basename(proxy_path),
        "analysed_at":   None,
        "proxy_deleted": False,     # pipeline sets this True after cleanup_proxies()
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
            model    = genai.GenerativeModel("models/gemini-2.5-pro")
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

def _parse_response(raw_text):
    """
    Strip markdown fences and parse JSON from the model response.

    Handles both sneaker fields and the location detection fields added
    when GPS geofencing was rescinded (2026-04-23).

    Location fields in returned dict:
      Location_Visual     — signage/storefront text read by the model
      Location_Audio      — verbally mentioned location from audio transcript
      loc_code_confirmed  — SACC location code if confidence is high/medium
                            (written as 'loc_code_confirmed' for pipeline use)
      Location_Confidence — "high" | "medium" | "low" | null
    """
    import re as _re
    cleaned = _re.sub(r"^```(?:json)?\s*", "", raw_text.strip())
    cleaned = _re.sub(r"```\s*$", "", cleaned).strip()
    data    = json.loads(cleaned)

    def _str(v):
        return str(v).strip() if v not in (None, "", "null") else ""

    loc_code  = _str(data.get("Location_Code") or data.get("location_code"))
    confidence = _str(data.get("Location_Confidence") or
                      data.get("location_confidence"))

    # Only promote to loc_code_confirmed when model is high or medium confidence
    confirmed = loc_code if confidence in ("high", "medium") else ""

    return {
        # Sneaker fields
        "Model": _str(data.get("Model") or data.get("model")),
        "SKU":   _str(data.get("SKU")   or data.get("sku")),
        "Size":  _str(data.get("Size")  or data.get("size")),
        "Price": _str(data.get("Price") or data.get("price")),
        # Location fields — from visual + audio analysis
        "Location_Visual":     _str(data.get("Location_Visual")     or
                                    data.get("location_visual")),
        "Location_Audio":      _str(data.get("Location_Audio")      or
                                    data.get("location_audio")),
        "Location_Confidence": confidence,
        "loc_code_confirmed":  confirmed,  # used by fcp_namer.apply_confirmed_locations()
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
    """Sequential per-file standard API calls."""
    results = []
    for i, proxy_path in enumerate(proxy_files, 1):
        orig_file, orig_path = original_map.get(proxy_path, (None, None))
        print(f"  [{i}/{len(proxy_files)}] {Path(proxy_path).name}")
        result = analyze_sneaker_video(proxy_path, orig_file, orig_path)
        results.append(result)
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
