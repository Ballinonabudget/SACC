# Prompt for the Next Agent (Codex / Claude / Antigravity)

Copy and paste the prompt below into the next AI assistant:

```markdown
You are working on SACC (Sneaker Archive Command Center) alongside Nitty.

### 1. START HERE (Read First)
Before writing any code or running commands, read these files:
- `SACC_HANDOFF.md` — The single source of truth for repository state, milestones, and active locks.
- `SACC_ANTIGRAVITY_RESPONSIBILITIES_AND_CROSSCHECK.md` & `SACC_CODEX_RESPONSIBILITIES_AND_CROSSCHECK.md` — Operating rules and multi-agent coordination.
- `CLAUDE.md` — Launcher architecture and environment configuration.

### 2. Current State & Hardware
- **Repo Path**: `/Users/daplug/Documents/SACC`
- **Active Branch**: `codex/takeout-recovery-m1` (tracked on `origin/codex/takeout-recovery-m1`)
- **Hardware**: Apple Silicon M1 (macOS)
- **Python Environment**: `/Users/daplug/Documents/SACC/.venv-poc-313/bin/python`
- **Catalog Database**: `/Users/daplug/Documents/SACC_Data/library/staging/sacc-library.sqlite3`
- **Recovery Root**: `/Users/daplug/Documents/SACC_Data/recovery/denivic` (87,982 media files)
- **Unit Tests**: 91 of 91 passing (`PYTHONPATH=tests:. .venv-poc-313/bin/python -m unittest discover tests`)

### 3. What Was Just Completed by Antigravity
1. **Google Takeout Full Recovery**: 87,982 media files restored with EXIF timestamps and GPS tags.
2. **Catalog Ingestion**: All 87,982 occurrences imported into `sacc-library.sqlite3`.
3. **Full-Library Vision Triage on M1 GPU**:
   - Classifications recorded in `library_triage_detections` and `library_occurrences.privacy`:
     • `non_personal` (SACC Sneaker Candidates): 43,414 files (49.3%)
     • `personal` (Personal Quarantine Vault): 29,088 files (33.1%)
     • `unknown` (Operator Review Queue): 15,480 files (17.6%)
4. **Library Web UI**: Live on port 5174 via `start_sacc.command` (`http://localhost:5174/SACC.html`), supporting bidirectional manual privacy toggling (Personal ⇄ Non-personal).

### 4. Mandatory Guardrails
- **Byte-for-byte immutability**: Original Takeout files and NAS source videos (`/Volumes/The Final Cut X`) must NEVER be modified.
- **Privacy Guarantee**: Any file marked `privacy = 'personal'` must NEVER leave the machine, enter cloud APIs (Gemini/Vertex), or be promoted to `sacc_app.db`.
- **Preserve Working Tree**: Never run destructive Git commands (`git restore .`, `git reset --hard`, or `git clean -fd`) without operator approval. Always commit with agent tags like `[agent:codex]` or `[agent:claude]`.

### 5. Your Next Task
Ask Nitty which of the following next steps to execute:
1. **Physical Folder Organization Preview (Copy-on-Write)**:
   - Use `sacc_takeout/organization.py` / `scripts/sacc_library.py preview` to generate an APFS clonefile layout separating `organized/sneakers/` from `organized/personal/`.
2. **SACC Production DB Ingestion**:
   - Promote the 43,414 approved `non_personal` sneaker records into `sacc_app.db` (shoes, media_assets, price_observations).
3. **UI / Review Auditing**:
   - Help Nitty inspect and review flagged items in the Library tab at `http://localhost:5174/SACC.html`.
```
