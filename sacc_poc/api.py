"""FastAPI router for SACC multi-modal ingestion and search."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .database import MultimodalDB
from .ingestion import IngestionService
from .storage import LocalStorageAdapter, NASStorageAdapter, adapter_from_env
from .transcode import ProxyConfig


router = APIRouter(prefix="/api/v1", tags=["multi-modal-poc"])
_db = MultimodalDB()
_jobs: dict[str, dict] = {}
_tasks: dict[str, asyncio.Task] = {}


class IngestBody(BaseModel):
    backend: Literal["local", "nas"] = "local"
    prefix: str = ""
    recursive: bool = True
    limit: int = Field(default=0, ge=0, le=10000)
    target_height: Literal[720, 1080] = 720
    prepared: bool = False


@router.get("/health")
def poc_health():
    return {
        "status": "ok",
        "database": str(_db.path),
        "storage": {
            "local": LocalStorageAdapter().describe(),
            "nas": NASStorageAdapter().describe(),
        },
    }


@router.get("/search")
def search(
    q: str = Query(default=""),
    media_types: list[str] = Query(default=["video", "image"]),
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    try:
        return _db.search(q, media_types=media_types, limit=limit, offset=offset)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/assets/{asset_id}")
def asset_file(asset_id: int):
    asset = _db.get_asset(asset_id)
    if not asset:
        raise HTTPException(404, f"asset not found: {asset_id}")
    path = Path(asset["file_path"]).expanduser().resolve()
    if not path.is_file():
        raise HTTPException(404, f"asset file is unavailable: {asset_id}")
    return FileResponse(
        str(path),
        media_type=asset["mime_type"],
        filename=path.name,
        content_disposition_type="inline",
    )


@router.get("/review")
def review_queue(limit: int = Query(default=100, ge=1, le=500)):
    rows = _db.review_queue(limit=limit)
    return {"count": len(rows), "results": rows}


async def _run_ingest(job_id: str, body: IngestBody) -> None:
    job = _jobs[job_id]
    job["status"] = "running"
    _db.save_ingest_job(job)

    def progress(event: dict) -> None:
        job["events"].append(event)
        if len(job["events"]) > 200:
            del job["events"][:-200]
        _db.save_ingest_job(job)

    try:
        adapter = adapter_from_env(body.backend)
        config = ProxyConfig.from_env(target_height=body.target_height)
        service = IngestionService(adapter, _db, proxy_config=config)
        job["result"] = await service.ingest(
            prefix=body.prefix,
            recursive=body.recursive,
            limit=body.limit,
            prepared=body.prepared,
            progress=progress,
        )
        job["status"] = "complete"
        _db.save_ingest_job(job)
    except Exception as exc:
        job["status"] = "failed"
        job["error"] = str(exc)
        _db.save_ingest_job(job)


@router.post("/ingest", status_code=202)
async def start_ingest(body: IngestBody):
    job_id = str(uuid.uuid4())
    _jobs[job_id] = {
        "id": job_id,
        "status": "queued",
        "request": body.model_dump(),
        "events": [],
        "result": None,
        "error": "",
    }
    _db.save_ingest_job(_jobs[job_id])
    task = asyncio.create_task(_run_ingest(job_id, body))
    _tasks[job_id] = task
    task.add_done_callback(lambda _task: _tasks.pop(job_id, None))
    return {"job_id": job_id, "status": "queued"}


@router.get("/ingest/{job_id}")
def ingest_status(job_id: str):
    job = _jobs.get(job_id) or _db.get_ingest_job(job_id)
    if not job:
        raise HTTPException(404, f"ingest job not found: {job_id}")
    return job
