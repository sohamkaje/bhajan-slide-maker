"""Download the latest Sai Rhythms catalogue into data/sairhythms.json.

Run it by hand:

    python refresh_catalogue.py

Windows Task Scheduler runs this once a day. The saved file is replaced only
after a complete song list comes back, so a failed download leaves the current
file in place.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

from bhajan_slides.sairhythms import download_catalogue, save_catalogue
from make_slides import BUNDLED_CACHE, CACHE

LOG = CACHE.parent / "catalogue-refresh.log"


def _song_count(path: Path) -> int | None:
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    songs = payload.get("songs")
    return len(songs) if isinstance(songs, list) else None


def _log(message: str) -> None:
    print(message)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as handle:
            handle.write(f"{datetime.now().isoformat(timespec='seconds')}  {message}\n")
    except OSError:
        pass


def main() -> int:
    previous = _song_count(BUNDLED_CACHE)
    try:
        songs, version = download_catalogue()
        save_catalogue(BUNDLED_CACHE, songs, version)
        try:
            save_catalogue(CACHE, songs, version)
        except OSError:
            pass
    except Exception as exc:
        _log(f"Catalogue refresh failed: {exc}")
        return 1

    change = ""
    if previous is not None:
        change = f" ({len(songs) - previous:+d} since the last file)"
    _log(f"Saved {len(songs)} songs to {BUNDLED_CACHE.name}{change}.")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    raise SystemExit(main())
