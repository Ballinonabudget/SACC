import os
import subprocess
import json
import time
from datetime import datetime
from pathlib import Path

LOCATION_DATA = {
    "FLM": {"name": "The Florida Mall", "type": "MALL", "region": "Orlando"},
    "MAM": {"name": "Mall at Millenia", "type": "MALL", "region": "Orlando"},
    "OFS": {"name": "Orlando Fashion Square", "type": "MALL", "region": "Orlando"},
    "WOM": {"name": "West Oaks Mall", "type": "MALL", "region": "Orlando"},
    "VLD": {"name": "Vineland Premium Outlets", "type": "NFS", "region": "Orlando"},
    "IDR": {"name": "International Drive", "type": "NFS", "region": "Orlando"},
    "LBV": {"name": "Lake Buena Vista", "type": "NFS", "region": "Orlando"},
    "WFL": {"name": "Waterford Lakes", "type": "MALL", "region": "Orlando"},
    "WGN": {"name": "Winter Garden Village", "type": "MALL", "region": "Orlando"},
    "OMP": {"name": "Orlando Marketplace (I-Drive)", "type": "NCS", "region": "Orlando"},
    "SEM": {"name": "Seminole Towne Center", "type": "MALL", "region": "Sanford"},
    "LKL": {"name": "Lakeland Square Mall", "type": "MALL", "region": "Lakeland"},
    "PDM": {"name": "Paddock Mall", "type": "MALL", "region": "Ocala"},
    "THL": {"name": "Tallahassee Mall", "type": "MALL", "region": "Tallahassee"},
    "BRN": {"name": "Brandon Exchange (Brandon Mall)", "type": "MALL", "region": "Tampa"},
    "INP": {"name": "International Plaza", "type": "MALL", "region": "Tampa"},
    "UNM": {"name": "University Mall", "type": "MALL", "region": "Tampa"},
    "TPA": {"name": "Tampa Premium Outlets", "type": "NFS", "region": "Tampa"},
    "HVP": {"name": "Hyde Park Village", "type": "NIKE", "region": "Tampa"},
    "AVE": {"name": "Aventura Mall", "type": "NIKE", "region": "Miami"},
    "LCN": {"name": "Lincoln Road", "type": "NIKE", "region": "Miami"},
    "DOL": {"name": "Dolphin Mall", "type": "NFS", "region": "Miami"},
    "GVA": {"name": "Gainesville (Celebration Pointe)", "type": "NFS", "region": "Gainesville"},
    "CEL-K": {"name": "Celebration (Kissimmee)", "type": "NFS", "region": "Kissimmee"},
    "KSM": {"name": "Kissimmee (Osceola Pkwy)", "type": "NCS", "region": "Kissimmee"}
}

def extract_metadata(file_path):
    ffprobe_path = os.path.join(os.path.dirname(__file__), "ffprobe")
    if not os.path.exists(ffprobe_path):
        ffprobe_path = "ffprobe" # Fallback to system path if not found

    cmd = [
        ffprobe_path,
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        "-select_streams", "v:0",
        file_path
    ]

    try:
        output = subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        data = json.loads(output.decode('utf-8'))
        
        # Extract Creation Date
        creation_time = None
        cam_model = "Cam"

        # Check format tags
        fmt_tags = data.get("format", {}).get("tags", {})
        if "creation_time" in fmt_tags:
            creation_time = fmt_tags["creation_time"]
        
        if "com.apple.quicktime.model" in fmt_tags:
            cam_model = fmt_tags["com.apple.quicktime.model"].replace(" ", "")

        # Fallback to stream tags if format tags don't have it
        if not creation_time or cam_model == "Cam":
            streams = data.get("streams", [])
            if streams:
                strm_tags = streams[0].get("tags", {})
                if not creation_time and "creation_time" in strm_tags:
                    creation_time = strm_tags["creation_time"]
                if cam_model == "Cam" and "com.apple.quicktime.model" in strm_tags:
                    cam_model = strm_tags["com.apple.quicktime.model"].replace(" ", "")

        # Parse Date to YYMMDD
        date_str = datetime.now().strftime('%y%m%d') # default fallback
        if creation_time:
            # typical format: "2023-08-15T12:00:00.000000Z"
            try:
                dt = datetime.strptime(creation_time[:19], "%Y-%m-%dT%H:%M:%S")
                date_str = dt.strftime("%y%m%d")
            except ValueError:
                pass
                
        return date_str, cam_model

    except Exception as e:
        # Default fallback if ffprobe fails
        return datetime.now().strftime('%y%m%d'), "Cam"

def run_vibe_renamer(folder_path, loc_code, identifier):
    if not folder_path or not os.path.exists(folder_path):
        yield {"error": "Invalid folder path."}
        return
        
    store_type = LOCATION_DATA.get(loc_code, {}).get("type", "UNK")
    loc_header = f"{loc_code}-{store_type}"
    identifier_clean = identifier.replace(" ", "-")

    files = [f for f in os.listdir(folder_path) if not f.startswith('.') and f.lower().endswith(('.mp4', '.mov', '.m4v'))]
    
    if not files:
        yield {"error": "No valid video files found in the specified directory."}
        return

    start_time = time.time()
    results = []
    total_files = len(files)

    for i, filename in enumerate(files):
        file_path = os.path.join(folder_path, filename)
        base_orig, ext = os.path.splitext(filename)
        
        date_str, cam = extract_metadata(file_path)
        
        new_name = f"{loc_header}_{date_str}_{identifier_clean}_{cam}_{base_orig}{ext}"
        new_path = os.path.join(folder_path, new_name)
        
        os.rename(file_path, new_path)
        results.append({"original": filename, "new": new_name})
        
        yield {
            "success": True,
            "current": i + 1,
            "total": total_files,
            "original": filename,
            "new": new_name,
            "done": False
        }

    end_time = time.time()
    elapsed = round(end_time - start_time, 2)
    
    yield {
        "success": True,
        "done": True,
        "processed_count": len(results),
        "elapsed_seconds": elapsed,
        "results": results
    }
