"""Local page for making a bhajan PowerPoint from a pasted list or a text file."""

from __future__ import annotations

import re
import uuid
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_file
from pptx import Presentation
from pptx.enum.shapes import PP_PLACEHOLDER
from pptx.oxml.ns import qn

from bhajan_slides.parse_list import parse_bhajan_text
from make_slides import ROOT, generate_deck

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 1_000_000
STORE = ROOT / "output" / "web"
TOKEN_RE = re.compile(r"^[0-9a-f]{32}$")


def _list_text(raw: str) -> str:
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\\n", "\n")
    if "/n" in text:
        text = text.replace("/n", "\n")
    return text


def _job_path(token: str) -> Path | None:
    if not TOKEN_RE.fullmatch(token or ""):
        return None
    folder = STORE / token
    if not folder.is_dir():
        return None
    files = sorted(folder.glob("*.pptx"))
    return files[0] if files else None


def _is_meaning(paragraph) -> bool:
    props = paragraph._p.find(qn("a:pPr"))
    if props is None:
        return False
    default = props.find(qn("a:defRPr"))
    return default is not None and default.get("i") == "1" and default.get("sz") == "1900"


def _slide_preview(path: Path) -> list[dict]:
    presentation = Presentation(path)
    slides = []
    for slide in presentation.slides:
        title = ""
        lyrics: list[str] = []
        meaning = ""
        coming = ""
        centered = False
        for shape in slide.shapes:
            if not shape.has_text_frame:
                continue
            text = shape.text_frame.text.strip()
            if shape.is_placeholder and shape.placeholder_format.type == PP_PLACEHOLDER.TITLE:
                title = text
                continue
            if text.lower().startswith("next"):
                coming = text.split(":", 1)[-1].strip()
                continue
            if shape.is_placeholder and shape.placeholder_format.idx == 1:
                body = shape.text_frame._txBody.find(qn("a:bodyPr"))
                centered = body is not None and body.get("anchor") == "ctr"
                lyric_lines: list[str] = []
                meaning_lines: list[str] = []
                for paragraph in shape.text_frame.paragraphs:
                    line = paragraph.text.strip()
                    if not line:
                        continue
                    if _is_meaning(paragraph):
                        meaning_lines.append(line)
                    else:
                        lyric_lines.append(line)
                lyrics = lyric_lines
                meaning = " ".join(meaning_lines)
        slides.append(
            {
                "title": title,
                "lines": lyrics,
                "meaning": meaning,
                "next": coming,
                "center": centered,
            }
        )
    return slides


@app.get("/")
def index():
    return render_template("index.html")


@app.post("/generate")
def generate():
    upload = request.files.get("file")
    pasted = request.form.get("list") or ""
    file_text = ""
    if upload and upload.filename:
        file_text = upload.read().decode("utf-8-sig", errors="replace")
    if file_text.strip():
        text = file_text
        default_name = Path(upload.filename).stem or "bhajans"
    else:
        text = pasted
        default_name = "bhajans"
    names = parse_bhajan_text(_list_text(text))
    if not names:
        return jsonify(error="No bhajan names found. Put one name on each line."), 400

    requested = (request.form.get("filename") or "").strip() or default_name
    token = uuid.uuid4().hex
    destination = STORE / token / requested
    try:
        path, hits = generate_deck(names, destination)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    except Exception as exc:
        return jsonify(error=str(exc)), 500

    found = sum(1 for hit in hits if hit.found)
    return jsonify(
        token=token,
        filename=path.name,
        found=found,
        total=len(hits),
        slides=_slide_preview(path),
    )


@app.get("/download/<token>")
def download(token: str):
    path = _job_path(token)
    if path is None:
        return "That file is no longer available.", 404
    return send_file(path, as_attachment=True, download_name=path.name)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5050, debug=False)
