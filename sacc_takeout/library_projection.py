"""Shared Library projection: source problems and human decisions survive triage."""
import json

METADATA_ATTENTION = frozenset({
    'date_conflict', 'gps_conflict', 'gps_invalid', 'invalid_embedded_date',
    'detected_media_type_mismatch', 'unknown_media_format', 'capture_date_missing',
    'metadata_write_readback_failed',
})
PRIVACY = frozenset({'unknown', 'personal', 'mixed', 'non_personal'})


def triage_record(con, oid):
    if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='library_triage_detections'").fetchone():
        return None
    row = con.execute('SELECT * FROM library_triage_detections WHERE id=?', (oid,)).fetchone()
    return dict(row) if row else None


def projection(raw, embedding_status, overrides, detection=None):
    if isinstance(raw, str):
        raw = json.loads(raw)
    if isinstance(overrides, str):
        overrides = json.loads(overrides)
    if not isinstance(raw, dict) or not isinstance(overrides, dict):
        raise ValueError('Invalid Library projection input')
    metadata_attention = embedding_status == 'unchanged_needs_review' or bool(
        set(raw.get('review_reasons', [])) & METADATA_ATTENTION)
    category = (detection or {}).get('category', 'unknown')
    status = (detection or {}).get('status', 'failed' if category == 'error' else 'succeeded')
    suggested = category if status == 'succeeded' and category in PRIVACY else 'unknown'
    privacy = overrides.get('privacy', suggested)
    if privacy not in PRIVACY:
        raise ValueError('Invalid retained privacy decision')
    triage_attention = detection is not None and (status != 'succeeded' or category in {'unknown', 'mixed', 'error'})
    return {'privacy': privacy, 'needs_attention': int(metadata_attention or triage_attention),
            'metadata_attention': bool(metadata_attention),
            'privacy_source': 'reviewed' if 'privacy' in overrides else 'automatic' if detection else 'unknown'}
