"""Command-line entry point for the SACC multi-modal PoC."""

from __future__ import annotations

import argparse
import asyncio
import json
import os

from .database import MultimodalDB
from .ingestion import IngestionService
from .storage import LocalStorageAdapter, NASStorageAdapter
from .transcode import ProxyConfig


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SACC multi-modal ingestion/search PoC")
    parser.add_argument("--db", default=os.getenv("SACC_POC_DB", ""))
    sub = parser.add_subparsers(dest="command", required=True)

    search = sub.add_parser("search")
    search.add_argument("q", nargs="?", default="")
    search.add_argument("--media-type", action="append", choices=["video", "image"])
    search.add_argument("--limit", type=int, default=30)
    search.add_argument("--offset", type=int, default=0)

    ingest = sub.add_parser("ingest")
    ingest.add_argument("--backend", choices=["local", "nas"], default="local")
    ingest.add_argument("--root", default="")
    ingest.add_argument("--prefix", default="")
    ingest.add_argument("--limit", type=int, default=0)
    ingest.add_argument("--height", type=int, choices=[720, 1080], default=720)
    ingest.add_argument("--non-recursive", action="store_true")
    ingest.add_argument("--prepared", action="store_true", help="Use existing proxies without transcoding; size limits still apply")

    sub.add_parser("init-db")
    sub.add_parser("health")
    return parser


async def _ingest(args, db: MultimodalDB) -> dict:
    adapter = (
        LocalStorageAdapter(args.root or None)
        if args.backend == "local"
        else NASStorageAdapter(args.root or None)
    )
    service = IngestionService(
        adapter,
        db,
        proxy_config=ProxyConfig.from_env(target_height=args.height),
    )
    return await service.ingest(
        prefix=args.prefix,
        recursive=not args.non_recursive,
        limit=args.limit,
        prepared=args.prepared,
        progress=lambda event: print(json.dumps(event, sort_keys=True)),
    )


def main() -> None:
    args = _parser().parse_args()
    db = MultimodalDB(args.db or None)
    if args.command == "init-db":
        print(json.dumps({"ok": True, "database": str(db.path)}))
    elif args.command == "health":
        print(json.dumps({"database": str(db.path), "integrity": "ok"}))
    elif args.command == "search":
        print(json.dumps(
            db.search(args.q, args.media_type, args.limit, args.offset),
            indent=2,
        ))
    elif args.command == "ingest":
        print(json.dumps(asyncio.run(_ingest(args, db)), indent=2))


if __name__ == "__main__":
    main()
