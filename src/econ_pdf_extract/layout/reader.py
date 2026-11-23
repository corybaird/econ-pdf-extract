from __future__ import annotations

import contextlib
import io
import logging
from collections import Counter
from pathlib import Path

import pymupdf

from econ_pdf_extract.core.models import (
    BBox,
    Block,
    BlockKind,
    Document,
    Line,
    Page,
    Span,
)
from econ_pdf_extract.core.paths import load_dictionary

logger = logging.getLogger(__name__)


class PdfReader:
    """Reads a PDF with PyMuPDF into geometry-preserving Document/Page/Block/Line/Span models."""

    def __init__(self, detect_tables: bool = True):
        math_fonts = load_dictionary("math_fonts")
        self._math_fonts = math_fonts.MATH_FONT_PREFIXES
        self._big_op_fonts = math_fonts.BIG_OP_FONT_PREFIXES
        self._detect_tables = detect_tables

    def read(self, pdf_path: Path | str, paper_id: str | None = None) -> Document:
        path = Path(pdf_path)
        if not path.exists():
            raise FileNotFoundError(f"PDF not found: {path}")
        resolved_id = paper_id or path.stem
        pages: list[Page] = []
        doc_size_weights: Counter[float] = Counter()

        with pymupdf.open(path) as raw_doc:
            for idx in range(len(raw_doc)):
                page = self._read_page(raw_doc[idx], idx + 1, doc_size_weights)
                pages.append(page)

        doc_body_size = self._modal_size(doc_size_weights, default=10.0)
        for page in pages:
            if page.body_font_size <= 0.0:
                page.body_font_size = doc_body_size

        return Document(
            paper_id=resolved_id,
            source_path=path,
            page_count=len(pages),
            body_font_size=doc_body_size,
            pages=pages,
        )

    def _read_page(self, raw_page: pymupdf.Page, page_num: int, doc_size_weights: Counter[float]) -> Page:
        width = float(raw_page.rect.width)
        height = float(raw_page.rect.height)
        page_dict = raw_page.get_text("dict", sort=True)

        blocks: list[Block] = []
        page_size_weights: Counter[float] = Counter()
        char_count = 0

        for b_idx, raw_block in enumerate(page_dict.get("blocks", []), 1):
            if "lines" not in raw_block:
                continue
            block = self._build_block(raw_block, page_num, b_idx, page_size_weights, doc_size_weights)
            if block is None:
                continue
            char_count += len(block.text)
            blocks.append(block)

        h_rules, v_rules, filled_rects = self._extract_drawings(raw_page, width, height)
        table_bboxes = self._extract_table_bboxes(raw_page, h_rules, v_rules, filled_rects)
        image_count = len(raw_page.get_images(full=False))

        if char_count < 20 and image_count > 0:
            logger.warning("Page %d has %d chars and %d images; may be scanned", page_num, char_count, image_count)

        body_font_size = self._modal_size(page_size_weights, default=0.0)
        return Page(
            page=page_num,
            width=width,
            height=height,
            body_font_size=body_font_size,
            blocks=blocks,
            horizontal_rules=h_rules,
            vertical_rules=v_rules,
            table_bboxes=table_bboxes,
            filled_rects=filled_rects,
            image_count=image_count,
            char_count=char_count,
        )

    def _build_block(self, raw_block: dict, page_num: int, b_idx: int, page_weights: Counter[float], doc_weights: Counter[float]) -> Block | None:
        lines: list[Line] = []
        block_weights: Counter[float] = Counter()
        block_is_bold = False
        max_size = 0.0

        for raw_line in raw_block.get("lines", []):
            line = self._build_line(raw_line, page_num, block_weights)
            if line is None:
                continue
            lines.append(line)
            for span in line.spans:
                if span.text.strip():
                    max_size = max(max_size, span.size)
                    if span.is_bold:
                        block_is_bold = True
                    rounded = round(span.size * 2) / 2
                    weight = len(span.text.strip())
                    if 7.5 <= rounded <= 14.0 and not span.is_math_font:
                        page_weights[rounded] += weight
                        doc_weights[rounded] += weight

        if not lines:
            return None

        bbox = self._to_bbox(raw_block["bbox"])
        text = "\n".join(line.text for line in lines).strip()
        return Block(
            block_id=f"p{page_num:02d}_b{b_idx:02d}",
            page=page_num,
            bbox=bbox,
            lines=lines,
            kind=BlockKind.PROSE,
            is_bold=block_is_bold,
            max_size=max_size,
            modal_size=self._modal_size(block_weights, default=max_size),
            text=text,
        )

    def _build_line(self, raw_line: dict, page_num: int, block_weights: Counter[float]) -> Line | None:
        spans: list[Span] = []
        line_weights: Counter[float] = Counter()
        has_math = False
        has_big_op = False

        for raw_span in raw_line.get("spans", []):
            raw_text = raw_span.get("text", "")
            if not raw_text:
                continue
            font = str(raw_span.get("font", ""))
            font_low = font.lower()
            flags = int(raw_span.get("flags", 0))
            size = float(raw_span.get("size", 0.0))
            is_bold = bool(flags & 16) or any(tag in font_low for tag in ("bold", "medi", "sfbx", "sfss", "cmbx", "lmbx", "hebo", "tibo"))
            is_italic = bool(flags & 2) or any(tag in font_low for tag in ("ital", "obli", "tiit", "cmti", "sfti"))
            is_math = any(mf in font_low for mf in self._math_fonts)
            is_big_op = any(bf in font_low for bf in self._big_op_fonts)

            span = Span(
                text=raw_text,
                bbox=self._to_bbox(raw_span["bbox"]),
                font=font,
                size=size,
                flags=flags,
                is_bold=is_bold,
                is_italic=is_italic,
                is_math_font=is_math,
                is_big_op_font=is_big_op,
            )
            spans.append(span)
            if raw_text.strip():
                has_math = has_math or is_math
                has_big_op = has_big_op or is_big_op
                rounded = round(size * 2) / 2
                weight = len(raw_text.strip())
                line_weights[rounded] += weight
                block_weights[rounded] += weight

        text = self._join_spans(spans)
        if not text:
            return None

        return Line(
            text=text,
            bbox=self._to_bbox(raw_line["bbox"]),
            page=page_num,
            spans=spans,
            has_math_font=has_math,
            has_big_op_font=has_big_op,
            modal_size=self._modal_size(line_weights, default=0.0),
        )

    @staticmethod
    def _join_spans(spans: list[Span]) -> str:
        if not spans:
            return ""
        parts: list[str] = [spans[0].text]
        prev = spans[0]
        for cur in spans[1:]:
            gap = cur.bbox[0] - prev.bbox[2]
            ref_size = max(prev.size, cur.size, 8.0)
            needs_space = (
                gap > 0.25 * ref_size
                and parts[-1]
                and not parts[-1].endswith((" ", "\t"))
                and not cur.text.startswith((" ", "\t"))
            )
            if needs_space:
                parts.append(" ")
            parts.append(cur.text)
            prev = cur
        return "".join(parts).strip()

    @staticmethod
    def _extract_drawings(raw_page: pymupdf.Page, page_w: float, page_h: float) -> tuple[list[BBox], list[BBox], list[BBox]]:
        h_rules: list[BBox] = []
        v_rules: list[BBox] = []
        filled_rects: list[BBox] = []

        for drawing in raw_page.get_drawings():
            rect = drawing.get("rect")
            if rect is None:
                continue
            x0, y0, x1, y1 = float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1)
            w = x1 - x0
            h = y1 - y0
            if w >= 8.0 and h <= 2.5:
                h_rules.append((x0, y0, x1, y1))
            elif h >= 12.0 and w <= 2.5:
                v_rules.append((x0, y0, x1, y1))
            elif drawing.get("fill") is not None and w >= 15.0 and h >= 8.0 and w < 0.95 * page_w and h < 0.85 * page_h:
                filled_rects.append((x0, y0, x1, y1))

            for item in drawing.get("items", []):
                if item[0] != "l":
                    continue
                p1, p2 = item[1], item[2]
                lx0, lx1 = min(float(p1.x), float(p2.x)), max(float(p1.x), float(p2.x))
                ly0, ly1 = min(float(p1.y), float(p2.y)), max(float(p1.y), float(p2.y))
                lw, lh = lx1 - lx0, ly1 - ly0
                bbox = (lx0, ly0, lx1, ly1)
                if lw >= 8.0 and lh <= 2.5 and bbox not in h_rules:
                    h_rules.append(bbox)
                elif lh >= 12.0 and lw <= 2.5 and bbox not in v_rules:
                    v_rules.append(bbox)

        return h_rules, v_rules, filled_rects

    def _extract_table_bboxes(self, raw_page: pymupdf.Page, h_rules: list[BBox], v_rules: list[BBox], filled_rects: list[BBox]) -> list[BBox]:
        if not self._detect_tables:
            return []
        if len(h_rules) < 2 and len(v_rules) < 2 and len(filled_rects) < 4:
            return []
        bboxes: list[BBox] = []
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                finder = raw_page.find_tables()
            for table in finder.tables:
                if table.bbox:
                    bboxes.append(self._to_bbox(table.bbox))
        except (RuntimeError, ValueError) as exc:
            logger.debug("find_tables skipped on page %d: %s", raw_page.number + 1, exc)
        return bboxes

    @staticmethod
    def _modal_size(weights: Counter[float], default: float) -> float:
        if not weights:
            return default
        return weights.most_common(1)[0][0]

    @staticmethod
    def _to_bbox(raw: tuple | list) -> BBox:
        return (float(raw[0]), float(raw[1]), float(raw[2]), float(raw[3]))
