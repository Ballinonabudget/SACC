# OUTLET_PLUG_LOCAL_OCR_BUILD_BRIEF.md

Hand-off doc for Claude Code. Drafted Nov 9, 2026.
Pairs with: OUTLETPLUG_BARCODE_OCR_VERIFICATION_SPEC.md (already in Drive root) and LOCAL_AI_TOOLKIT_SETUP_PROMPT.md (installs the tools this brief uses).

---

## 1. In plain English

When Nitty photographs a shoebox label in a store, the system should read that label on the Mac Mini M1 itself (the barcode and the printed style code) instead of sending the photo to a paid AI. The Mac has built-in text and barcode reading (Apple Vision). The result gets checked against the KicksDB shoe database. Only photos that cannot be resolved locally go on to Gemini.

Goal: fewer paid calls, same or better accuracy, no slower.

---

## 2. Check first. Do not assume.

An OCR/barcode spec already exists (pyzbar + pytesseract on the captured label photo, with dual-extraction cross-validation). It may be fully built, partly built, or only specced. Before writing code:

1. Look in `outlet-plug-blog` (pipeline/, cli.py) for existing OCR or barcode code. Report in plain English what is built vs only specced.
2. Read OUTLETPLUG_BARCODE_OCR_VERIFICATION_SPEC.md from Drive root.
3. Confirm whether the KicksDB 401 authentication error is fixed. No style-code or UPC lookup works until it is. If still broken, diagnose that first and tell Nitty.
4. Check whether the shared toolkit exists at `~/local-ai-toolkit/` and read its `TOOLKIT_REGISTRY.md`. If it does not exist yet, the install prompt (LOCAL_AI_TOOLKIT_SETUP_PROMPT.md) comes first.

---

## 3. What to build

Upgrade the existing design: **Apple Vision becomes the primary reader; pyzbar and Tesseract stay as an independent second opinion** for cross-validation.

Flow per label photo (runs on the Mac, asynchronously, after the photo is ingested):

1. **Barcode:** Apple Vision barcode detection gives the UPC. Cross-check with pyzbar.
2. **Text:** Apple Vision text recognition in accurate mode (not fast mode) returns lines with confidence scores. Cross-check with Tesseract.
3. **Extract** from the text: style code, size, color text, any UPC digits.
4. **Look up:** UPC first (KicksDB supports UPC lookups at the size-variant level), then style code.
5. **Decide:**
   - Barcode and text agree on the same shoe AND KicksDB returns a record: auto-populate fields, mark high confidence.
   - Only one source succeeds AND KicksDB returns a record: populate, mark "single-source", send to the review queue.
   - Sources disagree, or KicksDB has no record: manual review queue showing both readings. No guessing.
   - Nothing readable: fall back to the existing Gemini identification, mark "AI-identified", always reviewed.
6. **Log** which tier resolved it (section 5).

**Trust rule.** The worst failure is a wrong style code (wrong shoe entirely), because the rest of the post is built from it. A reading only counts as verified if KicksDB has a matching record. A code that merely looks the right shape is not verification. Nothing auto-publishes. Everything still goes through the existing 2 to 3 day review queue.

**Starting patterns** (tune against real labels; these are not complete):
- Nike / Jordan current: 6 letters or digits, a hyphen, 3 digits.
- Nike older format: 6 digits, a separator, 3 digits (example from a real label: 724557-565).
- Adidas: usually 2 letters + 4 digits, or 1 letter + 5 digits.
- New Balance: model + color letters, varies a lot. Collect samples before writing a pattern.

Common OCR confusions (O/0, I/1, S/5, B/8) may be corrected only inside the expected position of a pattern, and a corrected value is accepted only if KicksDB confirms it.

---

## 4. How to call Apple Vision

Preferred order:
1. A small Swift command-line tool, compiled once, that takes an image path and prints JSON (text lines + confidence + barcodes). The Python pipeline calls it as a subprocess. Most reliable.
2. Python via the pyobjc Vision/Quartz bindings (or the `ocrmac` wrapper) if the Swift route is awkward.

Test both quickly, pick one, document the choice. Requirements:
- Zero network calls.
- Wrap it in one function, e.g. `read_label(image_path)`, returning a plain structure (barcodes, text lines, confidences).
- Put the tool in the shared toolkit folder (`~/local-ai-toolkit/bin/`), NOT buried inside `outlet-plug-blog`, so SACC and any future project can call the same thing. This is the first piece of the shared Shoe ID Service idea.

---

## 5. Logging (so we can prove the savings)

For every photo, record: which tier resolved it (apple_vision_barcode, apple_vision_text, tesseract_only, gemini_fallback, manual), time taken, confidence, and whether KicksDB confirmed it.

Produce a simple weekly summary: percent resolved locally, Gemini calls avoided, review-queue rate.

---

## 6. Test plan and acceptance

1. Pull about 50 real label photos from the backlog: mix of Nike, Jordan, Adidas, New Balance; clean ones and bad ones (glare, angle, blur, curved box ends).
2. Run the new local flow AND the current Gemini method on the same photos.
3. Compare: correct style code rate, wrong-but-confident rate, seconds per photo.
4. Acceptance:
   - Zero wrong style codes auto-populated as "high confidence" in the test set.
   - A majority resolved without Gemini. Report the real number; do not promise one in advance.
   - Per-photo time not slower than the Gemini path.
5. Report results to Nitty in plain English before changing any defaults.

---

## 7. Out of scope for this build

Logo or shoe detection (YOLO), visual fingerprint matching (DINOv2 / SigLIP), a local vision-language model, and price OCR (reading the sticker price plus a storewide "additional X% off"). These are later phases, tracked in LOCAL_AI_TOOLKIT_SETUP_PROMPT.md.

---

## 8. Conventions

- Keep a copy of this doc in the repo `docs/` folder and in Drive root, and keep them in sync.
- The WordPress site on IONOS cannot run any of this. All OCR runs on the Mac Mini M1.
- Public-facing site and PWA text must not name third-party services (KicksDB, Gemini). Describe errors generically.
- Never write credentials into docs or logs.
