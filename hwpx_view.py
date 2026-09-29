"""HWPX 양식 리더.

`<hp:t>`만 평평하게 긁어모으면 표 안의 글자가 문단 사이에 섞여 버리고,
탭으로 맞춘 항목 번호가 무너진다. 이 모듈은 OWPML 구조를 그대로 따라가며
문단과 표를 구분해 읽는다.

  render(path) -> (html, text)

html 은 미리보기 화면에 그대로 넣을 수 있는 조각이고,
text 는 분류와 날짜 추출에 쓰는 평문이다. 문서에서 온 글자는 전부
이스케이프하며, 태그는 이 모듈이 직접 만든 것만 나간다.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

# 문단 안에서 자리만 차지하는 개체들 — 글자가 없으므로 표시만 남긴다.
_OBJECT_LABELS = {
    "pic": "그림", "ole": "개체", "equation": "수식", "chart": "차트",
    "container": "묶음 개체", "rect": "도형", "ellipse": "도형",
    "line": "도형", "polygon": "도형", "curve": "도형", "connectLine": "도형",
}

# HWPUNIT(1/7200인치)을 화면 픽셀로 옮길 때 쓰는 값
_HWPUNIT_TO_PX = 96 / 7200
_MAX_INDENT_PX = 96


def local(element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def esc(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace('"', "&quot;"))


# ------------------------------------------------------------------ 서식

class Styles:
    """header.xml에서 굵기와 정렬, 들여쓰기만 추려 둔다."""

    def __init__(self):
        self.bold_ids: set[str] = set()
        self.underline_ids: set[str] = set()
        self.align: dict[str, str] = {}
        self.indent: dict[str, int] = {}

    @classmethod
    def parse(cls, xml: bytes | None) -> "Styles":
        styles = cls()
        if not xml:
            return styles
        try:
            root = ET.fromstring(xml.decode("utf-8", "ignore"))
        except ET.ParseError:
            return styles

        for element in root.iter():
            name = local(element)
            if name == "charPr":
                char_id = element.get("id")
                if char_id is None:
                    continue
                for child in element:
                    if local(child) == "bold":
                        styles.bold_ids.add(char_id)
                    elif local(child) == "underline":
                        styles.underline_ids.add(char_id)
            elif name == "paraPr":
                para_id = element.get("id")
                if para_id is None:
                    continue
                for child in element.iter():
                    tag = local(child)
                    if tag == "align":
                        styles.align[para_id] = (child.get("horizontal") or "LEFT").upper()
                    elif tag == "left":
                        try:
                            value = int(child.get("value") or 0)
                        except ValueError:
                            value = 0
                        px = min(int(value * _HWPUNIT_TO_PX), _MAX_INDENT_PX)
                        if px:
                            styles.indent[para_id] = px
        return styles

    def is_bold(self, char_id: str | None) -> bool:
        return char_id is not None and char_id in self.bold_ids

    def is_underline(self, char_id: str | None) -> bool:
        return char_id is not None and char_id in self.underline_ids

    def para_style(self, para_id: str | None) -> tuple[str, int]:
        if para_id is None:
            return "LEFT", 0
        return self.align.get(para_id, "LEFT"), self.indent.get(para_id, 0)


# ------------------------------------------------------------------ 파싱
#
# 블록은 다음 셋 중 하나다.
#   ("p", 정렬, 들여쓰기, 인라인 html, 평문)
#   ("table", [[(colspan, rowspan, 블록 목록), ...], ...])
#   ("object", 이름)


def _paragraph(node, styles: Styles, depth: int) -> list[tuple]:
    blocks: list[tuple] = []
    html_parts: list[str] = []
    text_parts: list[str] = []
    align, indent = styles.para_style(node.get("paraPrIDRef"))

    def flush():
        if not text_parts and not html_parts:
            return
        plain = "".join(text_parts).strip()
        if plain:
            blocks.append(("p", align, indent, "".join(html_parts), plain))
        html_parts.clear()
        text_parts.clear()

    def handle(child, char_id: str | None):
        name = local(child)
        if name == "t":
            raw = "".join(child.itertext())
            if not raw:
                return
            text_parts.append(raw)
            piece = esc(raw)
            if styles.is_bold(char_id):
                piece = f"<b>{piece}</b>"
            if styles.is_underline(char_id):
                piece = f"<u>{piece}</u>"
            html_parts.append(piece)
        elif name == "tab":
            text_parts.append("\t")
            html_parts.append('<span class="hx-tab"></span>')
        elif name == "lineBreak":
            text_parts.append("\n")
            html_parts.append("<br>")
        elif name == "tbl":
            flush()
            blocks.append(("table", _table(child, styles, depth + 1)))
        elif name in _OBJECT_LABELS:
            flush()
            blocks.append(("object", _OBJECT_LABELS[name]))
        elif name in ("ctrl", "container"):
            for grandchild in child:
                handle(grandchild, char_id)

    for run in node:
        if local(run) != "run":
            continue
        char_id = run.get("charPrIDRef")
        for child in run:
            handle(child, char_id)

    flush()
    return blocks


def _table(node, styles: Styles, depth: int) -> list[list[tuple]]:
    if depth > 6:          # 표 안의 표가 끝없이 이어지는 경우를 막는다
        return []
    rows: list[list[tuple]] = []
    for tr in node:
        if local(tr) != "tr":
            continue
        cells: list[tuple] = []
        for tc in tr:
            if local(tc) != "tc":
                continue
            colspan = rowspan = 1
            inner: list[tuple] = []
            for child in tc:
                tag = local(child)
                if tag == "cellSpan":
                    colspan = _int(child.get("colSpan"), 1)
                    rowspan = _int(child.get("rowSpan"), 1)
                elif tag == "subList":
                    for sub in child:
                        if local(sub) == "p":
                            inner.extend(_paragraph(sub, styles, depth))
            cells.append((colspan, rowspan, inner))
        if cells:
            rows.append(cells)
    return rows


def _int(value: str | None, default: int) -> int:
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return default


# ------------------------------------------------------------------ 출력

_ALIGN_CLASS = {"CENTER": " hx-center", "RIGHT": " hx-right", "JUSTIFY": ""}


def _blocks_to_html(blocks: list[tuple]) -> str:
    out: list[str] = []
    for block in blocks:
        kind = block[0]
        if kind == "p":
            _, align, indent, inline, _plain = block
            cls = _ALIGN_CLASS.get(align, "")
            style = f' style="padding-left:{indent}px"' if indent else ""
            out.append(f'<p class="hx-p{cls}"{style}>{inline}</p>')
        elif kind == "table":
            out.append(_table_to_html(block[1]))
        elif kind == "object":
            out.append(f'<p class="hx-obj">[{esc(block[1])}]</p>')
    return "".join(out)


def _table_to_html(rows: list[list[tuple]]) -> str:
    if not rows:
        return ""
    out = ['<table class="hx-table">']
    for index, cells in enumerate(rows):
        out.append("<tr>")
        tag = "th" if index == 0 else "td"
        for colspan, rowspan, inner in cells:
            attrs = ""
            if colspan > 1:
                attrs += f' colspan="{colspan}"'
            if rowspan > 1:
                attrs += f' rowspan="{rowspan}"'
            body = _blocks_to_html(inner) or "<p class='hx-p'></p>"
            out.append(f"<{tag}{attrs}>{body}</{tag}>")
        out.append("</tr>")
    out.append("</table>")
    return "".join(out)


def _blocks_to_text(blocks: list[tuple]) -> str:
    lines: list[str] = []
    for block in blocks:
        kind = block[0]
        if kind == "p":
            lines.append(block[4])
        elif kind == "table":
            for cells in block[1]:
                values = [_blocks_to_text(inner).replace("\n", " ").strip()
                          for _, _, inner in cells]
                lines.append(" | ".join(v for v in values if v))
        elif kind == "object":
            lines.append(f"[{block[1]}]")
    return "\n".join(line for line in lines if line.strip())


# ------------------------------------------------------------------ 진입

def render(path: str | Path) -> tuple[str, str]:
    """(미리보기 html, 평문)을 돌려준다. 읽지 못하면 예외를 낸다."""
    path = Path(path)
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        header = archive.read("Contents/header.xml") if "Contents/header.xml" in names else None
        styles = Styles.parse(header)

        sections = [n for n in names if re.fullmatch(r"Contents/section\d+\.xml", n)]
        sections.sort(key=lambda n: int(re.search(r"(\d+)", n.rsplit("/", 1)[-1]).group(1)))
        if not sections:
            sections = [n for n in names if n.endswith(".xml") and "section" in n.lower()]
        if not sections:
            raise ValueError("hwpx 안에서 본문을 찾지 못했습니다.")

        blocks: list[tuple] = []
        for name in sections:
            try:
                root = ET.fromstring(archive.read(name).decode("utf-8", "ignore"))
            except ET.ParseError:
                continue
            for element in root:
                if local(element) == "p":
                    blocks.extend(_paragraph(element, styles, 0))

    if not blocks:
        raise ValueError("본문에 읽을 글자가 없습니다.")
    return _blocks_to_html(blocks), _blocks_to_text(blocks)
