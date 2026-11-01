"""DINOv2 image embedding + cosine similarity (with per-process caches)."""
from __future__ import annotations

import hashlib
import io
from functools import lru_cache

import torch
import torch.nn.functional as F
from PIL import Image

_MODEL_NAME = "facebook/dinov2-base"

_DEVICE = "mps" if torch.backends.mps.is_available() else (
    "cuda" if torch.cuda.is_available() else "cpu"
)

_BYTES_EMBED_CACHE: dict[str, torch.Tensor] = {}


@lru_cache(maxsize=1)
def _load():
    from transformers import AutoImageProcessor, AutoModel
    proc = AutoImageProcessor.from_pretrained(_MODEL_NAME)
    model = AutoModel.from_pretrained(_MODEL_NAME).to(_DEVICE).eval()
    return proc, model


def _to_pil(source) -> Image.Image:
    if isinstance(source, Image.Image):
        return source.convert("RGB")
    if isinstance(source, bytes):
        return Image.open(io.BytesIO(source)).convert("RGB")
    if isinstance(source, str):
        return Image.open(source).convert("RGB")
    raise TypeError(f"Unsupported source type: {type(source)}")


@torch.no_grad()
def embed_image(source) -> torch.Tensor:
    """Return a unit-norm 1-D embedding tensor (CPU). Caches for bytes input."""
    cache_key = None
    if isinstance(source, bytes):
        cache_key = hashlib.sha1(source).hexdigest()
        cached = _BYTES_EMBED_CACHE.get(cache_key)
        if cached is not None:
            return cached

    proc, model = _load()
    img = _to_pil(source)
    inputs = proc(images=img, return_tensors="pt").to(_DEVICE)
    outputs = model(**inputs)
    feat = outputs.last_hidden_state[:, 0, :]  # CLS token
    feat = F.normalize(feat, dim=-1).squeeze(0).cpu()

    if cache_key is not None:
        _BYTES_EMBED_CACHE[cache_key] = feat
    return feat


def cosine(a: torch.Tensor, b: torch.Tensor) -> float:
    return float(torch.dot(a, b).item())


def max_similarity(query: torch.Tensor, gallery: list[torch.Tensor]) -> tuple[float, int]:
    if not gallery:
        return (0.0, -1)
    sims = [cosine(query, g) for g in gallery]
    idx = max(range(len(sims)), key=lambda i: sims[i])
    return sims[idx], idx


def device() -> str:
    return _DEVICE
