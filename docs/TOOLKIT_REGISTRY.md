# Local AI Toolkit Registry

Created: November 9, 2026  
Host: Apple Mac mini (M1, 2020)  
Chip: Apple M1 (8 cores: 4 performance, 4 efficiency)  
RAM: 16 GB Unified Memory (Swap available: 4.0 GB)  
Disk: 926 GiB APFS volume, ~276 GiB available  
Environment: `~/local-ai-toolkit/venv` (Python 3.13.15)  
Binaries: `~/local-ai-toolkit/bin/`  

---

## 1. System CLI & Native Tooling

### Apple Vision OCR & Barcode CLI
* **Description:** Native compiled Swift CLI that extracts all text lines with confidence scores and detects barcodes/UPCs in a single local pass. Primary OCR engine for shoebox labels. Zero network calls.
* **Version:** 1.0.0 (Compiled with Apple Swift 6.4.2)
* **Location:** `~/local-ai-toolkit/bin/apple_vision`
* **Python Wrapper:** `~/local-ai-toolkit/apple_vision.py` (`read_label` and `read_label_crosscheck`)
* **Example Command:**
  ```bash
  ~/local-ai-toolkit/bin/apple_vision /path/to/box_label.jpg
  ```
* **License:** Apple Proprietary System Framework (built into macOS)
* **Tested Date:** 2026-11-09
* **Measured Speed:** **~0.24 seconds** per image
* **Projects Using:** Outlet Plug (`outletplug`), SACC (Sneaker Archive Command Center)

### Tesseract OCR
* **Description:** Local optical character recognition engine used as an independent second opinion to cross-validate Apple Vision readings.
* **Version:** 5.5.3 (Homebrew)
* **Location:** `/opt/homebrew/bin/tesseract` (Python wrapper: `pytesseract` 0.3.13)
* **Example Command:**
  ```bash
  /opt/homebrew/bin/tesseract /path/to/label.png stdout --oem 1 -l eng
  ```
* **License:** Apache-2.0
* **Tested Date:** 2026-11-09
* **Measured Speed:** ~0.15 seconds per crop
* **Projects Using:** Outlet Plug cross-validation queue

### zbar / pyzbar
* **Description:** Barcode and QR code scanning library used as independent cross-verification for UPC barcodes.
* **Version:** libzbar 0.23.93 (Homebrew) / pyzbar 0.1.9
* **Location:** `/opt/homebrew/bin/zbarimg` and `~/local-ai-toolkit/venv/lib/python3.13/site-packages/pyzbar`
* **Example Command:**
  ```bash
  /opt/homebrew/bin/zbarimg /path/to/barcode.png
  ```
* **License:** LGPL-2.1
* **Tested Date:** 2026-11-09
* **Measured Speed:** ~0.05 seconds per crop
* **Projects Using:** Outlet Plug cross-validation queue

### FFmpeg
* **Description:** Video and audio processing, frame extraction, transcoding, and HEVC compression.
* **Version:** 9.0.1 (Homebrew)
* **Location:** `/opt/homebrew/bin/ffmpeg`
* **Example Command:**
  ```bash
  ffmpeg -version
  ```
* **License:** LGPL-2.1+ / GPL-2.0+ (commercial flag: keep dynamic linking)
* **Tested Date:** 2026-11-09
* **Measured Speed:** Native Apple Silicon VideoToolbox hardware acceleration
* **Projects Using:** SACC, Outlet Plug

### Ollama Runtime & Vision-Language Model
* **Description:** Standalone local LLM/VLM runtime serving quantized vision-language models on Apple Silicon Metal GPU. Acts as the intermediate offline intelligence tier for hard-to-read labels prior to paid Gemini API calls.
* **Version:** 0.40.15
* **Location:** `~/local-ai-toolkit/bin/ollama` (bundle in `~/local-ai-toolkit/bin/ollama_dist`)
* **Installed Model:** `qwen3-vl:2b` (1.9 GB download, ~2.2 GB VRAM footprint)
* **Example Command:**
  ```bash
  ~/local-ai-toolkit/bin/ollama run qwen3-vl:2b "Read this shoebox label"
  ```
* **License:** Ollama: MIT; Qwen3-VL: Apache-2.0
* **Tested Date:** 2026-11-09
* **Measured Speed:** **41.3 tokens/second** (Warm inference: ~6.6 seconds per label extraction)
* **Projects Using:** Outlet Plug fallback tier, SACC

---

## 2. Python Libraries (`~/local-ai-toolkit/venv`)

