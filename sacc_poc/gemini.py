"""Strict single-entity identification through the Google Gen AI SDK.

The dispatcher uses Vertex AI when a Google Cloud project is configured and
falls back to the Gemini Developer API only when an API key is provided.
"""

from __future__ import annotations

import asyncio
import json
import mimetypes
import os
import random
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from .transcode import ensure_dispatchable

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass


IDENTIFICATION_SCHEMA = {
    "type": "object",
    "properties": {
        "sku": {"type": "string"},
        "model": {"type": "string"},
        "colorway": {"type": "string"},
        "brand": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["sku", "model", "colorway", "brand", "confidence"],
    "additionalProperties": False,
}

SYSTEM_INSTRUCTION = """
You are SACC's sneaker cataloging specialist. Treat the supplied media file as
one discrete asset containing one primary shoe entity. Identify only that
primary shoe. Prefer a SKU visibly printed on a label; never invent a SKU.
Use canonical model, colorway, and brand names when supported by the media.
Confidence measures exact SKU confidence, not general shoe visibility. Use 1.0
only when the SKU is directly readable and unambiguous. Return no commentary.
Do not perform temporal segmentation and do not return timestamps.
""".strip()


class IdentificationError(RuntimeError):
    pass


@dataclass(frozen=True)
class ShoeIdentification:
    sku: str
    model: str
    colorway: str
    brand: str
    confidence: float
    forced_review_reason: str = ""

    @classmethod
    def parse(cls, raw: object) -> "ShoeIdentification":
        if isinstance(raw, str):
            raw = json.loads(raw)
        if not isinstance(raw, dict):
            raise IdentificationError("Gemini returned a non-object response")
        required = set(IDENTIFICATION_SCHEMA["required"])
        if set(raw) != required:
            missing = sorted(required - set(raw))
            extra = sorted(set(raw) - required)
            raise IdentificationError(f"schema mismatch; missing={missing}, extra={extra}")
        try:
            confidence = float(raw["confidence"])
        except (TypeError, ValueError) as exc:
            raise IdentificationError("confidence must be numeric") from exc
        if not 0.0 <= confidence <= 1.0:
            raise IdentificationError("confidence must be between 0.0 and 1.0")
        return cls(
            sku=str(raw["sku"] or "").strip().upper(),
            model=str(raw["model"] or "").strip(),
            colorway=str(raw["colorway"] or "").strip(),
            brand=str(raw["brand"] or "").strip(),
            confidence=confidence,
        )

    @property
    def needs_review(self) -> bool:
        return self.confidence < 1.0 or not self.sku or bool(self.forced_review_reason)

    @property
    def review_reason(self) -> str:
        if self.forced_review_reason:
            return self.forced_review_reason
        if not self.sku:
            return "sku_unreadable"
        if self.confidence < 1.0:
            return "sku_confidence_below_1.0"
        return ""

    def to_dict(self) -> dict:
        return {
            **asdict(self),
            "needs_review": self.needs_review,
            "review_reason": self.review_reason,
        }


class GeminiDispatcher:
    def __init__(
        self,
        model: Optional[str] = None,
        max_dispatch_bytes: Optional[int] = None,
        attempts: int = 3,
    ):
        self.model = model or os.getenv("SACC_GEMINI_MODEL", "gemini-3.8-flash")
        configured_fallbacks = os.getenv(
            "SACC_GEMINI_FALLBACK_MODELS", "gemini-3.5-flash-lite"
        )
        self.models = list(dict.fromkeys([
            self.model,
            *(item.strip() for item in configured_fallbacks.split(",") if item.strip()),
        ]))
        self.max_dispatch_bytes = max_dispatch_bytes or int(
            float(os.getenv("SACC_MAX_DISPATCH_MB", "64")) * 1024 * 1024
        )
        self.attempts = max(1, attempts)
        self.project = os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("VERTEX_PROJECT_ID")
        self.location = os.getenv("GOOGLE_CLOUD_LOCATION") or os.getenv("VERTEX_LOCATION", "global")
        self.api_key = os.getenv("GEMINI_API_KEY", "")
        self.remote_api_enabled = os.getenv(
            "SACC_REMOTE_API_ENABLED", "false"
        ).strip().lower() in {"1", "true", "yes", "on"}
        self._client = None

    def _client_instance(self):
        if self._client is not None:
            return self._client
        if not self.remote_api_enabled:
            raise IdentificationError(
                "remote API access is locked; verify the SACC credential and set "
                "SACC_REMOTE_API_ENABLED=true"
            )
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise IdentificationError(
                "google-genai is not installed; run pip install -r requirements-poc.txt"
            ) from exc
        http = types.HttpOptions(api_version="v1")
        if self.project:
            self._client = genai.Client(
                vertexai=True,
                project=self.project,
                location=self.location,
                http_options=http,
            )
        elif self.api_key:
            self._client = genai.Client(api_key=self.api_key, http_options=http)
        else:
            raise IdentificationError(
                "set GOOGLE_CLOUD_PROJECT for Vertex AI or GEMINI_API_KEY for the Gemini API"
            )
        return self._client

    def identify(self, path: Path, mime_type: Optional[str] = None) -> ShoeIdentification:
        path = path.resolve()
        ensure_dispatchable(path, self.max_dispatch_bytes)
        resolved_mime = mime_type or mimetypes.guess_type(path.name)[0] or "video/mp4"
        client = self._client_instance()
        from google.genai import types

        media = types.Part.from_bytes(data=path.read_bytes(), mime_type=resolved_mime)
        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            response_mime_type="application/json",
            response_json_schema=IDENTIFICATION_SCHEMA,
        )
        last_error = None
        for model in self.models:
            for attempt in range(self.attempts):
                try:
                    response = client.models.generate_content(
                        model=model,
                        contents=[
                            media,
                            "Identify the primary shoe entity in this complete media asset.",
                        ],
                        config=config,
                    )
                    payload = response.parsed if isinstance(response.parsed, dict) else response.text
                    result = ShoeIdentification.parse(payload)
                    if result.confidence == 1.0 and result.sku and len(self.models) > 1:
                        validator_model = next(item for item in self.models if item != model)
                        try:
                            validation = client.models.generate_content(
                                model=validator_model,
                                contents=[
                                    media,
                                    "Independently identify and verify the exact SKU. Set confidence "
                                    "to 1.0 only if the SKU text is directly readable in the asset.",
                                ],
                                config=config,
                            )
                            validation_payload = (
                                validation.parsed
                                if isinstance(validation.parsed, dict)
                                else validation.text
                            )
                            checked = ShoeIdentification.parse(validation_payload)
                            if checked.sku != result.sku:
                                return ShoeIdentification(**{
                                    **asdict(result),
                                    "forced_review_reason": (
                                        "secondary_model_disagreement:"
                                        f"{checked.sku or 'unreadable'}"
                                    ),
                                })
                            if checked.confidence < 1.0:
                                return ShoeIdentification(**{
                                    **asdict(result),
                                    "forced_review_reason": "secondary_confidence_below_1.0",
                                })
                        except Exception:
                            return ShoeIdentification(**{
                                **asdict(result),
                                "forced_review_reason": "secondary_validation_unavailable",
                            })
                    return result
                except Exception as exc:
                    last_error = exc
                    status = getattr(exc, "code", None)
                    message = str(exc).lower()
                    retryable = status in {429, 500, 502, 503, 504} or any(
                        token in message
                        for token in ("high demand", "unavailable", "rate limit", "timeout")
                    )
                    if not retryable:
                        raise IdentificationError(
                            f"Gemini identification failed with {model}: {exc}"
                        ) from exc
                    if attempt + 1 < self.attempts:
                        time.sleep(min(30.0, (2 ** attempt) + random.random()))
        raise IdentificationError(f"Gemini identification failed: {last_error}")

    async def identify_async(self, path: Path, mime_type: Optional[str] = None) -> ShoeIdentification:
        return await asyncio.to_thread(self.identify, path, mime_type)
