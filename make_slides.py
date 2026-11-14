"""Build a bhajan PowerPoint from a name list and Sai Rhythms.

The deck follows template.pptx: gold title, white lyric lines, gray italic
meaning, and the next bhajan named in gold at the lower right. An AUM slide
opens the deck and Om Shanthi closes it.

Examples:
    python make_slides.py example_bhajans.txt
    python make_slides.py "C:\\lists\\thursday.txt" -o "Nov 13 2026 WO Video.pptx"
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path

from bhajan_slides.parse_list import read_bhajan_names
from bhajan_slides.sairhythms import apply_song_page, load_songs, match_bhajan
from bhajan_slides.slides import build_pptx, safe_output_path

ROOT = Path(__file__).resolve().parent
TEMPLATE = ROOT / "template.pptx"


@lru_cache(maxsize=1)
def writable_root() -> Path:
    """Project folder when it can be written, otherwise the system temp folder.

    Hosts such as AWS Lambda keep the app in /var/task, which is read-only.
    """
    fallback = Path(tempfile.gettempdir()) / "bhajan-slide-maker"
    for candidate in (ROOT, fallback):
        try:
            folder = candidate / "cache"
            folder.mkdir(parents=True, exist_ok=True)
            probe = folder / ".write-test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            return candidate
        except OSError:
            continue
    raise RuntimeError("No writable folder is available for the song cache.")


CACHE = writable_root() / "cache" / "sairhythms.json"
PAGE_CACHE = writable_root() / "cache"
BUNDLED_CACHE = ROOT / "data" / "sairhythms.json"


def _without_service_bookends(names: list[str]) -> list[str]:
    """Drop an opening AUM and a closing Om Shanthi; the template already adds those."""
    names = list(names)
    if names and names[0].strip().casefold() in {"aum", "om", "aum (x3)", "om (x3)"}:
        names = names[1:]
    if names and "shanthi" in names[-1].casefold() and names[-1].casefold().startswith("om"):
        names = names[:-1]
    return names


def generate_deck(
    names: list[str],
    output: Path,
    *,
    template: Path | None = None,
    bookends: bool = True,
    on_hit=None,
) -> tuple[Path, list]:
    """Match names on Sai Rhythms and write a PowerPoint. Names are used in order."""
    template = template or TEMPLATE
    names = list(names)
    if bookends:
        names = _without_service_bookends(names)
    if not names:
        raise ValueError("No bhajan names found in that list.")
    if not template.exists():
        raise FileNotFoundError("Missing template.pptx. Keep the bhajan slide template in this folder.")
    songs = load_songs(CACHE, bundled_path=BUNDLED_CACHE)
    hits = []
    for number, name in enumerate(names, start=1):
        hit = match_bhajan(name, songs)
        hits.append(hit)
        if on_hit:
            on_hit(number, hit)
    pending = [hit for hit in hits if hit.found]
    if pending:
        workers = min(8, len(pending))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(lambda hit: apply_song_page(hit, PAGE_CACHE), pending))
    path = build_pptx(template, hits, output, bookends=bookends)
    return path, hits


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="Make a Sai bhajan PowerPoint from a list of names.")
    parser.add_argument(
        "source",
        help="Text, CSV, JSON, or Word file with one bhajan name per line. Numbered lists and bullets are fine.",
    )
    parser.add_argument("-o", "--output", type=Path, help="Output .pptx path. Defaults to output/<list name>.pptx")
    parser.add_argument("--template", type=Path, default=TEMPLATE, help="Deck template. Defaults to template.pptx")
    parser.add_argument("--refresh", action="store_true", help="Download a fresh Sai Rhythms catalogue")
    parser.add_argument("--no-bookends", action="store_true", help="Skip the AUM opening and Om Shanthi closing slides")
    args = parser.parse_args(argv)

    template = args.template if args.template.is_absolute() else (Path.cwd() / args.template)
    if not template.exists():
        template = TEMPLATE
    if not template.exists():
        print("Missing template.pptx. Keep the bhajan slide template in this folder.", file=sys.stderr)
        return 1

    names = read_bhajan_names(args.source)
    if not args.no_bookends:
        names = _without_service_bookends(names)
    if not names:
        print("No bhajan names found in that list.", file=sys.stderr)
        return 1

    print(f"Reading {len(names)} bhajan{'s' if len(names) != 1 else ''} in order.")
    print("Loading Sai Rhythms...")
    if args.refresh:
        load_songs(CACHE, refresh=True, bundled_path=BUNDLED_CACHE)

    output = args.output
    if output is None:
        source_path = Path(args.source)
        stem = source_path.stem if source_path.exists() else "bhajans"
        output = ROOT / "output" / f"{stem}.pptx"
    elif not output.is_absolute():
        output = Path.cwd() / output
    if output.suffix.lower() != ".pptx":
        output = output.with_suffix(".pptx")
    requested = output
    output = safe_output_path(output)
    if output.name != requested.name:
        print(f"That file name is not allowed on Windows. Saving as {output.name}")

    def _report(number: int, hit) -> None:
        if hit.found:
            extra = f"  ({hit.note})" if hit.note else ""
            print(f"{number:>2}. {hit.query}")
            print(f"    {hit.url}{extra}")
        else:
            print(f"{number:>2}. {hit.query}  ->  NOT FOUND")

    try:
        output, hits = generate_deck(
            names,
            output,
            template=template,
            bookends=not args.no_bookends,
            on_hit=_report,
        )
    except (ValueError, FileNotFoundError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    found = sum(1 for hit in hits if hit.found)
    print(f"Wrote {output}")
    print(f"Lyrics found for {found} of {len(hits)}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
