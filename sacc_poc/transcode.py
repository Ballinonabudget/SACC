"""Asynchronous FFmpeg proxy generation with dispatch-size guardrails."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional


class MediaGuardrailError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProxyConfig:
    target_height: int = 720
    crf: int = 23
    max_video_bitrate: str = "4M"
    audio_bitrate: str = "96k"
    max_dispatch_bytes: int = 64 * 1024 * 1024
    concurrency: int = 2
    timeout_seconds: int = 1800

    @classmethod
    def from_env(cls, target_height: Optional[int] = None) -> "ProxyConfig":
        height = target_height or int(os.getenv("SACC_PROXY_HEIGHT", "720"))
        if height not in (720, 1080):
            raise ValueError("target height must be 720 or 1080")
        return cls(
            target_height=height,
            crf=int(os.getenv("SACC_PROXY_CRF", "23")),
            max_video_bitrate=os.getenv("SACC_PROXY_MAX_BITRATE", "4M"),
            audio_bitrate=os.getenv("SACC_PROXY_AUDIO_BITRATE", "96k"),
            max_dispatch_bytes=int(float(os.getenv("SACC_MAX_DISPATCH_MB", "64")) * 1024 * 1024),
            concurrency=max(1, int(os.getenv("SACC_TRANSCODE_CONCURRENCY", "2"))),
            timeout_seconds=max(60, int(os.getenv("SACC_TRANSCODE_TIMEOUT", "1800"))),
        )


def ensure_dispatchable(path: Path, max_bytes: int) -> None:
    size = path.stat().st_size
    if size <= 0:
        raise MediaGuardrailError(f"empty media asset: {path}")
    if size > max_bytes:
        raise MediaGuardrailError(
            f"proxy is {size / 1024 / 1024:.1f} MB; dispatch limit is "
            f"{max_bytes / 1024 / 1024:.1f} MB"
        )


class AsyncFFmpegTranscoder:
    def __init__(self, config: Optional[ProxyConfig] = None):
        self.config = config or ProxyConfig.from_env()
        self.ffmpeg = os.getenv("SACC_FFMPEG", "") or shutil.which("ffmpeg") or "ffmpeg"
        self.ffprobe = os.getenv("SACC_FFPROBE", "") or shutil.which("ffprobe") or "ffprobe"
        self._semaphore = asyncio.Semaphore(self.config.concurrency)

    def command(self, source: Path, destination: Path) -> list[str]:
        c = self.config
        scale = f"scale=-2:'min({c.target_height},ih)'"
        return [
            self.ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel", "error",
            "-fflags", "+genpts",
            "-i", str(source),
            "-map", "0:v:0",
            "-map", "0:a?",
            "-vf", scale,
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", str(c.crf),
            "-maxrate", c.max_video_bitrate,
            "-bufsize", c.max_video_bitrate,
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", c.audio_bitrate,
            "-ac", "1",
            "-movflags", "+faststart",
            str(destination),
        ]

    async def transcode(self, source: Path, destination: Path) -> dict:
        source = source.resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        async with self._semaphore:
            proc = await asyncio.create_subprocess_exec(
                *self.command(source, destination),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                _, stderr = await asyncio.wait_for(proc.communicate(), self.config.timeout_seconds)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                destination.unlink(missing_ok=True)
                raise RuntimeError(f"FFmpeg timed out after {self.config.timeout_seconds}s: {source}")
            if proc.returncode != 0:
                destination.unlink(missing_ok=True)
                detail = stderr.decode("utf-8", errors="replace")[-2000:]
                raise RuntimeError(f"FFmpeg failed for {source.name}: {detail}")
        ensure_dispatchable(destination, self.config.max_dispatch_bytes)
        return {
            "path": str(destination),
            "size_bytes": destination.stat().st_size,
            "resolution": await self.resolution(destination),
            "mime_type": "video/mp4",
        }

    async def resolution(self, path: Path) -> str:
        proc = await asyncio.create_subprocess_exec(
            self.ffprobe,
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "json",
            str(path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await proc.communicate()
        try:
            stream = json.loads(stdout).get("streams", [])[0]
            return f"{int(stream['width'])}x{int(stream['height'])}"
        except (ValueError, KeyError, IndexError, TypeError):
            return ""

    async def transcode_many(self, jobs: Iterable[tuple[Path, Path]]) -> list:
        return await asyncio.gather(
            *(self.transcode(source, destination) for source, destination in jobs),
            return_exceptions=True,
        )