| Package | Version | Purpose | License | Commercial Note | Tested |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Pillow** | 13.0.0 | Image manipulation & format conversion | MIT-CMU | Commercial friendly | PASS |
| **opencv-python** | 5.0.0.93 | Computer vision, cropping, pre-processing | Apache-2.0 | Commercial friendly | PASS |
| **scenedetect** | 0.7.3 | Video scene cut and boundary detection | BSD-3-Clause | Commercial friendly | PASS |
| **sqlite-vec** | 0.1.9 | In-process fast vector search & embedding storage | MIT / Apache-2.0 | Commercial friendly | PASS |
| **pyobjc-framework-Vision** | 13.0 | Direct Python bindings to Apple Vision | MIT | Commercial friendly | PASS |
| **pyobjc-framework-Quartz** | 13.0 | CoreGraphics image source bindings | MIT | Commercial friendly | PASS |
| **pytesseract** | 0.3.13 | Tesseract Python interface | Apache-2.0 | Commercial friendly | PASS |
| **pyzbar** | 0.1.9 | ZBar Python barcode reading interface | MIT | Commercial friendly | PASS |
| **torch** | 2.15.0 | Deep learning framework with Metal (MPS) GPU support | BSD-3-Clause | Commercial friendly | PASS |
| **torchvision** | 0.29.2 | Vision transforms and models | BSD-3-Clause | Commercial friendly | PASS |
| **transformers** | 5.22.2 | Hugging Face transformer architectures | Apache-2.0 | Commercial friendly | PASS |
| **sentencepiece** | 0.2.3 | Fast tokenizer supporting multimodal models | Apache-2.0 | Commercial friendly | PASS |
| **ultralytics** | 8.4.208 | Object and label bounding-box detection (YOLO) | AGPL-3.0 | Internal R&D use (replace prior to commercial sale) | PASS |

---

## 3. Computer Vision & Feature Embedding Models

### DINOv2 (`facebook/dinov2-small`)
* **Description:** Vision transformer for visual image fingerprinting and visual similarity matching across sneaker angles.
* **Size:** 88.2 MB download (384-dimensional dense vectors)
* **Location:** Hugging Face cache (`~/.cache/huggingface/hub/models--facebook--dinov2-small`)
* **Execution Device:** Apple Silicon GPU via Metal Performance Shaders (`mps`)
* **License:** Apache-2.0 (Commercial friendly)
* **Tested Date:** 2026-11-09
* **Measured Speed:** **3.6 milliseconds** per image
* **Projects Using:** SACC Phase 7.5, Outlet Plug visual verification

### SigLIP (`google/siglip-base-patch16-224`)
* **Description:** Multimodal vision-language embedding model for zero-shot classification and text-to-image similarity.
* **Size:** 813 MB download (768-dimensional dense vectors)
* **Location:** Hugging Face cache (`~/.cache/huggingface/hub/models--google--siglip-base-patch16-224`)
* **Execution Device:** Apple Silicon GPU via Metal Performance Shaders (`mps`)
* **License:** Apache-2.0 (Commercial friendly)
* **Tested Date:** 2026-11-09
* **Measured Speed:** **4.2 milliseconds** per image
* **Projects Using:** SACC photo recognizer, Outlet Plug

### Ultralytics YOLO (`yolo11n.pt`)
* **Description:** Real-time object detection for box labels, shoes, and logos.
* **Size:** 5.4 MB
* **Execution Device:** Apple Silicon GPU via Metal Performance Shaders (`mps`)
* **License:** AGPL-3.0 (Commercial note: Approved for internal development/use; will train custom architecture before commercial distribution)
* **Tested Date:** 2026-11-09
* **Measured Speed:** **6.8 milliseconds** per image
* **Projects Using:** SACC, Outlet Plug detection queue

---

## 4. Audio Transcription (Pre-existing)

### mlx-whisper
* **Description:** High-efficiency Apple Silicon native Whisper speech-to-text.
* **Version:** 0.4.3 (in `~/Documents/Backcatalog/.venv/`)
* **Location:** `~/Documents/Backcatalog/.venv/lib/python3.13/site-packages/mlx_whisper`
* **License:** MIT
* **Status:** Operational. Preserved as-is per Ground Rule 1.

---

## 5. Tier 3 Backup Tools

* **PaddleOCR:** Kept uninstalled on reserve as a secondary backup if Apple Vision and Tesseract ever prove insufficient for complex non-Latin scripts or specialized label conditions.
