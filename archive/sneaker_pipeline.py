#!/usr/bin/env python3
import os, json, time, csv, re, urllib.request, urllib.error, uuid
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────────
#  CONFIG (VERSION 16 - PAID TIER / ROBUST)
# ─────────────────────────────────────────────
GEMINI_UPLOADS_DIR = Path("/Volumes/Team Bank 12/Sneeaker Solo/Sneaker Solo GEMINI UPLOADS")
OUTPUT_DIR         = Path("/Volumes/Team Bank 12/Sneeaker Solo")

DATABASE_FILE = OUTPUT_DIR / "sneaker_database.json"
MANIFEST_FILE = OUTPUT_DIR / "rename_manifest.csv"

API_BASE    = "https://generativelanguage.googleapis.com/v1beta"
UPLOAD_BASE = "https://generativelanguage.googleapis.com/upload/v1beta/files"

MANIFEST_COLUMNS = [
    "original_file_id", "brand", "silhouette", "colorway_name",
    "style_code", "retail_price", "release_date",
    "new_filename", "folder_path", "verification_status"
]

PROMPT = """You are a professional sneaker authenticator. Identify the sneaker in this video.
Return ONLY a valid JSON object.

JSON keys:
- "brand": e.g., "Nike", "Jordan Brand", "Adidas", "New Balance".
- "silhouette": The full model and edition name (e.g., "Air Jordan 1 High OG", "Dunk Low SB", "New Balance 990v6").
- "colorway_name": The specific nickname or colorway (e.g., "Chicago", "Lost & Found", "Mocha"). Use null if none.
- "style_code": The SKU (e.g., "555088-001"). Use null if unknown.
- "retail_price": Number only. Use null if unknown.
- "release_date": 4-digit year string. Use null if unknown.

Return ONLY JSON. No markdown formatting."""

# ─────────────────────────────────────────────
#  CUSTOM EXCEPTIONS
# ─────────────────────────────────────────────
class QuotaExhausted(Exception):
    """Hard stop — daily or billing quota hit. Don't mark files as FAILED."""
    pass

# ─────────────────────────────────────────────
#  UTILITIES
# ─────────────────────────────────────────────
def to_camel_case(s):
    if not s or str(s).lower() in ("null", "none", "unknown"): return ""
    s = re.sub(r'[^a-zA-Z0-9\s]', '', str(s))
    return "".join(word.capitalize() for word in s.split())

def safe_name(s):
    return re.sub(r'[<>:"/\\|?*]', '', str(s).strip()).strip(" .") or "Unknown"

def http_get(url):
    with urllib.request.urlopen(url) as resp:
        return json.loads(resp.read().decode())

def http_post(url, data, headers):
    req = urllib.request.Request(url, data=data, method="POST")
    for k, v in headers.items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode())

def read_http_error(e):
    """Read the response body from an HTTPError for diagnosis."""
    try:
        return e.read().decode("utf-8", errors="replace")
    except Exception:
        return "(could not read error body)"

