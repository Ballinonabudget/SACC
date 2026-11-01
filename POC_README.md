# SACC Multi-Modal Ingestion/Search PoC

This PoC is an isolated, whole-asset pipeline for proving local-DAS ingestion,
Gemini identification, grouped video/image search, and manual-review routing.
It intentionally does **not** perform timestamp extraction or temporal
segmentation. Each media file is treated as one primary shoe entity.

## Architecture

```text
LocalStorageAdapter (/Volumes/External_Drive/staging by default)
NASStorageAdapter   (mounted SMB/NFS path, later)
        │
        ├── video → async FFmpeg H.264/AAC proxy → size guardrail ─┐
        └── image ───────────────────────────────→ size guardrail ─┤
                                                                 ▼
                                            Google Gen AI SDK / Vertex AI
                                                                 │
                                              strict JSON shoe identity
                                                                 │
                                                 sacc_multimodal.db
                                                                 │
                                  GET /api/v1/search → Multi-Modal UI
```

The PoC database is separate from legacy `clips` and `sneakers_broll` data.
It creates migration-managed `shoes`, `media_assets`, and `shoes_fts` tables.

## Setup

1. Install FFmpeg (`brew install ffmpeg`) or set `SACC_FFMPEG` and
   `SACC_FFPROBE`.
2. Create the supported Python 3.13 environment and install dependencies:

   ```bash
   /opt/homebrew/bin/python3.13 -m venv .venv-poc-313
   .venv-poc-313/bin/python -m pip install -r requirements-poc.txt
   ```

3. Copy the relevant PoC settings from `.env.example` into `.env`.
4. For Vertex AI, authenticate Application Default Credentials and set
   `GOOGLE_CLOUD_PROJECT`. `GEMINI_API_KEY` is supported as a fallback.

The default local source is `/Volumes/External_Drive/staging`. Override it with
`SACC_LOCAL_STAGING`; no application code changes are needed when switching to
`SACC_STORAGE_BACKEND=nas` and `SACC_NAS_ROOT=<mounted share>`.

## Run

Initialize the PoC database:

```bash
.venv-poc-313/bin/python -m sacc_poc.cli init-db
```

Ingest a small local batch:

```bash
.venv-poc-313/bin/python -m sacc_poc.cli ingest --backend local --limit 5 --height 720
```

Search from the CLI:

```bash
.venv-poc-313/bin/python -m sacc_poc.cli search "Jordan 1" --media-type video --media-type image
```

Launch the existing app with `start_sacc.command`, then open the **Multi-Modal**
sidebar view.

## API

- `GET /api/v1/health`
- `GET /api/v1/search?q=Jordan&media_types=video&media_types=image&limit=30&offset=0`
- `GET /api/v1/assets/{asset_id}`
- `GET /api/v1/review`
- `POST /api/v1/ingest`
- `GET /api/v1/ingest/{job_id}`

Example ingest request:

```json
{
  "backend": "local",
  "prefix": "",
  "recursive": true,
  "limit": 5,
  "target_height": 720
}
```

The confidence barrier is deliberately strict: every asset with SKU confidence
below `1.0`, or with an unreadable SKU, enters the manual-review queue. A `1.0`
result is independently checked with the configured fallback model; model
disagreement or an unavailable validation call also routes the asset to review.

The discovered NAS is available at `nasa.local` and currently mounts as
`/Volumes/The Final Cut X`. See `TEMPORAL_SEGMENTATION_PHASE2.md` for the design
that adds seekable shoe appearances after whole-asset identity is reliable.
