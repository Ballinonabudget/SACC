"""Environment-agnostic storage adapters for SACC ingestion.

Adapters expose logical keys to the ingestion pipeline while keeping physical
mount paths at the edge. A local DAS and a mounted SMB/NFS share therefore use
the same pipeline code.
"""

from __future__ import annotations

import mimetypes
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional
from sacc_takeout.library_paths import unprotected_path


MEDIA_TYPES = {
    ".mov": "video",
    ".mp4": "video",
    ".m4v": "video",
    ".mts": "video",
    ".avi": "video",
    ".jpg": "image",
    ".jpeg": "image",
    ".png": "image",
    ".webp": "image",
    ".heic": "image",
}


@dataclass(frozen=True)
class StoredAsset:
    storage_backend: str
    logical_key: str
    physical_path: Path
    media_type: str
    mime_type: str
    size_bytes: int


class StorageAdapter(ABC):
    """Translate logical asset keys into files under one configured root."""

    def __init__(self, root: str, name: str):
        self.root = Path(root).expanduser().resolve()
        self.name = name

    def resolve(self, logical_key: str = "") -> Path:
        candidate = (self.root / logical_key).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise ValueError(f"storage key escapes configured root: {logical_key}") from exc
        return candidate

    def logical_key(self, physical_path: Path) -> str:
        path = physical_path.expanduser().resolve()
        try:
            return path.relative_to(self.root).as_posix()
        except ValueError as exc:
            raise ValueError(f"path is outside configured storage root: {path}") from exc

    def iter_media(
        self,
        prefix: str = "",
        recursive: bool = True,
        limit: int = 0,
    ) -> Iterator[StoredAsset]:
        base = unprotected_path(self.resolve(prefix))
        if not base.exists():
            raise FileNotFoundError(f"storage path not found: {base}")
        paths = [base] if base.is_file() else (base.rglob("*") if recursive else base.glob("*"))
        yielded = 0
        for path in sorted(paths):
            if not path.is_file() or path.name.startswith("."):
                continue
            media_type = MEDIA_TYPES.get(path.suffix.lower())
            if not media_type:
                continue
            unprotected_path(path)
            mime_type = mimetypes.guess_type(path.name)[0]
            if not mime_type:
                mime_type = "video/mp4" if media_type == "video" else "image/jpeg"
            yield StoredAsset(
                storage_backend=self.name,
                logical_key=self.logical_key(path),
                physical_path=path,
                media_type=media_type,
                mime_type=mime_type,
                size_bytes=path.stat().st_size,
            )
            yielded += 1
            if limit and yielded >= limit:
                return

    @abstractmethod
    def describe(self) -> dict:
        raise NotImplementedError


class LocalStorageAdapter(StorageAdapter):
    def __init__(self, root: Optional[str] = None):
        super().__init__(
            root or os.getenv("SACC_LOCAL_STAGING", "/Volumes/External_Drive/staging"),
            "local",
        )

    def describe(self) -> dict:
        return {"backend": self.name, "root": str(self.root), "mounted": self.root.is_dir()}


class NASStorageAdapter(StorageAdapter):
    """Adapter for an SMB/NFS share after macOS mounts it as a local volume."""

    def __init__(self, root: Optional[str] = None, protocol: Optional[str] = None):
        self.protocol = protocol or os.getenv("SACC_NAS_PROTOCOL", "smb")
        super().__init__(
            root or os.getenv("SACC_NAS_ROOT", "/Volumes/The Final Cut X"),
            "nas",
        )

    def describe(self) -> dict:
        return {
            "backend": self.name,
            "protocol": self.protocol,
            "root": str(self.root),
            "mounted": self.root.is_dir(),
        }


def adapter_from_env(backend: Optional[str] = None) -> StorageAdapter:
    selected = (backend or os.getenv("SACC_STORAGE_BACKEND", "local")).strip().lower()
    if selected == "local":
        return LocalStorageAdapter()
    if selected == "nas":
        return NASStorageAdapter()
    raise ValueError(f"unsupported storage backend: {selected}")
