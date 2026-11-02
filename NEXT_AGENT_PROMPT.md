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
- **Unit Tests**: 106 of 106 passing (`PYTHONPATH=tests:. .venv-poc-313/bin/python -m unittest discover tests`)
- **Latest Local Repair**: `9a80000` plus the handoff update; committed locally, not pushed. Read `docs/SACC_TRIAGE_REPAIR.md` before changing triage or restoring a backup.

### 3. What Was Just Completed by Antigravity
1. **Google Takeout Full Recovery**: 87,982 occurrences recovered; 63,558 metadata readbacks passed, 21,513 are manifest-only, and 2,911 require review. Do not describe every file as metadata-enriched.
2. **Catalog Ingestion**: All 87,982 occurrences imported into `sacc-library.sqlite3`.
3. **Full-Library Vision Triage on M1 GPU**:
   - Classifications recorded in `library_triage_detections` and `library_occurrences.privacy`:
     • `non_personal`: 43,542 automatic suggestions
     • `personal`: 29,181 automatic suggestions
     • `unknown`: 15,244 detections plus 15 errors (15,259 effective unknown privacy labels)
   - No human privacy reviews or production promotion approvals have occurred. These are suggestions, not physical quarantine folders or privacy clearance; all media remains local-only.
4. **Library Web UI**: Live on port 5174 (`http://localhost:5174/SACC.html`), supporting bidirectional manual privacy toggling (Personal ⇄ Non-personal). The normal launcher is `start_sacc.command`; the current process was restarted directly for this repair.

### 3a. Focused Codex Repair Just Applied
- Verified rollback catalog: `/Users/daplug/Documents/SACC_Data/backups/library-before-safeguards-2026-11-01_223312_EST/sacc-library.sqlite3`.
- Restored 9,611 hidden metadata warnings (9,793 attention projections total); retained metadata, file locators, source history, manual overrides and PoC rows exactly match the backup.
- Fixed note/clear/source-refresh label persistence, retries, partial batches, automatic audit provenance and protected-path bypasses. Added 15 regression tests.
- Retried 284 failed plus 14 skipped items locally: 283 succeeded, 15 remain flagged. All 14 previously skipped items were inferred.
- Remaining exceptions predate this repair: 12 truncated JPEGs, two unsupported Sony RAW files and one unknown media type. Original files were not rewritten.
- Live integrity and foreign-key checks passed; 87,982 occurrences retained; zero hidden metadata warnings or remote-eligible media. The app was restarted with repaired code.
- No external Antigravity QA has been sent or claimed. Legacy pricing/date/drop defects and organization/promotion workflows remain separate work.

### 4. Mandatory Guardrails
- **Byte-for-byte immutability**: Original Takeout files and NAS source videos (`/Volumes/The Final Cut X`) must NEVER be modified.
- **Privacy Guarantee**: Any file marked `privacy = 'personal'` must NEVER leave the machine, enter cloud APIs (Gemini/Vertex), or be promoted to `sacc_app.db`.
- **Preserve Working Tree**: Never run destructive Git commands (`git restore .`, `git reset --hard`, or `git clean -fd`) without operator approval. Always commit with agent tags like `[agent:codex]` or `[agent:claude]`.

### 5. Your Next Task
Honor the user's current instructions. The next focused work is source comparison and safe preview handling for the 15 remaining media exceptions, then human review of the suggestions and metadata concerns. Future options after that review:
1. **Physical Folder Organization Preview (Copy-on-Write)**:
   - Use `sacc_takeout/organization.py` / `scripts/sacc_library.py preview` to generate an APFS clonefile layout separating `organized/sneakers/` from `organized/personal/`.
2. **SACC Production DB Ingestion**:
   - Design and validate promotion of explicitly human-approved sneaker records into `sacc_app.db` (shoes, media_assets, price_observations). The automatic suggestions are not approvals.
3. **UI / Review Auditing**:
   - Help Nitty inspect and review flagged items in the Library tab at `http://localhost:5174/SACC.html`.
```
