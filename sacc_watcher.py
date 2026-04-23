"""
sacc_watcher.py — SACC Folder-Watch Daemon
============================================
Watches /Volumes/Team Bank 12/SACC/Inbox/ for new video files dropped
after FCP consolidation. When files appear and settle (no new writes for
SETTLE_SECS), triggers the full sacc_pipeline automatically.

Synology folder structure created automatically:
  /Volumes/Team Bank 12/SACC/
  ├── Inbox/                ← ← ← FCP drops consolidated files here
  ├── 2025/
  │   ├── 250111/
  │   │   ├── FLM-MALL_250111_Air-Jordan-1-Chicago_iPhone15ProMax_raw.mov
  │   │   ├── Compressed_Files/
  │   │   │   └── FLM-MALL_250111_..._Gemini_API.mp4
  │   │   ├── Processed_RAW/
  │   │   └── json/
  │   │       └── 555088-101_Air_Jordan_1_Retro_High_OG_Chicago.json
  │   └── 250323/
  └── 2024/
      └── ...

Usage (manual):
  python sacc_watcher.py --loc FLM --id "Air Jordan 1 Chicago"

Usage (launchd — auto on login):
  Install com.sacc.watcher.plist to ~/Library/LaunchAgents/
  launchctl load ~/Library/LaunchAgents/com.sacc.watcher.plist

Requirements:
  pip install watchdog --break-system-packages
"""

import os
import sys
import time
import logging
import argparse
import threading
from pathlib import Path
from datetime import datetime

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
except ImportError:
    print("[ERROR] watchdog not installed. Run:")
    print("  pip install watchdog --break-system-packages")
    sys.exit(1)

_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _DIR)

from sacc_pipeline import run_pipeline, SYNOLOGY_ROOT, INBOX_PATH, VIDEO_EXTS

# ── Config ────────────────────────────────────────────────────────────────────
SETTLE_SECS  = 30     # seconds of quiet after last file event before triggering pipeline
LOG_PATH     = os.path.join(_DIR, "sacc_watcher.log")
POLL_INTERVAL = 2     # watchdog observer poll interval (seconds)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH),
        logging.StreamHandler(sys.stdout),
    ]
)
log = logging.getLogger("sacc_watcher")


# ── Event handler ─────────────────────────────────────────────────────────────

class InboxHandler(FileSystemEventHandler):
    """
    Watches Inbox for new video files. Uses a settle timer so a batch of
    files dropped at once triggers only a single pipeline run.
    """

    def __init__(self, inbox, root, loc_code, identifier, settle_secs=SETTLE_SECS):
        super().__init__()
        self.inbox       = inbox
        self.root        = root
        self.loc_code    = loc_code
        self.identifier  = identifier
        self.settle_secs = settle_secs
        self._timer      = None
        self._lock       = threading.Lock()

    def _is_video(self, path):
        return Path(path).suffix.lower() in VIDEO_EXTS and not os.path.basename(path).startswith('.')

    def on_created(self, event):
        if not event.is_directory and self._is_video(event.src_path):
            log.info(f"New file detected: {os.path.basename(event.src_path)}")
            self._reset_timer()

    def on_moved(self, event):
        if not event.is_directory and self._is_video(event.dest_path):
            log.info(f"File moved in: {os.path.basename(event.dest_path)}")
            self._reset_timer()

    def on_modified(self, event):
        if not event.is_directory and self._is_video(event.src_path):
            self._reset_timer()

    def _reset_timer(self):
        """Cancel any pending trigger and start a fresh settle countdown."""
        with self._lock:
            if self._timer:
                self._timer.cancel()
            self._timer = threading.Timer(self.settle_secs, self._trigger)
            self._timer.daemon = True
            self._timer.start()
            log.info(f"Settle timer reset — pipeline fires in {self.settle_secs}s if no new files")

    def _trigger(self):
        """Called after settle window — fires the pipeline."""
        log.info("=" * 50)
        log.info("Settle window closed — starting SACC pipeline")
        log.info("=" * 50)
        try:
            run_pipeline(
                inbox      = self.inbox,
                root       = self.root,
                loc_code   = self.loc_code,
                identifier = self.identifier,
            )
        except Exception as e:
            log.error(f"Pipeline error: {e}", exc_info=True)


# ── Watcher entry point ───────────────────────────────────────────────────────

def run_watcher(inbox, root, loc_code, identifier):
    os.makedirs(inbox, exist_ok=True)
    log.info(f"SACC Watcher started")
    log.info(f"  Watching : {inbox}")
    log.info(f"  Root     : {root}")
    log.info(f"  Location : {loc_code}")
    log.info(f"  ID       : {identifier}")
    log.info(f"  Settle   : {SETTLE_SECS}s")

    handler  = InboxHandler(inbox, root, loc_code, identifier)
    observer = Observer(timeout=POLL_INTERVAL)
    observer.schedule(handler, path=inbox, recursive=False)
    observer.start()

    try:
        while True:
            time.sleep(5)
            if not observer.is_alive():
                log.warning("Observer died — restarting")
                observer = Observer(timeout=POLL_INTERVAL)
                observer.schedule(handler, path=inbox, recursive=False)
                observer.start()
    except KeyboardInterrupt:
        log.info("Keyboard interrupt — stopping watcher")
    finally:
        observer.stop()
        observer.join()
        log.info("SACC Watcher stopped")


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SACC Folder-Watch Daemon")
    parser.add_argument("--inbox",  default=INBOX_PATH,    help="Inbox folder to watch")
    parser.add_argument("--root",   default=SYNOLOGY_ROOT, help="SACC root on Synology")
    parser.add_argument("--loc",    default="FLM",         help="Location code")
    parser.add_argument("--id",     required=True,         help="Shoe identifier string")
    parser.add_argument("--settle", type=int, default=SETTLE_SECS,
                        help="Seconds of quiet before pipeline triggers")
    args = parser.parse_args()

    run_watcher(
        inbox      = args.inbox,
        root       = args.root,
        loc_code   = args.loc,
        identifier = args.id,
    )
