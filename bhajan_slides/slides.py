"""Fill the bhajan deck template and write a PowerPoint file."""

from __future__ import annotations

import re
import shutil
from copy import deepcopy
from pathlib import Path

from lxml import etree
from pptx import Presentation
from pptx.enum.shapes import PP_PLACEHOLDER
from pptx.oxml.ns import qn

from bhajan_slides.sairhythms import MISSING_LYRICS, MISSING_MEANING, SongHit, lyric_lines

A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
_UNSAFE_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_output_path(path: Path) -> Path:
    """Drop characters Windows rejects in a file name. Colons in times become dots."""
    stem = _UNSAFE_FILENAME.sub(".", path.stem).strip(" .")
    if not stem:
        stem = "bhajans"
    suffix = path.suffix if path.suffix else ".pptx"
    return path.with_name(stem + suffix)


def build_pptx(template: Path, hits: list[SongHit], output: Path, bookends: bool = True) -> Path:
    output = safe_output_path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(template, output)
    prs = Presentation(output)
    opening, prototype, closing = _classify(prs)
    if prototype is None:
        raise SystemExit(f"No bhajan slide found in the template: {template}")
    if not bookends:
        opening = None
        closing = None

    original_count = len(prs.slides)
    for _ in hits:
        _clone_slide(prs, prototype)
    new_indexes = list(range(original_count, original_count + len(hits)))

    titles = [hit.title for hit in hits]
    closing_title = _slide_title(prs.slides[closing]) if closing is not None else ""
    for offset, hit in enumerate(hits):
        if offset + 1 < len(titles):
            coming = titles[offset + 1]
        else:
            coming = closing_title
        _fill_bhajan_slide(prs.slides[new_indexes[offset]], hit, coming, prs.slide_width)

    if opening is not None and titles:
        _set_next_line(prs.slides[opening], titles[0], prs.slide_width)

    keep = []
    if opening is not None:
        keep.append(opening)
    keep.extend(new_indexes)
    if closing is not None:
        keep.append(closing)
    _keep_slides(prs, keep)
    prs.save(output)
    return output


def _classify(prs: Presentation) -> tuple[int | None, int | None, int | None]:
    opening = None
    closing = None
    prototype = None
    for index, slide in enumerate(prs.slides):
        title = _slide_title(slide).casefold()
        centered = _body_is_centered(slide)
        if title == "aum" and centered:
            opening = index
        elif "shanthi" in title and centered:
            closing = index
        elif prototype is None:
            prototype = index
    if prototype is None and len(prs.slides):
        prototype = 0
    return opening, prototype, closing


def _clone_slide(prs: Presentation, index: int):
    source = prs.slides[index]
    dest = prs.slides.add_slide(source.slide_layout)
    tree = dest.shapes._spTree
    for child in list(tree):
        if child.tag in (qn("p:nvGrpSpPr"), qn("p:grpSpPr")):
            continue
        tree.remove(child)
    for shape in source.shapes:
        tree.append(deepcopy(shape.element))
    return dest


def _keep_slides(prs: Presentation, indexes: list[int]) -> None:
    sld_id_lst = prs.slides._sldIdLst
    items = list(sld_id_lst)
    keep = set(indexes)
    for index, element in enumerate(items):
        if index not in keep:
            rel_id = element.get(qn("r:id"))
            if rel_id:
                prs.part.drop_rel(rel_id)
    for element in list(sld_id_lst):
        sld_id_lst.remove(element)
    for index in indexes:
        sld_id_lst.append(items[index])


def _fill_bhajan_slide(slide, hit: SongHit, coming: str, slide_width: int) -> None:
    title_shape = _title_shape(slide)
    if title_shape is not None:
        _set_run_text(title_shape, hit.title)
    body = _content_shape(slide)
    if body is not None:
        lines = lyric_lines(hit.lyrics) or [MISSING_LYRICS]
        meaning = hit.meaning if hit.found else MISSING_MEANING
        _set_body(body, lines, meaning)
    _set_next_line(slide, coming, slide_width)


def _set_body(shape, lines: list[str], meaning: str) -> None:
    tx_body = shape.text_frame._txBody
    for paragraph in tx_body.findall(qn("a:p")):
        tx_body.remove(paragraph)
    for line in lines:
        tx_body.append(_paragraph(line, "lyric"))
    if meaning:
        tx_body.append(_paragraph("", "blank"))
        tx_body.append(_paragraph(meaning, "meaning"))


