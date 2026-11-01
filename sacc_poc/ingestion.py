"""Whole-asset ingestion orchestration for the multi-modal PoC."""

from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path
from typing import Callable, Optional

from .database import MultimodalDB
from .catalog import enrich_catalog
from .gemini import GeminiDispatcher, ShoeIdentification
from .storage import StorageAdapter, StoredAsset
from .transcode import AsyncFFmpegTranscoder, ProxyConfig, ensure_dispatchable


ProgressCallback = Callable[[dict], None]


def _asset_token(asset: StoredAsset) -> str:
    digest = hashlib.sha256(
        f"{asset.physical_path.resolve()}:{asset.physical_path.stat().st_size}:"
        f"{asset.physical_path.stat().st_mtime_ns}".encode("utf-8")
    ).hexdigest()[:12]
    safe_stem = "".join(c if c.isalnum() or c in "-_" else "-" for c in asset.physical_path.stem)
    return f"{digest}_{safe_stem[:80]}"


class IngestionService:
    def __init__(
        self,
        storage: StorageAdapter,
        database: MultimodalDB,
        dispatcher: Optional[GeminiDispatcher] = None,
        proxy_root: Optional[str] = None,
        proxy_config: Optional[ProxyConfig] = None,
    ):
        self.storage = storage
        self.database = database
        self.proxy_root = Path(
            proxy_root
            or os.getenv("SACC_PROXY_ROOT", "")
            or (Path(__file__).resolve().parent.parent / "var" / "proxies")
        ).expanduser().resolve()
        self.proxy_config = proxy_config or ProxyConfig.from_env()
        self.transcoder = AsyncFFmpegTranscoder(self.proxy_config)
        self.dispatcher = dispatcher or GeminiDispatcher(
            max_dispatch_bytes=self.proxy_config.max_dispatch_bytes
        )
        self.dispatch_slots = asyncio.Semaphore(
            max(1, int(os.getenv("SACC_GEMINI_CONCURRENCY", "3")))
        )
        self.worker_count = max(1, int(os.getenv("SACC_INGEST_CONCURRENCY", "4")))

    async def ingest(
        self,
        prefix: str = "",
        recursive: bool = True,
        limit: int = 0,
        progress: Optional[ProgressCallback] = None,
        prepared: bool = False,
    ) -> dict:
        assets = list(self.storage.iter_media(prefix=prefix, recursive=recursive, limit=limit))
        summary = {"discovered": len(assets), "indexed": 0, "review": 0, "skipped": 0, "failed": 0, "errors": []}
        lock = asyncio.Lock()

        async def emit(event: dict) -> None:
            if progress:
                progress(event)

        async def process(asset: StoredAsset) -> None:
            token = _asset_token(asset)
            try:
                is_prepared = prepared or any(
                    part.lower().replace('_', ' ') in ('compress files', 'compressed files')
                    for part in asset.physical_path.parts
                )
                if asset.media_type == "video" and is_prepared:
                    dispatch_path = asset.physical_path
                    ensure_dispatchable(dispatch_path, self.proxy_config.max_dispatch_bytes)
                    proxy = {
                        "path": str(dispatch_path),
                        "size_bytes": dispatch_path.stat().st_size,
                        "resolution": await self.transcoder.resolution(dispatch_path),
                        "mime_type": asset.mime_type,
                    }
                    await emit({"status": "using_existing_proxy", "asset": asset.logical_key})
                elif asset.media_type == "video":
                    dispatch_path = self.proxy_root / f"{token}.mp4"
                    if not dispatch_path.is_file():
                        proxy = await self.transcoder.transcode(asset.physical_path, dispatch_path)
                    else:
                        ensure_dispatchable(dispatch_path, self.proxy_config.max_dispatch_bytes)
                        proxy = {
                            "path": str(dispatch_path),
                            "size_bytes": dispatch_path.stat().st_size,
                            "resolution": await self.transcoder.resolution(dispatch_path),
                            "mime_type": "video/mp4",
                        }
                else:
                    dispatch_path = asset.physical_path
                    ensure_dispatchable(dispatch_path, self.proxy_config.max_dispatch_bytes)
                    proxy = {
                        "path": str(dispatch_path),
                        "size_bytes": dispatch_path.stat().st_size,
                        "resolution": "",
                        "mime_type": asset.mime_type,
                    }

                existing = self.database.find_asset_by_path(str(dispatch_path))
                if existing and existing['file_size_bytes'] == proxy['size_bytes']:
                    summary['skipped'] += 1
                    await emit({'status': 'already_indexed', 'asset': asset.logical_key})
                    return
                await emit({"status": "identifying", "asset": asset.logical_key})
                async with self.dispatch_slots:
                    identified = await self.dispatcher.identify_async(dispatch_path, proxy["mime_type"])
                needs_review = identified.needs_review
                sku = identified.sku or f"UNRESOLVED-{token.upper()}"
                shoe_id = self.database.upsert_shoe(
                    sku, identified.model, identified.colorway, identified.brand
                )
                catalog = await asyncio.to_thread(enrich_catalog, sku)
                self.database.set_catalog(shoe_id, catalog)
                asset_id = self.database.add_media_asset(
                    shoe_id=shoe_id,
                    media_type=asset.media_type,
                    file_path=str(dispatch_path),
                    resolution=proxy["resolution"],
                    mime_type=proxy["mime_type"],
                    is_primary=True,
                    storage_backend=asset.storage_backend,
                    storage_key=asset.logical_key,
                    source_path=str(asset.physical_path),
                    file_size_bytes=proxy["size_bytes"],
                    confidence=identified.confidence,
                    needs_review=needs_review,
                    review_reason=identified.review_reason,
                )
                async with lock:
                    summary["indexed"] += 1
                    if needs_review:
                        summary["review"] += 1
                await emit({
                    "status": "indexed",
                    "asset": asset.logical_key,
                    "asset_id": asset_id,
                    "sku": sku,
                    "needs_review": needs_review,
                })
            except Exception as exc:
                async with lock:
                    summary["failed"] += 1
                    summary["errors"].append({"asset": asset.logical_key, "error": str(exc)})
                await emit({"status": "failed", "asset": asset.logical_key, "error": str(exc)})

        queue: asyncio.Queue[StoredAsset] = asyncio.Queue()
        for asset in assets:
            queue.put_nowait(asset)

        async def worker() -> None:
            while True:
                try:
                    asset = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                try:
                    await process(asset)
                finally:
                    queue.task_done()

        workers = min(self.worker_count, len(assets))
        if workers:
            await asyncio.gather(*(worker() for _ in range(workers)))
        return summary


class StaticDispatcher:
    """Deterministic dispatcher for local smoke tests and UI demos."""

    def __init__(self, result: ShoeIdentification):
        self.result = result

    async def identify_async(self, path: Path, mime_type: Optional[str] = None) -> ShoeIdentification:
        return self.result
