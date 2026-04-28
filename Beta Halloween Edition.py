#!/usr/bin/env python3
import os, json, time, csv, re, urllib.request, urllib.error, uuid
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────────
#  CONFIG (DASHBOARD EDITION)
# ─────────────────────────────────────────────
BASE_DIR           = Path("/Volumes/Team Bank 12/Jordan 1 Halloween/API_Ready_Files")
GEMINI_UPLOADS_DIR = BASE_DIR
OUTPUT_DIR         = BASE_DIR

DATABASE_FILE = OUTPUT_DIR / "sneaker_database.json"
MANIFEST_FILE = OUTPUT_DIR / "rename_manifest.csv"

API_BASE    = "https://generativelanguage.googleapis.com/v1beta"
UPLOAD_BASE = "https://generativelanguage.googleapis.com/upload/v1beta/files"

# Added "notes" to track error messages in the CSV
MANIFEST_COLUMNS = [
    "original_file_id", "brand", "silhouette", "colorway_name",
    "style_code", "retail_price", "release_date",
    "new_filename", "folder_path", "verification_status", "notes"
]

PROMPT = """You are a professional sneaker authenticator. Identify the sneaker in this slow-motion video.
This is a studio shot of a single shoe. Focus on the shoe details and the box label if visible.
Return ONLY a valid JSON object.

JSON keys:
- "brand": e.g., "Jordan Brand", "Nike".
- "silhouette": The full model name (e.g., "Air Jordan 1 High OG").
- "colorway_name": The specific nickname (e.g., "Halloween").
- "style_code": The SKU from the box or inner tag.
- "retail_price": Number only.
- "release_date": 4-digit year string.

Return ONLY JSON. No markdown."""

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
    for k, v in headers.items(): req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode())

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
    with urllib.request.urlopen(req) as resp:
        info = json.loads(resp.read().decode())
    short_id = info["file"]["name"].split("/")[-1]
    print(f"  [2/3] File ID: {short_id} — waiting for ACTIVE...")
    for _ in range(60):
        status = http_get(f"{API_BASE}/files/{short_id}?key={api_key}")
        if status.get("state") == "ACTIVE":
            print(f"        ACTIVE ✓")
            break
        time.sleep(5)
    return info["file"]["uri"], short_id

def normalize_response(raw, file_id):
    brand, sil, col = raw.get("brand") or "Unknown", raw.get("silhouette") or "Unknown", raw.get("colorway_name") or ""
    cc_sil, cc_col = to_camel_case(sil), to_camel_case(col)
    fn_base = f"{cc_sil}_{cc_col}" if cc_col else cc_sil
    return {
        "original_file_id": file_id,
        "brand": brand, "silhouette": sil, "colorway_name": col,
        "style_code": str(raw.get("style_code") or ""),
        "retail_price": str(raw.get("retail_price") or ""),
        "release_date": str(raw.get("release_date") or ""),
        "new_filename": f"{fn_base}.mp4",
        "folder_path": f"{safe_name(brand)}/{safe_name(sil)}",
        "verification_status": "VERIFIED",
        "notes": ""
    }

def call_gemini(api_key, file_uri, file_id):
    url = f"{API_BASE}/models/gemini-2.5-flash:generateContent?key={api_key}"
    payload = {
        "contents": [{"parts": [
            {"fileData": {"mimeType": "video/mp4", "fileUri": file_uri}},
            {"text": PROMPT}
        ]}],
        "generationConfig": {"response_mime_type": "application/json"}
    }
    raw = http_post(url, json.dumps(payload).encode(), {"Content-Type": "application/json"})
    text = raw["candidates"][0]["content"]["parts"][0]["text"].strip()
    return normalize_response(json.loads(text), file_id)

def update_manifest(db):
    with open(MANIFEST_FILE, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=MANIFEST_COLUMNS)
        writer.writeheader()
        for k in sorted(db.keys()):
            writer.writerow({c: db[k].get(c, "") for c in MANIFEST_COLUMNS})

def main():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("ERROR: GEMINI_API_KEY not found in .env")
        return

    print("\n" + "="*52 + "\n  JORDAN 1 HALLOWEEN - DASHBOARD ACTIVE\n" + "="*52)

    db = {}
    if DATABASE_FILE.exists():
        with open(DATABASE_FILE) as f: db = json.load(f)

    videos = sorted(GEMINI_UPLOADS_DIR.glob("*.mp4"))
    
    for i, v_path in enumerate(videos, 1):
        file_id = v_path.stem
        if db.get(file_id, {}).get("verification_status") == "VERIFIED":
            continue

        print(f"[{i}/{len(videos)}] Processing: {v_path.name}")
        sid = None
        try:
            uri, sid = upload_multipart(api_key, v_path)
            info = call_gemini(api_key, uri, file_id)
            db[file_id] = {**info, "timestamp": datetime.now().isoformat()}
            print(f"  ✓ {info['silhouette']} — {info['colorway_name']}\n")

        except Exception as e:
            print(f"  × FAILED: {e}\n")
            db[file_id] = {
                "original_file_id": file_id,
                "verification_status": "FAILED",
                "notes": str(e),
                "timestamp": datetime.now().isoformat()
            }

        finally:
            # Always update DB and CSV after every attempt
            with open(DATABASE_FILE, "w") as f: json.dump(db, f, indent=2)
            update_manifest(db)
            if sid:
                try: urllib.request.urlopen(urllib.request.Request(f"{API_BASE}/files/{sid}?key={api_key}", method="DELETE"))
                except: pass

        time.sleep(8) # Mandatory Pacing

    # ─────────────────────────────────────────────
    #  FINAL DASHBOARD SUMMARY
    # ─────────────────────────────────────────────
    print("\n" + "="*52)
    print("  FINAL RUN SUMMARY")
    print("="*52)
    total = len(videos)
    verified = sum(1 for v in db.values() if v.get("verification_status") == "VERIFIED")
    failed   = sum(1 for v in db.values() if v.get("verification_status") == "FAILED")
    print(f"  Total Files in Folder: {total}")
    print(f"  ✅ Successfully Verified: {verified}")
    print(f"  ❌ Identification Failed: {failed}")
    print(f"  ⏳ Remaining / Pending:   {total - (verified + failed)}")
    print("="*52 + "\n")

if __name__ == "__main__":
    main()