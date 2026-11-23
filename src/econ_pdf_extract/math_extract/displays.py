from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from econ_pdf_extract.core.config import ConfigLoader
from econ_pdf_extract.core.models import (
    BBox,
    BlockKind,
    Document,
    MathKind,
    MathObject,
    Page,
    SourceChannel,
    Span,
)
from econ_pdf_extract.core.paths import load_dictionary

_MATH_OPERATOR_RE = re.compile(r"[=≈∼≤≥∈∑∏∫→<>±×]")
_PROSE_END_RE = re.compile(r"[.:;]\s*$")
_EXCLUDED_BLOCK_KINDS = frozenset(
    {
        BlockKind.MARGIN_NOISE,
        BlockKind.FOOTNOTE,
        BlockKind.TABLE,
        BlockKind.CAPTION,
        BlockKind.HEADER_FOOTER,
        BlockKind.HEADING,
    }
)


@dataclass
class _LogicalRow:
    page: int
    spans: list[Span] = field(default_factory=list)
    text: str = ""
    raw_text: str = ""
    bbox: BBox = (0.0, 0.0, 0.0, 0.0)
    has_math_font: bool = False
    has_big_op_font: bool = False
    tag: str | None = None
    tag_bbox: BBox | None = None
    body_text: str = ""
    english_words: int = 0

    @property
    def left(self) -> float:
        return self.bbox[0]

    @property
    def top(self) -> float:
        return self.bbox[1]

    @property
    def right(self) -> float:
        return self.bbox[2]

    @property
    def bottom(self) -> float:
        return self.bbox[3]


def _union_bbox(bboxes: list[BBox]) -> BBox:
    return (
        min(b[0] for b in bboxes),
        min(b[1] for b in bboxes),
        max(b[2] for b in bboxes),
        max(b[3] for b in bboxes),
    )


def _join_spans_preserve(spans: list[Span]) -> str:
    if not spans:
        return ""
    parts: list[str] = [spans[0].text]
    prev = spans[0]
    for cur in spans[1:]:
        gap = cur.bbox[0] - prev.bbox[2]
        ref = max(prev.size, cur.size, 8.0)
        if gap > 0.25 * ref and parts[-1] and not parts[-1].endswith(" ") and not cur.text.startswith(" "):
            parts.append(" ")
        parts.append(cur.text)
        prev = cur
    return "".join(parts).strip()


