# SACC Phase 2: Temporal Segmentation and Timestamp Search

The current PoC answers one question:

> Which primary shoe is associated with this complete media file?

Temporal segmentation answers the more useful archive question:

> Which shoes appear inside this file, and exactly when does each appearance
> begin and end?

For example, a 20-minute video might contain an Air Jordan 1 only from
`02:14–02:21` and again from `17:44–18:02`. Whole-asset indexing can attach the
shoe to the video, but it cannot produce either seek point. Phase 2 creates
those seekable appearance records.

## Proposed pipeline

1. Use FFmpeg scene-change detection plus coarse frame sampling to divide a
   video into candidate shots. Do not upload every frame.
2. Generate a compact contact sheet or short proxy segment for each candidate
   shot.
3. Ask Gemini which shoe entities are visible in that segment and require
   structured start/end timecodes, identity fields, and confidence.
4. Merge adjacent detections for the same shoe when the gap is below a small
   threshold, such as one second.
5. Run a finer pass around each boundary so seek points start just before the
   shoe becomes visible and end just after it disappears.
6. Route identity disagreement, unreadable SKUs, and uncertain boundaries to
   review.

## Schema extension

```sql
CREATE TABLE appearances (
    id             INTEGER PRIMARY KEY,
    media_asset_id INTEGER NOT NULL REFERENCES media_assets(id),
    shoe_id        INTEGER NOT NULL REFERENCES shoes(id),
    start_ms       INTEGER NOT NULL,
    end_ms         INTEGER NOT NULL,
    confidence     REAL NOT NULL,
    needs_review   INTEGER NOT NULL DEFAULT 1,
    review_reason  TEXT NOT NULL DEFAULT '',
    CHECK (start_ms >= 0 AND end_ms > start_ms)
);

CREATE INDEX idx_appearances_shoe_time
ON appearances(shoe_id, media_asset_id, start_ms);
```

Search results can then include links such as
`/api/v1/assets/101#t=134,141`, allowing the video player or editor to jump
directly to the matching section.

## Why this is a second phase

It is more expensive and less forgiving than whole-file classification. SACC
first needs reliable storage, proxy generation, identity validation, and search
entities. Once those foundations are stable, timestamp extraction can reuse
the same proxies, shoes, review queue, and media-serving API rather than
building a second disconnected pipeline.

