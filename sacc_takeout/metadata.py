"""Evidence-preserving metadata proposals and bounded ExifTool copy verification."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import re
import subprocess
import uuid

from .common import file_hash, finite, no_symlinks

TAGS = (
    "Make", "Model", "Orientation", "DateTimeOriginal", "OffsetTimeOriginal", "CreateDate",
    "CreationDate", "MediaCreateDate", "TrackCreateDate", "DateCreated", "Description",
    "GPSLatitude", "GPSLatitudeRef", "GPSLongitude", "GPSLongitudeRef", "GPSAltitude",
    "GPSAltitudeRef", "GPSCoordinates", "GPSHPositioningError", "GPSHorizontalAccuracy",
    "GPSMapDatum", "ImageWidth", "ImageHeight", "MIMEType", "FileType", "ContentIdentifier",
)
COPY_FORMATS = {".jpg", ".jpeg", ".png"}


def raw(value):
    if isinstance(value, float) and not math.isfinite(value):
        return {"non_json_number": repr(value)}
    if isinstance(value, dict):
        return {str(k): raw(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [raw(v) for v in value]
    return value


def read_tags(paths, executable="exiftool"):
    result = {}
    for start in range(0, len(paths), 40):
        batch = [str(Path(p).absolute()) for p in paths[start:start+40]]
        proc = subprocess.run([executable, "-config", "", "-j", "-n", "-G1", "-a", "-s",
                               "-api", "QuickTimeUTC=0", *("-"+t for t in TAGS), *batch],
                              capture_output=True, text=True, timeout=180)
        try:
            records = json.loads(proc.stdout)
        except ValueError as exc:
            raise RuntimeError("ExifTool returned no readable JSON") from exc
        for row in records:
            source = row.get("SourceFile")
            if source in batch:
                result[source] = row
        for p in batch:
            if p not in result:
                result[p] = {"SourceFile": p, "ExifTool:Error": "Missing ExifTool result"}
    return result


def parse_date(value, offset=None):
    if not isinstance(value, str):
        return None
    value = re.sub(r"^(\d{4}):(\d{2}):(\d{2})", r"\1-\2-\3", value.strip())
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None and offset is not None:
            if not isinstance(offset, str) or not re.fullmatch(r"[+-]\d{2}:\d{2}", offset):
                return None
            hours, minutes = map(int, offset[1:].split(":"))
            if hours > 14 or minutes > 59 or (hours == 14 and minutes):
                return None
            parsed = parsed.replace(tzinfo=timezone(timedelta(minutes=(hours*60+minutes)*(1 if offset[0]=="+" else -1))))
        return parsed
    except (ValueError, OverflowError):
        return None


def date_record(source, value, parsed, timezone_evidence):
    return {"source": source, "raw": raw(value), "valid": parsed is not None,
            "utc": parsed.astimezone(timezone.utc).isoformat() if parsed and parsed.tzinfo else None,
            "local": parsed.isoformat() if parsed else None, "timezone_evidence": timezone_evidence}


def capture_proposal(document, embedded, zip_time, as_of):
    observations, issues = [], []
    taken = document.get("photoTakenTime")
    parsed = None
    if isinstance(taken, dict):
        stamp = taken.get("timestamp")
        if isinstance(stamp, (str, int)) and not isinstance(stamp, bool) and re.fullmatch(r"-?\d+", str(stamp)):
            try:
                parsed = datetime.fromtimestamp(int(stamp), timezone.utc)
            except (ValueError, OverflowError, OSError):
                pass
    if taken is not None:
        observations.append(date_record("photoTakenTime.timestamp", taken, parsed, "Unix timestamp is a UTC instant"))
        if parsed is None:
            issues.append("invalid_photo_taken_time")
    priority = {"DateTimeOriginal": 0, "CreationDate": 1, "DateCreated": 2, "CreateDate": 3,
                "MediaCreateDate": 4, "TrackCreateDate": 5}
    for field in sorted(embedded, key=lambda k: (priority.get(k.split(":")[-1], 99), k)):
        name = field.split(":")[-1]
        if name not in priority:
            continue
        offset = embedded.get("ExifIFD:OffsetTimeOriginal") if name == "DateTimeOriginal" else None
        dt = parse_date(embedded[field], offset)
        observations.append(date_record(field, embedded[field], dt,
                            "explicit embedded offset" if dt and dt.tzinfo else "unknown; wall-clock value retained"))
        if dt is None:
            issues.append("invalid_embedded_date")
        elif dt.tzinfo is None:
            issues.append("embedded_timezone_unknown")
    valid = [o for o in observations if o["valid"]]
    selected = dict(valid[0]) if valid else None
    aware = [datetime.fromisoformat(o["utc"]) for o in valid if o["utc"]]
    conflict = bool(aware and (max(aware)-min(aware)).total_seconds() > 120)
    # Offset-free dates cannot be compared as instants. Large wall-clock jumps
    # are still suspicious even after allowing the entire terrestrial offset range.
    if parsed:
        for o in valid[1:]:
            if not o["utc"] and abs((datetime.fromisoformat(o["local"])-parsed.replace(tzinfo=None)).total_seconds()) > 15*3600:
                conflict = True
    if conflict:
        issues.append("date_conflict")
    if selected is None and zip_time:
        try:
            dt = datetime(*zip_time)
        except (ValueError, TypeError):
            dt = None
        selected = date_record("zip_member.date_time", zip_time, dt, "unknown; ZIP timestamp is not capture evidence")
        observations.append(selected.copy())
        issues.append("zip_time_fallback_untrusted")
    if selected is None or not selected["valid"]:
        issues.append("capture_date_missing")
    if selected and selected["valid"]:
        dt = datetime.fromisoformat(selected["utc"] or selected["local"])
        if dt.year < 2005 or dt.date() > as_of + timedelta(days=1):
            issues.append("suspicious_capture_date")
        if selected["utc"] is None:
            issues.append("selected_timezone_unknown")
        selected["confidence"] = "source_reported" if selected["source"] == "photoTakenTime.timestamp" else "requires_review"
    safe = bool(selected and selected["utc"] and not any(i in issues for i in
                ("date_conflict", "suspicious_capture_date", "invalid_photo_taken_time", "invalid_embedded_date")))
    return {"observations": observations, "selected": selected, "conflict": conflict, "safe_to_embed": safe}, issues


def distance_m(a, b):
    lat1, lat2 = math.radians(a["latitude"]), math.radians(b["latitude"])
    dlat, dlon = lat2-lat1, math.radians(b["longitude"]-a["longitude"])
    h = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    return 6371008.8*2*math.asin(math.sqrt(min(1, max(0, h))))


def gps_observation(source, values, accuracy=None):
    lat, lon = values.get("latitude"), values.get("longitude")
    reason = None
    if lat is None and lon is None:
        reason = "missing"
    elif not finite(lat) or not finite(lon) or not -90 <= lat <= 90 or not -180 <= lon <= 180:
        reason = "invalid_or_partial"
    elif lat == 0 and lon == 0:
        reason = "zero_placeholder"
    accuracy_invalid = accuracy is not None and (not finite(accuracy) or accuracy < 0)
    return {"source": source, "raw": raw(values), "valid": reason is None, "reason": reason,
            "latitude": lat if reason is None else None, "longitude": lon if reason is None else None,
            "accuracy_m": accuracy if accuracy is not None and not accuracy_invalid else None,
            "accuracy_invalid": accuracy_invalid}


def gps_proposal(document, embedded, tolerance_m):
    observations, issues = [], []
    for source in ("geoDataExif", "geoData"):
        if source not in document:
            continue
        values = document[source]
        if not isinstance(values, dict):
            observations.append({"source": source, "raw": raw(values), "valid": False, "reason": "malformed"})
            issues.append("gps_invalid")
        else:
            observations.append(gps_observation(source, values, values.get("accuracy")))
    groups = sorted({k.rsplit(":", 1)[0] for k in embedded if k.endswith(":GPSLatitude") or k.endswith(":GPSLongitude")})
    for group in groups:
        values = {"latitude": embedded.get(group+":GPSLatitude"), "longitude": embedded.get(group+":GPSLongitude")}
        for axis, refname, positive, negative in (("latitude", "GPSLatitudeRef", "N", "S"), ("longitude", "GPSLongitudeRef", "E", "W")):
            ref = embedded.get(group+":"+refname)
            if ref is not None:
                values[refname] = ref
                if ref not in {positive, negative} or not finite(values[axis]):
                    issues.append("gps_invalid")
                elif values[axis] < 0 and ref == positive:
                    issues.append("gps_conflicting_reference")
                else:
                    values[axis] = abs(values[axis]) * (1 if ref == positive else -1)
        observations.append(gps_observation(group+":GPSLatitude/GPSLongitude", values, embedded.get(group+":GPSHPositioningError")))
    for field, value in embedded.items():
        if field.endswith(":GPSCoordinates"):
            values = {}
            if isinstance(value, str):
                try:
                    numbers = [float(n) for n in re.findall(r"[+-]?\d+(?:\.\d+)?", value)]
                    if len(numbers) >= 2:
                        values = {"latitude": numbers[0], "longitude": numbers[1], "raw_coordinates": value}
                except ValueError:
                    pass
            if not values:
                issues.append("gps_invalid")
            observations.append(gps_observation(field, values, embedded.get("Keys:GPSHorizontalAccuracy")))
    for o in observations:
        if o.get("reason") in {"invalid_or_partial", "malformed"}:
            issues.append("gps_invalid")
        if o.get("accuracy_invalid"):
            issues.append("gps_accuracy_invalid")
    valid = [o for o in observations if o["valid"]]
    conflicts = []
    for i, a in enumerate(valid):
        for b in valid[i+1:]:
            separation = distance_m(a, b)
            limit = max(tolerance_m, (a.get("accuracy_m") or 0)+(b.get("accuracy_m") or 0))
            if separation > limit:
                conflicts.append({"sources": [a["source"], b["source"]], "distance_m": separation, "tolerance_m": limit})
    if conflicts:
        issues.append("gps_conflict")
    if valid and any(o.get("accuracy_m") is None for o in valid):
        issues.append("gps_accuracy_unknown")
    if not valid:
        issues.append("gps_missing")
    selected = None
    if valid and not any(i in issues for i in ("gps_conflict", "gps_invalid", "gps_conflicting_reference")):
        best = sorted(valid, key=lambda o: 0 if o["source"] == "geoDataExif" else 2 if o["source"] == "geoData" else 1)[0]
        selected = {k: best[k] for k in ("source", "latitude", "longitude", "accuracy_m")}
        selected["reason"] = "Validated source observation; other valid observations agree within policy tolerance. Accuracy is not inferred."
    return {"observations": observations, "selected": selected, "conflicts": conflicts,
            "available": bool(valid), "safe_to_embed": selected is not None}, issues


def propose(document, embedded, zip_time, as_of, tolerance_m=100):
    capture, dates = capture_proposal(document, embedded, zip_time, as_of)
    gps, locations = gps_proposal(document, embedded, tolerance_m)
    issues = dates+locations
    if any(k.endswith(":Error") for k in embedded):
        issues.append("embedded_read_error")
    mime = embedded.get('File:MIMEType')
    if mime and not mime.startswith(('image/', 'video/')):
        issues.append('detected_media_type_mismatch')
    description = document.get("description")
    if description is not None and not isinstance(description, str):
        issues.append("description_invalid")
        description = None
    return {"capture": capture, "observed_gps": gps, "description": description,
            "raw_sidecar": raw(document), "embedded": raw(embedded), "review_reasons": sorted(set(issues)),
            "store_assignment": {"status": "needs_review", "store_id": None, "store_version_id": None,
                                 "venue_id": None, "evidence": [], "confidence": None},
            "privacy": "unknown", "remote_eligible": False}


def verify_copy(source, destination, proposal):
    source, destination = Path(source), no_symlinks(destination)
    if source.resolve() == destination.resolve() or source.suffix.lower() not in COPY_FORMATS:
        raise ValueError("Copy verification requires a separate JPEG/PNG destination")
    if destination.exists():
        raise ValueError("Existing output must be validated by the manifest, never overwritten")
    if not proposal["capture"]["safe_to_embed"] or any(i in proposal["review_reasons"] for i in
            ("gps_conflict", "gps_invalid", "gps_conflicting_reference", "embedded_read_error", "detected_media_type_mismatch", "duplicate_metadata_conflict", "ambiguous_sidecar", "missing_sidecar")):
        raise ValueError("Conflicting or uncertain metadata is not eligible for copy verification")
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = destination.with_name(".copy-"+uuid.uuid4().hex+source.suffix.lower())
    captured = proposal["capture"]["selected"]["utc"]
    expected = {"XMP-photoshop:DateCreated": captured}
    args = ["exiftool", "-config", "", "-o", str(temporary), "-XMP-photoshop:DateCreated="+captured]
    description = proposal.get("description")
    old_descriptions = [v for k, v in proposal["embedded"].items() if k.endswith(":Description")]
    if description and not old_descriptions:
        expected["XMP-dc:Description"] = description
        args.append("-XMP-dc:Description="+description)
    geo = proposal["observed_gps"]["selected"]
    embedded_gps = any(k.endswith((":GPSLatitude", ":GPSLongitude", ":GPSCoordinates")) for k in proposal["embedded"])
    if geo and not embedded_gps:
        lat, lon = geo["latitude"], geo["longitude"]
        expected.update({"GPS:GPSLatitude": abs(lat), "GPS:GPSLatitudeRef": "N" if lat >= 0 else "S",
                         "GPS:GPSLongitude": abs(lon), "GPS:GPSLongitudeRef": "E" if lon >= 0 else "W"})
        args.extend("-EXIF:"+k.split(":")[-1]+"="+str(v) for k, v in expected.items() if k.startswith("GPS:"))
    source_hash = file_hash(source)
    try:
        subprocess.run([*args, str(source)], capture_output=True, text=True, check=True, timeout=120)
        checked = read_tags([temporary])[str(temporary.absolute())]
        for field, value in expected.items():
            got = checked.get(field)
            if field.endswith(":DateCreated"):
                got_date, expected_date = parse_date(got), parse_date(value)
                valid = got_date is not None and got_date == expected_date
            elif finite(value):
                valid = finite(got) and abs(got-value) < 0.000001
            else:
                valid = got == value
            if not valid:
                raise ValueError("Readback mismatch for "+field)
        for field, value in proposal["embedded"].items():
            if field.split(":")[-1] in {"Make", "Model", "Orientation", "DateTimeOriginal", "OffsetTimeOriginal", "CreateDate",
                                          "GPSLatitude", "GPSLongitude", "GPSLatitudeRef", "GPSLongitudeRef", "ContentIdentifier"}:
                if checked.get(field) != value:
                    raise ValueError("Existing embedded field changed: "+field)
        timestamp_ns = int(datetime.fromisoformat(captured).timestamp()*1_000_000_000)
        os.utime(temporary, ns=(temporary.stat().st_atime_ns, timestamp_ns))
        if abs(temporary.stat().st_mtime_ns-timestamp_ns) > 1000:
            raise ValueError("Recovered-copy mtime readback failed")
        if file_hash(source) != source_hash:
            raise ValueError("Staged source changed during copy verification")
        temporary.chmod(0o600)
        os.replace(temporary, destination)
        return {"status": "verified", "path": str(destination), "sha256": file_hash(destination),
                "expected_tags": expected, "readback": checked, "mtime_ns": destination.stat().st_mtime_ns,
                "source_sha256": source_hash}
    finally:
        if temporary.exists():
            temporary.unlink()
