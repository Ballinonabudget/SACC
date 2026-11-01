"""Extract video capture date from MP4/MOV metadata via ffmpeg."""
from __future__ import annotations

import re
import subprocess
from datetime import date, datetime, timedelta
from pathlib import Path

import imageio_ffmpeg

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()

_DATE_KEYS = (
    "com.apple.quicktime.creationdate",
    "creation_time",
    "date",
)


def video_capture_date(video_path: str) -> str | None:
    """Return YYYY-MM-DD string of video capture, or None if unavailable."""
    try:
        proc = subprocess.run(
            [FFMPEG, "-i", str(video_path), "-hide_banner"],
            capture_output=True, text=True, timeout=15,
        )
    except Exception:
        return None

    for line in proc.stderr.splitlines():
        s = line.strip()
        low = s.lower()
        for key in _DATE_KEYS:
            if low.startswith(key):
                # "  com.apple.quicktime.creationdate: 2023-04-15T12:34:56-0400"
                _, _, val = s.partition(":")
                val = val.strip()
                # ffmpeg may put a colon inside the timestamp — so partition again
                # if val starts with a number followed by ':' it's the time, not the key
                # Easier: extract via regex
                m = re.search(r"\d{4}-\d{2}-\d{2}", s)
                if m:
                    return m.group(0)
    return None


def parse_release_date(s: str | None) -> date | None:
    """Parse a date string in any of YYYY-MM-DD, YYYY/MM/DD, or YYYY format."""
    if not s:
        return None
    s = s.strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m", "%Y"):
        try:
            return datetime.strptime(s[: len(fmt.replace("%Y", "0000")
                                              .replace("%m", "00")
                                              .replace("%d", "00"))], fmt).date()
        except Exception:
            continue
    # Last-ditch: regex out a year
    m = re.match(r"(\d{4})", s)
    if m:
        try:
            return date(int(m.group(1)), 1, 1)
        except Exception:
            return None
    return None


def is_plausible(product_release_date: str | None,
                 video_capture_date_str: str | None,
                 max_years_after: float = 0.0,
                 max_years_before: float | None = None) -> bool:
    """
    Filter rule: a product release is plausible for a video iff:
      - product_release_date is unknown (allow), OR
      - product_release_date <= video_date + small grace, AND
      - if max_years_before set: product_release_date >= video_date - max_years_before

    With max_years_after=0: products released AFTER the video is shot are excluded.
    With max_years_before=None: no lower bound (older shoes still allowed).
    """
    rd = parse_release_date(product_release_date)
    vd = parse_release_date(video_capture_date_str)
    if rd is None or vd is None:
        return True
    upper_bound = vd + timedelta(days=int(max_years_after * 365))
    if rd > upper_bound:
        return False
    if max_years_before is not None:
        lower_bound = vd - timedelta(days=int(max_years_before * 365))
        if rd < lower_bound:
            return False
    return True


def years_diff(a: str | None, b: str | None) -> float | None:
    """Years between two date strings (a - b), or None if unparseable."""
    da = parse_release_date(a)
    db = parse_release_date(b)
    if da is None or db is None:
        return None
    return (da - db).days / 365.0