class DisplayEquationDetector:
    """Detects numbered and unnumbered display equations with baseline clustering and needs_ocr scoring."""

    def __init__(self, extraction_cfg: dict[str, Any] | None = None, math_cfg: dict[str, Any] | None = None):
        loader = ConfigLoader()
        ecfg = extraction_cfg if extraction_cfg is not None else loader.load("extraction.yaml").get("math", {})
        mcfg = math_cfg if math_cfg is not None else loader.load("math_patterns.yaml")

        self._tag_min_x1_ratio = float(ecfg.get("tag_min_x1_ratio", 0.72))
        self._baseline_ratio = float(ecfg.get("baseline_cluster_ratio", 0.45))
        self._multiline_gap_ratio = float(ecfg.get("multiline_gap_ratio", 1.6))
        self._unnumbered_indent = float(ecfg.get("unnumbered_indent_pt", 15.0))
        self._unnumbered_gap_ratio = float(ecfg.get("unnumbered_gap_ratio", 0.4))
        self._tall_multiline_ratio = float(ecfg.get("tall_multiline_ratio", 2.2))
        self._max_english_words = int(ecfg.get("max_english_words_in_display", 2))

        self._tag_re = re.compile(mcfg.get("equation_tag_regex", r"\(((?:[1-9]\d*|[A-Z])(?:\.\d+)*)\)\s*$"))
        deg = mcfg.get("degradation_patterns", {})
        self._radical_re = re.compile(deg.get("radical_fragment", r"\bv\s+u(?:\s+u)*\s+t\b"))
        self._flattened_op_re = re.compile(deg.get("flattened_big_op", r"(?:^|\s)[ZXP]\s*(?:∞|\\infty|\d|t\s*=|i\s*=|n\s*=)"))
        self._accent_garble_re = re.compile(deg.get("accent_garble", r"(?:exp\(\s*d\b|\b[A-Za-z]\s*\^\s*$)"))

        self._common_english = load_dictionary("math_fonts").COMMON_ENGLISH_WORDS

    def detect(self, doc: Document) -> list[MathObject]:
        page_section = self._build_section_map(doc)
        results: list[MathObject] = []
        eq_counter = 0

        for page in doc.pages:
            body_size = page.body_font_size or doc.body_font_size or 10.0
            rows = self._cluster_rows(page, body_size)
            if not rows:
                continue
            body_left = self._estimate_body_left(page)
            consumed: set[int] = set()

            # Pass 1: Right-margin tagged display equations (Anchor 1)
            for idx, row in enumerate(rows):
                if idx in consumed or row.tag is None:
                    continue
                if self._looks_like_prose_with_paren(row):
                    continue
                group_indices = self._expand_bidirectional(rows, consumed, idx, body_size, body_left)
                for g_idx in group_indices:
                    consumed.add(g_idx)
                obj = self._build_math_object(doc.paper_id, page, rows, group_indices, row.tag, row.tag_bbox, body_size, page_section, eq_counter + 1)
                if obj is not None:
                    eq_counter += 1
                    results.append(obj)

            # Pass 2: Unnumbered centered display equations (Anchor 2)
            for idx, row in enumerate(rows):
                if idx in consumed:
                    continue
                if not self._is_unnumbered_anchor(rows, idx, body_size, body_left):
                    continue
                group_indices = self._expand_bidirectional(rows, consumed, idx, body_size, body_left)
                for g_idx in group_indices:
                    consumed.add(g_idx)
                obj = self._build_math_object(doc.paper_id, page, rows, group_indices, None, None, body_size, page_section, eq_counter + 1)
                if obj is not None:
                    eq_counter += 1
                    results.append(obj)

        results.sort(key=lambda m: (m.page, m.bbox[1], m.bbox[0]))
        for idx, obj in enumerate(results, 1):
            obj.math_id = f"EQ-{idx:03d}"
        return results

    def _cluster_rows(self, page: Page, body_size: float) -> list[_LogicalRow]:
        spans: list[Span] = []
        for block in page.blocks:
            if block.kind in _EXCLUDED_BLOCK_KINDS:
                continue
            for line in block.lines:
                for span in line.spans:
                    if span.text.strip():
                        spans.append(span)
        if not spans:
            return []

        spans.sort(key=lambda s: ((s.bbox[1] + s.bbox[3]) / 2.0, s.bbox[0]))
        y_tol = self._baseline_ratio * body_size
        clusters: list[list[Span]] = []
        cluster_centers: list[float] = []

        for span in spans:
            cy = (span.bbox[1] + span.bbox[3]) / 2.0
            if clusters and abs(cy - cluster_centers[-1]) <= y_tol:
                clusters[-1].append(span)
                # Keep running average center
                cluster_centers[-1] = sum((s.bbox[1] + s.bbox[3]) / 2.0 for s in clusters[-1]) / len(clusters[-1])
            else:
                clusters.append([span])
                cluster_centers.append(cy)

        rows: list[_LogicalRow] = []
        for cluster in clusters:
            cluster.sort(key=lambda s: s.bbox[0])
            raw_text = _join_spans_preserve(cluster)
            if not raw_text:
                continue
            bbox = _union_bbox([s.bbox for s in cluster])
            tag, tag_bbox, body_spans = self._extract_right_margin_tag(cluster, page.width)
            body_text = _join_spans_preserve(body_spans) if tag is not None else raw_text
            rows.append(
                _LogicalRow(
                    page=page.page,
                    spans=cluster,
                    text=re.sub(r"\s+", " ", raw_text).strip(),
                    raw_text=raw_text,
                    bbox=bbox,
                    has_math_font=any(s.is_math_font for s in body_spans),
                    has_big_op_font=any(s.is_big_op_font for s in body_spans),
                    tag=tag,
                    tag_bbox=tag_bbox,
                    body_text=body_text,
                    english_words=self._count_english(body_text),
                )
            )
        return rows

    def _extract_right_margin_tag(self, spans: list[Span], page_width: float) -> tuple[str | None, BBox | None, list[Span]]:
        last = spans[-1]
        if last.bbox[2] < self._tag_min_x1_ratio * page_width:
            return None, None, spans
        m = self._tag_re.search(last.text.strip())
        if not m:
            return None, None, spans
        inner = m.group(1)
        if len(inner) == 4 and inner.isdigit() and 1950 <= int(inner) <= 2035:
            return None, None, spans
        tag_str = f"({inner})"
        if last.text.strip() == tag_str:
            return tag_str, last.bbox, spans[:-1]
        # Tag was concatenated at the end of a span
        prefix = last.text[: m.start()].rstrip()
        if not prefix:
            return tag_str, last.bbox, spans[:-1]
        trimmed = Span(
            text=prefix,
            bbox=(last.bbox[0], last.bbox[1], max(last.bbox[0] + 1.0, last.bbox[2] - 25.0), last.bbox[3]),
            font=last.font,
            size=last.size,
            flags=last.flags,
            is_bold=last.is_bold,
            is_italic=last.is_italic,
            is_math_font=last.is_math_font,
            is_big_op_font=last.is_big_op_font,
        )
        tag_bbox = (max(last.bbox[0], last.bbox[2] - 25.0), last.bbox[1], last.bbox[2], last.bbox[3])
        return tag_str, tag_bbox, [*spans[:-1], trimmed]

    def _looks_like_prose_with_paren(self, row: _LogicalRow) -> bool:
        if not row.body_text:
            return False
        # Reject Likert / numbered inline scale lists like "Negative (2) Neutral (3) Positive (4) Very Positive (5)"
        if len(re.findall(r"\(\d+\)", row.text)) >= 3 and not row.has_math_font and not _MATH_OPERATOR_RE.search(row.body_text):
            return True
        return bool(row.english_words >= 5 and not row.has_math_font and not _MATH_OPERATOR_RE.search(row.body_text))

    def _is_unnumbered_anchor(self, rows: list[_LogicalRow], idx: int, body_size: float, body_left: float) -> bool:
        row = rows[idx]
        if not row.has_math_font or not _MATH_OPERATOR_RE.search(row.text):
            return False
        if row.english_words > self._max_english_words or len(row.text) < 5 or len(row.text) > 120:
            return False
        if row.left <= body_left + self._unnumbered_indent:
            return False
        min_gap = self._unnumbered_gap_ratio * body_size
        gap_above = (row.top - rows[idx - 1].bottom) if idx > 0 else min_gap + 1.0
        gap_below = (rows[idx + 1].top - row.bottom) if idx + 1 < len(rows) else min_gap + 1.0
        return gap_above >= min_gap or gap_below >= min_gap

    def _expand_bidirectional(self, rows: list[_LogicalRow], consumed: set[int], anchor_idx: int, body_size: float, body_left: float) -> list[int]:
        max_gap = self._multiline_gap_ratio * body_size
        indices = [anchor_idx]

        # Expand upward
        j = anchor_idx - 1
        while j >= 0 and j not in consumed:
            gap = rows[j + 1].top - rows[j].bottom
            if gap > max_gap or rows[j].tag is not None:
                break
            if not self._is_math_continuation_row(rows[j], body_left):
                break
            indices.insert(0, j)
            j -= 1

        # Expand downward
        k = anchor_idx + 1
        while k < len(rows) and k not in consumed:
            gap = rows[k].top - rows[k - 1].bottom
            if gap > max_gap or rows[k].tag is not None:
                break
            if not self._is_math_continuation_row(rows[k], body_left):
                break
            indices.append(k)
            k += 1

        return indices

    def _is_math_continuation_row(self, row: _LogicalRow, body_left: float) -> bool:
        text = row.body_text.strip()
        if not text:
            return False
        # Prose sentence starter/ending guard (e.g., "where y_t denotes..." or "takes the form")
        if row.english_words > self._max_english_words:
            return False
        low = text.lower()
        if low.startswith(("where ", "with ", "in (", "the ", "this ", "here ", "assumption ", "algorithm ", "theorem ", "proposition ", "table ", "figure ")):
            return False
        if _PROSE_END_RE.search(text) and row.left <= body_left + 10.0 and not row.has_math_font and not _MATH_OPERATOR_RE.search(text):
            return False
        if row.has_math_font or row.has_big_op_font:
            return True
        if _MATH_OPERATOR_RE.search(text):
            return True
        # Indented short denominator/constraint line (e.g. "T", "s.t. sum(w) = 1")
        return bool(row.left > body_left + 12.0 and len(text) <= 60 and row.english_words <= 1)

    def _build_math_object(self, paper_id: str, page: Page, rows: list[_LogicalRow], indices: list[int], tag: str | None, tag_bbox: BBox | None, body_size: float, page_section: dict[tuple[int, float], str], seq_num: int) -> MathObject | None:
        selected = [rows[i] for i in indices]
        body_lines = [r.body_text.strip() for r in selected if r.body_text.strip()]
        if not body_lines:
            return None

        raw_joined_unclean = "\n".join(body_lines)
        cleaned_raw = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]", "", raw_joined_unclean).strip()
        cleaned_raw = re.sub(r"[ \t]+", " ", cleaned_raw)
        if len(cleaned_raw) < 3:
            return None

        # Validate that equation actually looks mathematical (not stray short text)
        has_math_signal = (
            any(r.has_math_font or r.has_big_op_font for r in selected)
            or bool(_MATH_OPERATOR_RE.search(cleaned_raw))
            or tag is not None
        )
        if not has_math_signal:
            return None

        bbox = _union_bbox([r.bbox for r in selected])
        ocr_reasons = self._score_degradation(page, selected, raw_joined_unclean, bbox, body_size)

        first_idx, last_idx = indices[0], indices[-1]
        before_rows = rows[max(0, first_idx - 2) : first_idx]
        after_rows = rows[last_idx + 1 : min(len(rows), last_idx + 4)]
        context_before = " ".join(r.text for r in before_rows).strip()
        context_after = " ".join(r.text for r in after_rows).strip()

        section_heading = self._lookup_section(page.page, bbox[1], page_section)
        return MathObject(
            math_id=f"EQ-{seq_num:03d}",
            paper_id=paper_id,
            kind=MathKind.DISPLAY_EQUATION,
            tag=tag,
            raw_text=cleaned_raw,
            latex=None,
            page=page.page,
            page_end=page.page,
            section=section_heading,
            bbox=bbox,
            tag_bbox=tag_bbox,
            source_channel=SourceChannel.TEXT,
            needs_ocr=bool(ocr_reasons),
            ocr_reasons=ocr_reasons,
            context_before=context_before,
            context_after=context_after,
        )

    def _score_degradation(self, page: Page, rows: list[_LogicalRow], raw_text: str, bbox: BBox, body_size: float) -> list[str]:
        reasons: list[str] = []
        if any(r.has_big_op_font for r in rows):
            reasons.append("big_op_font")
        if any(0xE000 <= ord(ch) <= 0xF8FF or (ord(ch) < 0x20 and ch not in "\t\n\r") for ch in raw_text):
            reasons.append("private_use_glyph")
        if self._radical_re.search(raw_text):
            reasons.append("radical_fragment")
        if self._flattened_op_re.search(raw_text) or self._has_flattened_math_op_span(rows):
            reasons.append("flattened_big_op")
        if self._has_stacked_fraction_rule(page, bbox):
            reasons.append("stacked_fraction")
        if (bbox[3] - bbox[1]) > self._tall_multiline_ratio * body_size:
            reasons.append("tall_multiline")
        if self._accent_garble_re.search(raw_text):
            reasons.append("accent_garble")
        return reasons

    @staticmethod
    def _has_flattened_math_op_span(rows: list[_LogicalRow]) -> bool:
        for row in rows:
            for span in row.spans:
                if (span.is_math_font or span.is_big_op_font) and span.text.strip() in {"Z", "X", "P"}:
                    return True
        return False

    @staticmethod
    def _has_stacked_fraction_rule(page: Page, bbox: BBox) -> bool:
        disp_w = max(bbox[2] - bbox[0], 1.0)
        for rule in page.horizontal_rules:
            rw = rule[2] - rule[0]
            rh = rule[3] - rule[1]
            if rh > 2.0 or rw >= 0.65 * disp_w:
                continue
            if rule[0] >= bbox[0] - 8.0 and rule[2] <= bbox[2] + 8.0 and bbox[1] - 4.0 <= rule[1] <= bbox[3] + 4.0:
                return True
        return False

    def _count_english(self, text: str) -> int:
        words = [w.lower() for w in re.findall(r"[A-Za-z]{3,}", text)]
        return sum(1 for w in words if w in self._common_english)

    @staticmethod
    def _estimate_body_left(page: Page) -> float:
        prose_x0 = [b.bbox[0] for b in page.blocks if b.kind == BlockKind.PROSE and (b.bbox[2] - b.bbox[0]) > 0.25 * page.width]
        if not prose_x0:
            return 0.12 * page.width
        prose_x0.sort()
        return prose_x0[max(0, int(0.1 * len(prose_x0)))]

    @staticmethod
    def _build_section_map(doc: Document) -> dict[tuple[int, float], str]:
        mapping: dict[tuple[int, float], str] = {}
        for sec in doc.sections:
            for block in sec.blocks:
                mapping[(block.page, block.bbox[1])] = sec.heading
            if not sec.blocks:
                mapping[(sec.page_start, 0.0)] = sec.heading
        return mapping

    @staticmethod
    def _lookup_section(page: int, y: float, page_section: dict[tuple[int, float], str]) -> str:
        candidates = [(py, heading) for (p, py), heading in page_section.items() if p == page and py <= y + 10.0]
        if candidates:
            candidates.sort(key=lambda item: item[0])
            return candidates[-1][1]
        earlier = [(p, py, heading) for (p, py), heading in page_section.items() if p <= page]
        if earlier:
            earlier.sort(key=lambda item: (item[0], item[1]))
            return earlier[-1][2]
        return "Document"
