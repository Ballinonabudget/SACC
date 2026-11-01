"""Small persistence and path helpers; no environment-file or network access."""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import tempfile


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def token(*parts):
    return hashlib.sha256(canonical(parts).encode()).hexdigest()


def file_hash(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def safe_member(name):
    p = PurePosixPath(name)
    if (not name or p.is_absolute() or ".." in p.parts or "\\" in name
            or "\x00" in name or any(ord(c) < 32 for c in name)):
        raise ValueError("Unsafe archive member path")
    return p


def no_symlinks(path):
    path = Path(path).absolute()
    for p in (path, *path.parents):
        if p.is_symlink():
            raise ValueError("Symlink in output path")
    return path


def private_root(path, sources=()):
    path = no_symlinks(Path(path).expanduser()).resolve()
    repo = Path(__file__).resolve().parents[1]
    forbidden = [repo, *(Path(s).resolve().parent for s in sources)]
    for name in ("SACC_INBOX", "SACC_ROOT"):
        if os.getenv(name):
            forbidden.append(Path(os.environ[name]).expanduser().resolve())
    if any(path == p or path.is_relative_to(p) for p in forbidden):
        raise ValueError("Recovery output must be outside source, repo, and watched trees")
    if any(p.lower() in {"inbox", "ingestion_zone", "cloudstorage", "mobile documents"} for p in path.parts):
        raise ValueError("Recovery output cannot be a watched or cloud-synced directory")
    if path.is_relative_to(Path("/Volumes")):
        raise ValueError("This milestone requires a local private output directory")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)
    return path


def child(root, *parts):
    root = Path(root).resolve()
    path = no_symlinks(root.joinpath(*parts))
    if not path.resolve().is_relative_to(root):
        raise ValueError("Output escaped private root")
    return path


def atomic_text(path, value):
    path = no_symlinks(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(prefix=".writing-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


@contextmanager
def run_lock(root):
    path = child(root, ".recovery.lock")
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("Another recovery command owns this output directory") from exc
        yield
    finally:
        os.close(fd)
