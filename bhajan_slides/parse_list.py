"""Turn a bhajan list in almost any text layout into an ordered list of names."""

from __future__ import annotations

import csv
import json
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

HEADER_RE = re.compile(
    r"^(bhajans?|bhajan list|song list|songs|program|programme|order of bhajans|"
    r"satsang|agenda|opening|closing|wo video|world (?:youth|organisation|organization).*)$",
    re.IGNORECASE,
)
DATE_RE = re.compile(
    r"^(?:"
    r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}"
    r"|\d{4}-\d{2}-\d{2}"
    r"|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}"
    r"|\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?,?\s+\d{4}"
    r")$",
    re.IGNORECASE,
)
BULLET_RE = re.compile(r"^\s*(?:[-*•●▪‣]|\d{1,3}[\.\)\:\-])\s+")
NOTE_RE = re.compile(
    r"\s*[\(\[](?:fast|slow|medium|repeat|male|female|boys|girls|lead|group|all|soft|loud)[^)\]]*[\(\]]\s*$",
    re.IGNORECASE,
)
INLINE_NUMBER_RE = re.compile(r"(?:^|\s)(?=\d{1,3}[\.\)]\s+\S)")


def read_bhajan_names(source: str | Path) -> list[str]:
    """Read names from a path, or from a raw string when it is not a file."""
    path = Path(source)
    if path.exists() and path.is_file():
        text = _read_file(path)
    else:
        text = str(source)
    return parse_bhajan_text(text)


def parse_bhajan_text(text: str) -> list[str]:
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return []

    if text.startswith("[") or text.startswith("{"):
        loaded = _parse_json(text)
        if loaded is not None:
            return loaded

    lines = text.split("\n")
    # A single block such as "1. Foo 2. Bar 3. Baz".
    if len([ln for ln in lines if ln.strip()]) == 1:
        only = next(ln for ln in lines if ln.strip())
        pieces = [p for p in INLINE_NUMBER_RE.split(only) if p.strip()]
        if len(pieces) >= 2:
            lines = pieces

    names: list[str] = []
    for raw in lines:
        for piece in _split_piece(raw):
            name = _clean_name(piece)
            if name and not _skip(name):
                names.append(name)
    return names


def _read_file(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".json":
        return path.read_text(encoding="utf-8-sig")
    if suffix == ".csv":
        return _read_csv(path)
    if suffix == ".docx":
        return _read_docx(path)
    if suffix in {".xlsx", ".xlsm"}:
        raise SystemExit("Save the spreadsheet as CSV or text, then run again.")
    data = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _read_csv(path: Path) -> str:
    raw = path.read_bytes()
    text = raw.decode("utf-8-sig", errors="replace")
    rows = list(csv.reader(text.splitlines()))
    if not rows:
        return ""
    header = [cell.strip().lower() for cell in rows[0]]
    col = 0
    for key in ("bhajan", "title", "song", "name", "bhajans"):
        if key in header:
            col = header.index(key)
            rows = rows[1:]
            break
    return "\n".join(row[col].strip() for row in rows if len(row) > col and row[col].strip())


def _read_docx(path: Path) -> str:
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    with zipfile.ZipFile(path) as zf:
        xml = zf.read("word/document.xml")
    root = ET.fromstring(xml)
    lines = []
    for para in root.findall(".//w:p", ns):
        parts = [node.text or "" for node in para.findall(".//w:t", ns)]
        lines.append("".join(parts))
    return "\n".join(lines)


def _parse_json(text: str) -> list[str] | None:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if isinstance(data, dict):
        for key in ("bhajans", "songs", "list", "items"):
            if key in data:
                data = data[key]
                break
        else:
            return None
    if not isinstance(data, list):
        return None
    names: list[str] = []
    for item in data:
        if isinstance(item, str):
            names.append(item.strip())
        elif isinstance(item, dict):
            for key in ("title", "name", "bhajan", "song"):
                if item.get(key):
                    names.append(str(item[key]).strip())
                    break
    return [name for name in names if name]


def _split_piece(line: str) -> list[str]:
    if line.count(";") >= 1 or line.count("|") >= 1:
        return re.split(r"[;|]", line)
    return [line]


def _clean_name(line: str) -> str:
    name = line.strip().strip("\"'")
    name = BULLET_RE.sub("", name).strip()
    name = NOTE_RE.sub("", name).strip()
    name = re.sub(r"\s+", " ", name)
    return name.strip(" -–—")


def _skip(name: str) -> bool:
    if name.startswith("#"):
        return True
    if len(name) < 2:
        return True
    if HEADER_RE.match(name):
        return True
    if DATE_RE.match(name):
        return True
    if name.endswith(":") and len(name.split()) <= 4:
        return True
    return False
