"""Path B orchestrator: video → multi-frame → Gemini (best frame + bbox) → DINOv2 → verdict."""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from kicksdb_enricher import enrich as kicksdb_enrich  # noqa: E402

from .crop import crop_to_bbox, normalize_bbox
from .dinov2_similarity import embed_image, max_similarity
from .gemini_identify import identify
from .keyframe import extract_keyframes
from .kicksdb_search import fetch_image, gallery_urls, search_by_description
from .verdict import classify
from .video_metadata import is_plausible, video_capture_date, years_diff


def _norm_sku(sku: str) -> str:
    """Normalize SKU for comparison: uppercase, strip spaces/hyphens."""
    return (sku or "").upper().replace(" ", "").replace("-", "").strip()


def verify_clip(video_path: str,
                top_n_candidates: int = 3,
                max_skus_per_query: int = 5,
                max_gallery_per_sku: int = 5,
                source: str = "goat",
                n_frames: int = 12,
                n_frames_to_gemini: int = 12,
                use_bbox_crop: bool = False,
                date_filter: bool = True,
                date_window_years: float = 2.0,
                verbose: bool = False) -> dict:
    """Run Path B (with Path A short-circuit when label visible) on one video.

    Pipeline:
      1. Extract N evenly-spaced frames, sharpness-score them
      2. Send top sharpest frames to Gemini, get back best frame + shoe_bbox + candidates
      3. Crop chosen frame to shoe_bbox before DINOv2 embedding
      4. Resolve candidates → KicksDB → DINOv2 → verdict
    """
    out: dict = {
        "video_path": str(video_path),
        "video_date": None,
        "path": None,
        "label_visible": False,
        "label_sku": "",
        "best_frame_idx": None,
        "best_frame_time": None,
        "best_frame_reason": "",
        "shoe_bbox": None,
        "candidates_raw": [],
        "candidates_scored": [],
        "candidates_filtered_out": [],
        "chosen_sku": None,
        "chosen_model": None,
        "chosen_colorway": None,
        "visual_similarity": 0.0,
        "verdict": "unverified",
        "error": None,
    }
    out["video_date"] = video_capture_date(video_path) if date_filter else None

    frames: list[dict] = []
    try:
        # ── Step 0: Extract candidate frames + sharpness scoring ──────────────
        frames = extract_keyframes(video_path, n=n_frames)
        if verbose:
            for fr in frames:
                print(f"    frame t={fr['time_sec']:.2f}s sharp={fr['sharpness']:.0f}  {fr['path']}")
        # Pick top-K sharpest for Gemini
        chosen_frames = frames[:n_frames_to_gemini]
        gemini_inputs = [fr["path"] for fr in chosen_frames]

        # ── Step 1: Gemini multi-frame identification ─────────────────────────
        ident = identify(gemini_inputs, top_n=top_n_candidates)
        out["candidates_raw"]    = ident.get("candidates", [])
        out["label_visible"]     = ident.get("label_visible", False)
        out["label_sku"]         = ident.get("label_sku", "")
        out["best_frame_reason"] = ident.get("best_frame_reason", "")
        candidates = list(ident.get("candidates", []))

        # Resolve which input frame Gemini chose (it indexes into chosen_frames)
        bfi = ident.get("best_frame_index", 0)
        if 0 <= bfi < len(chosen_frames):
            best_frame = chosen_frames[bfi]
        else:
            best_frame = chosen_frames[0] if chosen_frames else None
        out["best_frame_idx"]  = best_frame["index"] if best_frame else None
        out["best_frame_time"] = best_frame["time_sec"] if best_frame else None
        # Read the chosen frame bytes BEFORE cleanup so callers can save it
        if best_frame:
            try:
                with open(best_frame["path"], "rb") as fh:
                    out["best_frame_bytes"] = fh.read()
            except Exception:
                out["best_frame_bytes"] = None

        # bbox: kept for inspector visualisation but NOT used for cropping by default.
        # Empirically, bbox crops cut off parts of the shoe more often than they help;
        # using Gemini's full chosen frame gives DINOv2 the same information without
        # the risk of bad crops. Set use_bbox_crop=True to opt in.
        bbox = normalize_bbox(ident.get("shoe_bbox"))
        if bbox is not None:
            area = (bbox["x_max"] - bbox["x_min"]) * (bbox["y_max"] - bbox["y_min"])
            if area > 0.97:
                bbox = None
        out["shoe_bbox"] = bbox

        if best_frame is None:
            query_bytes = None
        elif use_bbox_crop and bbox:
            try:
                query_bytes = crop_to_bbox(best_frame["path"], bbox, padding=0.04)
            except Exception:
                with open(best_frame["path"], "rb") as fh:
                    query_bytes = fh.read()
        else:
            with open(best_frame["path"], "rb") as fh:
                query_bytes = fh.read()
        out["query_bytes"] = query_bytes
        if verbose:
            print(f"    best_frame_idx={out['best_frame_idx']} t={out['best_frame_time']} bbox={bbox}")

        # If a SKU was read from a label, prepend it as the strongest candidate
        if out["label_sku"]:
            candidates.insert(0, {
                "model":        "(from label)",
                "colorway":     "",
                "search_query": out["label_sku"],
                "year":         "",
                "confidence":   1.0,
                "_label_sku":   out["label_sku"],
            })
            out["path"] = "ocr"
        else:
            out["path"] = "visual"

        if not candidates or query_bytes is None:
            return out

        # ── Step 2: Resolve each candidate to KicksDB SKUs ────────────────────
        query_emb = embed_image(query_bytes)
        scored: list[dict] = []
        seen_skus: set[str] = set()

        for cand in candidates:
            specific = (cand.get("search_query") or "").strip()
            broad    = (cand.get("model_only_query") or "").strip()
            queries  = [q for q in (specific, broad) if q]
            # dedupe queries (sometimes Gemini emits the same string twice)
            seen_q: set[str] = set()
            queries = [q for q in queries if not (q.lower() in seen_q or seen_q.add(q.lower()))]

            products: list[dict] = []
            for q in queries:
                got = search_by_description(q, max_results=max_skus_per_query, source=source)
                if not got and source != "stockx":
                    got = search_by_description(q, max_results=max_skus_per_query, source="stockx")
                if verbose:
                    print(f"    query={q!r:<60s} → {len(got)} products")
                products.extend(got)

            for p in products:
                sku_raw = (p.get("sku") or p.get("style_id") or "").upper()
                sku_norm = _norm_sku(sku_raw)
                if not sku_norm or sku_norm in seen_skus:
                    continue
                seen_skus.add(sku_norm)
                sku = sku_raw

                # ── Date filter: skip products released after the video was shot ──
                if date_filter and out["video_date"]:
                    rd = (p.get("release_date") or p.get("releaseDate") or "")
                    if rd and not is_plausible(rd, out["video_date"],
                                                max_years_after=0.5):
                        out["candidates_filtered_out"].append({
                            "sku":          sku,
                            "release_date": rd,
                            "reason":       "release_after_video",
                        })
                        if verbose:
                            print(f"      FILTERED sku={sku} release={rd} (video={out['video_date']})")
                        continue

                urls = gallery_urls(p, max_urls=max_gallery_per_sku)
                if not urls:
                    continue

                gallery_embs = []
                for u in urls:
                    img_bytes = fetch_image(u)
                    if img_bytes is None:
                        continue
                    try:
                        gallery_embs.append(embed_image(img_bytes))
                    except Exception:
                        pass
                if not gallery_embs:
                    continue

                sim, _ = max_similarity(query_emb, gallery_embs)
                rd = (p.get("release_date") or p.get("releaseDate") or "")
                # Soft preference: small bonus for releases within the date window
                # before the video. This nudges ties toward the era-appropriate retro.
                date_bonus = 0.0
                if date_filter and out["video_date"] and rd:
                    yd = years_diff(out["video_date"], rd)
                    if yd is not None and 0 <= yd <= date_window_years:
                        date_bonus = 0.03  # small but tie-breaking
                scored.append({
                    "sku":                  sku,
                    "model":                p.get("model") or p.get("name") or p.get("title") or "",
                    "colorway":             p.get("colorway") or p.get("secondary_title") or "",
                    "title":                p.get("title") or p.get("name") or "",
                    "release_date":         rd,
                    "candidate_query":      q,
                    "candidate_confidence": cand.get("confidence"),
                    "similarity":           sim,
                    "score":                sim + date_bonus,
                    "date_bonus":           date_bonus,
                    "n_gallery":            len(gallery_embs),
                })
                if verbose:
                    print(f"      sku={sku} sim={sim:.3f} title={p.get('title','')[:60]}")

        if not scored:
            return out

        # ── Step 3: Pick highest-scoring option (similarity + date bonus) ─────
        scored.sort(key=lambda o: -o["score"])
        best = scored[0]

        out["candidates_scored"]  = scored
        out["chosen_sku"]         = best["sku"]
        out["chosen_model"]       = best["model"]
        out["chosen_colorway"]    = best["colorway"]
        out["visual_similarity"]  = best["similarity"]
        out["verdict"]            = classify(out["path"], best["similarity"])
        return out

    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
        return out
    finally:
        # Clean up extracted frames
        for fr in frames:
            try:
                os.unlink(fr["path"])
            except Exception:
                pass
        # Try to remove the temp dir too
        try:
            if frames:
                Path(frames[0]["path"]).parent.rmdir()
        except Exception:
            pass


__all__ = ["verify_clip"]