# ─────────────────────────────────────────────
#  UPLOAD
# ─────────────────────────────────────────────
def upload_multipart(api_key, path):
    print(f"  [1/3] Uploading: {path.name}...")
    with open(path, "rb") as f:
        video_data = f.read()

    boundary = f"----{uuid.uuid4().hex}"
    metadata = json.dumps({"file": {"displayName": path.name}})
    parts = [
        f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{metadata}\r\n".encode(),
        f"--{boundary}\r\nContent-Type: video/mp4\r\n\r\n".encode(),
        video_data,
        f"\r\n--{boundary}--\r\n".encode()
    ]
    body = b"".join(parts)

    url = f"{UPLOAD_BASE}?uploadType=multipart&key={api_key}"
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", f"multipart/related; boundary={boundary}")

    try:
        with urllib.request.urlopen(req) as resp:
            info = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body_text = read_http_error(e)
        # 403 almost always means API key / billing issue — print full detail
        if e.code == 403:
            print(f"\n  ⛔  403 FORBIDDEN on upload. Google says:")
            print(f"  {body_text[:600]}")
            print(f"\n  Common causes:")
            print(f"    1. Your .env still has the OLD free-tier API key — paste in the new paid-tier key")
            print(f"    2. The 'Generative Language API' is not enabled in your Google Cloud project")
            print(f"       → Visit: https://console.cloud.google.com/apis/library/generativelanguage.googleapis.com")
            print(f"    3. Billing was just enabled — wait 5 minutes and retry\n")
            raise Exception(f"HTTP 403 — see diagnosis above")
        raise Exception(f"Upload HTTP {e.code}: {body_text[:300]}")

    short_id = info["file"]["name"].split("/")[-1]
    print(f"  [2/3] File ID: {short_id} — waiting for ACTIVE...")

    # Poll for ACTIVE state
    for _ in range(60):  # max 5 minutes
        status = http_get(f"{API_BASE}/files/{short_id}?key={api_key}")
        state = status.get("state")
        if state == "ACTIVE":
            print(f"        ACTIVE ✓")
            break
        elif state == "FAILED":
            raise Exception("Google failed to process video file.")
        time.sleep(5)
    else:
        raise Exception("Timed out waiting for ACTIVE state.")

    return info["file"]["uri"], short_id

# ─────────────────────────────────────────────
#  NORMALIZE
# ─────────────────────────────────────────────
def normalize_response(raw, file_id):
    brand      = raw.get("brand")        or "Unknown"
    silhouette = raw.get("silhouette")   or "Unknown"
    colorway   = raw.get("colorway_name") or ""

    cc_brand      = to_camel_case(brand)
    cc_silhouette = to_camel_case(silhouette)
    cc_colorway   = to_camel_case(colorway)

    folder_path = f"{safe_name(brand)}/{safe_name(silhouette)}"
    # Filename uses silhouette only — brand is redundant when silhouette already contains it
    # e.g. "AirJordan1RetroHighOG_Bred.mp4" not "JordanBrandAirJordan1RetroHighOG_Bred.mp4"
    fn_base = cc_silhouette
    if cc_colorway:
        fn_base += f"_{cc_colorway}"

    return {
        "original_file_id":   file_id,
        "brand":              brand,
        "silhouette":         silhouette,
        "colorway_name":      colorway,
        "style_code":         str(raw.get("style_code") or ""),
        "retail_price":       str(raw.get("retail_price") or ""),
        "release_date":       str(raw.get("release_date") or ""),
        "new_filename":       f"{fn_base}.mp4",
        "folder_path":        folder_path,
        "verification_status": "VERIFIED",
    }

# ─────────────────────────────────────────────
#  GEMINI CALL
# ─────────────────────────────────────────────
def call_gemini(api_key, file_uri, file_id):
    url = f"{API_BASE}/models/gemini-2.5-flash:generateContent?key={api_key}"
    payload = {
        "contents": [{"parts": [
            {"fileData": {"mimeType": "video/mp4", "fileUri": file_uri}},
            {"text": PROMPT}
        ]}],
        "generationConfig": {"response_mime_type": "application/json"}
    }

    for attempt in range(3):
        try:
            raw = http_post(url, json.dumps(payload).encode(), {"Content-Type": "application/json"})
            text = raw["candidates"][0]["content"]["parts"][0]["text"].strip()
            return normalize_response(json.loads(text), file_id)

        except urllib.error.HTTPError as e:
            body_text = read_http_error(e)
            print(f"        AI HTTP {e.code}: {body_text[:300]}")

            if e.code == 429:
                # Check for daily/billing quota exhaustion
                if any(k in body_text for k in ("requests_per_day", "free_tier_requests", "billing", "quota")):
                    print("\n  ⛔  QUOTA EXHAUSTED — stopping pipeline cleanly.")
                    print("  No files are lost. Re-run to continue from where this stopped.")
                    raise QuotaExhausted("Quota exhausted")
                # Per-minute RPM — wait and retry
                if attempt < 2:
                    wait = 60 * (attempt + 1)
                    print(f"        RPM limit — waiting {wait}s then retrying ({attempt+1}/3)...")
                    time.sleep(wait)
                    continue

            elif e.code == 503 and attempt < 2:
                wait = 30 * (attempt + 1)
                print(f"        Service overload — waiting {wait}s ({attempt+1}/3)...")
                time.sleep(wait)
                continue

            raise Exception(f"AI HTTP {e.code}: {body_text[:200]}")

        except QuotaExhausted:
            raise

        except Exception as e:
            if attempt < 2:
                print(f"        Error ({attempt+1}/3): {e} — retrying in 15s...")
                time.sleep(15)
                continue
            raise