def _paragraph(text: str, kind: str):
    paragraph = etree.Element(f"{{{A_NS}}}p")
    props = etree.SubElement(paragraph, f"{{{A_NS}}}pPr")
    props.set("indent", "7222")
    props.set("defTabSz", "594359")
    before = etree.SubElement(props, f"{{{A_NS}}}spcBef")
    points = etree.SubElement(before, f"{{{A_NS}}}spcPts")
    points.set("val", "200")
    default = etree.SubElement(props, f"{{{A_NS}}}defRPr")
    if kind == "lyric":
        default.set("sz", "2900")
    elif kind == "blank":
        default.set("sz", "1500")
        default.set("i", "1")
        _gray(default, "AEAEAE")
    else:
        default.set("sz", "1900")
        default.set("i", "1")
        _gray(default, "D2D2D2")
    if text:
        run = etree.SubElement(paragraph, f"{{{A_NS}}}r")
        run_props = etree.SubElement(run, f"{{{A_NS}}}rPr")
        run_props.set("lang", "en-US")
        if kind == "meaning":
            run_props.set("sz", "1900")
            run_props.set("i", "1")
            _gray(run_props, "D2D2D2")
        node = etree.SubElement(run, f"{{{A_NS}}}t")
        node.text = text
    etree.SubElement(paragraph, f"{{{A_NS}}}endParaRPr")
    return paragraph


def _gray(parent, hex_color: str) -> None:
    fill = etree.SubElement(parent, f"{{{A_NS}}}solidFill")
    color = etree.SubElement(fill, f"{{{A_NS}}}srgbClr")
    color.set("val", hex_color)


def _set_next_line(slide, coming: str, slide_width: int) -> None:
    shape = _next_shape(slide)
    if shape is None:
        return
    _widen_next_box(shape, slide_width)
    tx_body = shape.text_frame._txBody
    for paragraph in tx_body.findall(qn("a:p")):
        tx_body.remove(paragraph)
    paragraph = etree.SubElement(tx_body, qn("a:p"))
    props = etree.SubElement(paragraph, qn("a:pPr"))
    props.set("algn", "r")
    if not coming:
        return
    _colored_run(paragraph, "Next:", "D2D2D2")
    _colored_run(paragraph, " " + coming, "FFC000", preserve=True)


def _colored_run(paragraph, text: str, hex_color: str, preserve: bool = False) -> None:
    run = etree.SubElement(paragraph, qn("a:r"))
    props = etree.SubElement(run, qn("a:rPr"))
    props.set("lang", "en-US")
    fill = etree.SubElement(props, qn("a:solidFill"))
    color = etree.SubElement(fill, qn("a:srgbClr"))
    color.set("val", hex_color)
    node = etree.SubElement(run, qn("a:t"))
    if preserve:
        node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    node.text = text


def _widen_next_box(shape, slide_width: int) -> None:
    transform = shape._element.find(qn("p:spPr")).find(qn("a:xfrm"))
    if transform is None:
        return
    offset = transform.find(qn("a:off"))
    extent = transform.find(qn("a:ext"))
    left = 3657600  # 4 inches, right-aligned so long names stay on the slide
    offset.set("x", str(left))
    extent.set("cx", str(int(slide_width) - left))


def _set_run_text(shape, text: str) -> None:
    nodes = shape._element.findall(".//" + qn("a:t"))
    if not nodes:
        shape.text_frame.paragraphs[0].text = text
        return
    nodes[0].text = text
    for extra in nodes[1:]:
        extra.text = ""


def _title_shape(slide):
    for shape in slide.shapes:
        if shape.has_text_frame and shape.is_placeholder:
            if shape.placeholder_format.type == PP_PLACEHOLDER.TITLE:
                return shape
    return None


def _content_shape(slide):
    for shape in slide.shapes:
        if shape.has_text_frame and shape.is_placeholder and shape.placeholder_format.idx == 1:
            return shape
    return None


def _next_shape(slide):
    for shape in slide.shapes:
        if shape.has_text_frame and shape.text_frame.text.strip().lower().startswith("next"):
            return shape
    return None


def _slide_title(slide) -> str:
    shape = _title_shape(slide)
    if shape is None:
        return ""
    return shape.text_frame.text.strip()


def _body_is_centered(slide) -> bool:
    shape = _content_shape(slide)
    if shape is None:
        return False
    body = shape.text_frame._txBody.find(qn("a:bodyPr"))
    return body is not None and body.get("anchor") == "ctr"