# ─────────────────────────────────────────────
#  WRITE CSV
# ─────────────────────────────────────────────
def write_csv(db):
    with open(MANIFEST_FILE, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=MANIFEST_COLUMNS)
        writer.writeheader()
        for k in sorted(db.keys()):
            writer.writerow({c: db[k].get(c, "") for c in MANIFEST_COLUMNS})

# ─────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────
def main():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("ERROR: GEMINI_API_KEY not found in .env")
        return

    print("\n" + "="*52 + "\n  SNEAKER PIPELINE V16 - PAID TIER / ROBUST\n" + "="*52)

    # Load DB
    db = {}
    if DATABASE_FILE.exists():
        try:
            with open(DATABASE_FILE) as f:
                db = json.load(f)
        except Exception as e:
            print(f"WARNING: Could not load database — {e}")

    videos = sorted(GEMINI_UPLOADS_DIR.glob("*.mp4"))

    # Count status
    done    = sum(1 for v in videos if db.get(v.name.split("-")[0].strip(), {}).get("verification_status") == "VERIFIED")
    pending = len(videos) - done
    print(f"  {len(videos)} total | {done} already verified | {pending} to process\n")

    processed = 0
    for i, v_path in enumerate(videos, 1):
        file_id = v_path.name.split("-")[0].strip()

        # Skip anything already VERIFIED
        if db.get(file_id, {}).get("verification_status") == "VERIFIED":
            continue

        print(f"[{i}/{len(videos)}] {v_path.name}")

        sid = None
        try:
            uri, sid = upload_multipart(api_key, v_path)
            print(f"  [3/3] AI identifying...")
            info = call_gemini(api_key, uri, file_id)

            db[file_id] = {**info, "timestamp": datetime.now().isoformat()}
            with open(DATABASE_FILE, "w") as f:
                json.dump(db, f, indent=2)
            write_csv(db)

            print(f"  ✓ {info['silhouette']} — {info['colorway_name'] or info['style_code'] or '—'}\n")
            processed += 1

        except QuotaExhausted:
            print(f"\n[STOPPED] Quota hit at [{i}/{len(videos)}]. {processed} processed this session.")
            print("[STOPPED] Re-run to continue — completed files will be skipped.\n")
            break

        except Exception as e:
            print(f"  × FAILED: {e}\n")
            db[file_id] = {
                "original_file_id":   file_id,
                "verification_status": "FAILED",
                "notes":              str(e),
                "timestamp":          datetime.now().isoformat()
            }
            with open(DATABASE_FILE, "w") as f:
                json.dump(db, f, indent=2)

        finally:
            # Always clean up the uploaded file
            if sid:
                try:
                    urllib.request.urlopen(
                        urllib.request.Request(f"{API_BASE}/files/{sid}?key={api_key}", method="DELETE")
                    )
                except:
                    pass

        # Paid tier pacing — 8s between files (~6 files/min, well under RPM ceiling)
        time.sleep(8)

    print(f"\n{'='*52}")
    verified = sum(1 for v in db.values() if v.get("verification_status") == "VERIFIED")
    failed   = sum(1 for v in db.values() if v.get("verification_status") == "FAILED")
    print(f"  Session done. {processed} processed this run.")
    print(f"  Total verified: {verified} | Failed/pending: {failed}")
    print(f"{'='*52}\n")

if __name__ == "__main__":
    main()
