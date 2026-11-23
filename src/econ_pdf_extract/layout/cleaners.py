from __future__ import annotations

import logging
import re
from collections import defaultdict
from typing import Any

from econ_pdf_extract.core.config import ConfigLoader
from econ_pdf_extract.core.models import BBox, Block, BlockKind, Document, Page

logger = logging.getLogger(__name__)

_PAGE_NUM_RE = re.compile(r"^(?:[-–—]\s*)?(?:page\s+)?(\d{1,4})(?:\s*[-–—])?$", re.IGNORECASE)
_MARGIN_NUM_RE = re.compile(r"^\d{1,3}$")
_CAPTION_START_RE = re.compile(
    r"^(?:Table|Figure|Fig\.|Chart|Panel)\s+(?:[A-Z]\.)?\d+[a-z]?(?:\s*[:.\u2014\u2013-]|\s+[A-Z]|\s*$)",
    re.IGNORECASE,
)
_CAPTION_PROSE_VERB_RE = re.compile(
    r"^(?:Table|Figure|Fig\.|Chart|Panel)\s+(?:[A-Z]\.)?\d+[a-z]?\s+"
    r"(?:shows?|presents?|reports?|summarizes?|displays?|illustrates?|depicts?|compares?|lists?|contains?|gives?|provides?|plots?|confirms?|reveals?|indicates?|suggests?|demonstrates?)\b",
    re.IGNORECASE,
)
_NOTES_PREFIX_RE = re.compile(r"^Notes?\s*[:.]", re.IGNORECASE)
_FOOTNOTE_MARKER_RE = re.compile(r"^(?:\d{1,2}\s+[A-Z]|[∗*†‡§]\s*[A-Za-z])")
_NUMERIC_TOKEN_RE = re.compile(r"^[(\[]?[+-]?\d+(?:[.,]\d+)?[*†‡§%]*[)\]]?$")
_ALPHA_WORD_RE = re.compile(r"^[a-z]{3,}$")


def _bbox_overlap_ratio(inner: BBox, outer: BBox) -> float:
    ix0 = max(inner[0], outer[0])
    iy0 = max(inner[1], outer[1])
    ix1 = min(inner[2], outer[2])
    iy1 = min(inner[3], outer[3])
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    inter = (ix1 - ix0) * (iy1 - iy0)
    area = max((inner[2] - inner[0]) * (inner[3] - inner[1]), 1.0)
    return inter / area


def _body_horizontal_bounds(page: Page) -> tuple[float, float]:
    prose_blocks = [
        b
        for b in page.blocks
        if b.kind == BlockKind.PROSE and (b.bbox[2] - b.bbox[0]) > 0.25 * page.width
    ]
    if not prose_blocks:
        return 0.12 * page.width, 0.88 * page.width
    x0s = sorted(b.bbox[0] for b in prose_blocks)
    x1s = sorted(b.bbox[2] for b in prose_blocks)
    left = x0s[max(0, int(0.1 * len(x0s)))]
    right = x1s[min(len(x1s) - 1, int(0.9 * len(x1s)))]
    return left, max(right, left + 0.4 * page.width)


class MarginNoiseFilter:
    """Tags margin line numbers and running headers/footers while parsing printed page numbers."""

    def __init__(self, cfg: dict[str, Any]):
        self._header_top_ratio = float(cfg.get("header_top_ratio", 0.05))
        self._footer_bottom_ratio = float(cfg.get("footer_bottom_ratio", 0.94))
        self._running_min_pages = int(cfg.get("running_header_min_pages", 3))
        self._running_y_tol = float(cfg.get("running_header_y_tolerance", 3.0))
        self._margin_left_ratio = float(cfg.get("margin_left_ratio", 0.12))
        self._margin_right_ratio = float(cfg.get("margin_right_ratio", 0.88))

    def apply(self, doc: Document) -> None:
        repeated_headers = self._find_repeated_headers(doc)
        for page in doc.pages:
            self._clean_page(page, repeated_headers)

    def _find_repeated_headers(self, doc: Document) -> set[tuple[str, int]]:
        occurrences: dict[tuple[str, int], set[int]] = defaultdict(set)
        tol = max(self._running_y_tol, 1.0)
        for page in doc.pages:
            for block in page.blocks:
                if block.bbox[3] < 0.10 * page.height or block.bbox[1] > 0.90 * page.height:
                    norm = re.sub(r"\s+", " ", block.text).strip().lower()
                    if not norm or _PAGE_NUM_RE.match(norm):
                        continue
                    y_bucket = round(block.bbox[1] / tol)
                    occurrences[(norm, y_bucket)].add(page.page)
        return {key for key, pages in occurrences.items() if len(pages) >= self._running_min_pages}

    def _clean_page(self, page: Page, repeated_headers: set[tuple[str, int]]) -> None:
        tol = max(self._running_y_tol, 1.0)
        for block in page.blocks:
            if block.kind != BlockKind.PROSE:
                continue
            text = block.text.strip()
            if not text:
                continue

            # Margin line numbers in outer strips (works for Letter and A4)
            in_left_strip = block.bbox[2] < self._margin_left_ratio * page.width
            in_right_strip = block.bbox[0] > self._margin_right_ratio * page.width
            if (in_left_strip or in_right_strip) and self._is_margin_number_block(block):
                block.kind = BlockKind.MARGIN_NOISE
                continue

            # Repeated running headers / footers
            norm = re.sub(r"\s+", " ", text).lower()
            y_bucket = round(block.bbox[1] / tol)
            if (block.bbox[3] < 0.10 * page.height or block.bbox[1] > 0.90 * page.height) and (norm, y_bucket) in repeated_headers:
                block.kind = BlockKind.HEADER_FOOTER
                continue

            # Top / bottom band page numbers and chrome
            in_header = block.bbox[3] < self._header_top_ratio * page.height
            in_footer = block.bbox[1] > self._footer_bottom_ratio * page.height
            if in_header or in_footer:
                m = _PAGE_NUM_RE.match(text)
                if m:
                    page_num = int(m.group(1))
                    if page.printed_page is None or in_footer:
                        page.printed_page = page_num
                    block.kind = BlockKind.HEADER_FOOTER
                    continue
                if len(block.lines) <= 2 and len(text) <= 120:
                    block.kind = BlockKind.HEADER_FOOTER
                    continue

            # Strip inline-merged left-margin line numbers from prose blocks
            self._strip_inline_margin_numbers(block, page.width)

    @staticmethod
    def _is_margin_number_block(block: Block) -> bool:
        tokens = [t for t in block.text.split() if t]
        return bool(tokens) and all(_MARGIN_NUM_RE.match(tok) for tok in tokens)

    def _strip_inline_margin_numbers(self, block: Block, page_width: float) -> None:
        left_cutoff = 0.095 * page_width
        changed = False
        kept_lines = []
        for line in block.lines:
            if line.bbox[2] < left_cutoff and _MARGIN_NUM_RE.match(line.text.strip()):
                changed = True
                continue
            if (
                len(line.spans) >= 2
                and line.spans[0].bbox[2] < left_cutoff
                and _MARGIN_NUM_RE.match(line.spans[0].text.strip())
                and line.spans[1].bbox[0] > 0.12 * page_width
            ):
                line.spans = line.spans[1:]
                line.text = "".join(s.text for s in line.spans).strip()
                changed = True
            kept_lines.append(line)
        if changed:
            block.lines = kept_lines
            block.text = "\n".join(line.text for line in kept_lines).strip()


class TableCaptionFilter:
    """Tags table/figure captions and table body blocks (booktabs, shaded, borderless)."""

    def __init__(self, cfg: dict[str, Any]):
        self._full_rule_ratio = float(cfg.get("table_full_rule_width_ratio", 0.65))
        self._num_token_ratio = float(cfg.get("table_numeric_token_ratio", 0.45))
        self._max_eng_ratio = float(cfg.get("table_max_english_ratio", 0.35))
        self._min_lines = int(cfg.get("table_min_lines", 3))

    def apply(self, doc: Document) -> None:
        for page in doc.pages:
            self._clean_page(page)

    def _clean_page(self, page: Page) -> None:
        body_left, body_right = _body_horizontal_bounds(page)
        text_width = max(body_right - body_left, 0.5 * page.width)

        # 1. Tag obvious Table / Figure captions first
        caption_blocks: list[Block] = []
        for block in page.blocks:
            if block.kind != BlockKind.PROSE:
                continue
            first_line = block.lines[0].text.strip() if block.lines else block.text.strip()
            if self._is_caption(first_line, block):
                block.kind = BlockKind.CAPTION
                caption_blocks.append(block)

        # 2. Collect geometric table regions (PyMuPDF find_tables + booktabs rule bands + shaded grids)
        table_regions: list[BBox] = list(page.table_bboxes)
        table_regions.extend(self._rule_band_regions(page, text_width))
        table_regions.extend(self._shaded_grid_regions(page))

        for block in page.blocks:
            if block.kind != BlockKind.PROSE:
                continue
            if any(_bbox_overlap_ratio(block.bbox, region) >= 0.40 for region in table_regions) and not self._looks_like_long_prose_paragraph(block):
                block.kind = BlockKind.TABLE

        # 3. Borderless numeric-density fallback (especially directly below a Table caption)
        table_caption_ys = [b.bbox[3] for b in caption_blocks if b.text.strip().lower().startswith("table")]
        for block in page.blocks:
            if block.kind != BlockKind.PROSE:
                continue
            near_table_caption = any(-5.0 <= (block.bbox[1] - cy) <= 45.0 for cy in table_caption_ys)
            if (len(block.lines) >= self._min_lines or near_table_caption) and self._is_numeric_table_block(block):
                block.kind = BlockKind.TABLE

        # 4. Expand to adjacent short table header/row blocks and table notes
        table_blocks = [b for b in page.blocks if b.kind == BlockKind.TABLE]
        if table_blocks:
            for block in page.blocks:
                if block.kind != BlockKind.PROSE:
                    continue
                if _NOTES_PREFIX_RE.match(block.text.strip()) and any(-5.0 <= (block.bbox[1] - tb.bbox[3]) <= 40.0 for tb in table_blocks):
                    block.kind = BlockKind.CAPTION
                    continue
                if (
                    len(block.lines) <= 2
                    and len(block.text) <= 100
                    and "." not in block.text
                    and any(-18.0 <= (tb.bbox[1] - block.bbox[3]) <= 18.0 for tb in table_blocks)
                ):
                    num_ratio, eng_ratio = self._token_ratios(block.text)
                    if num_ratio >= 0.35 or (eng_ratio < 0.35 and len(block.text.split()) >= 3):
                        block.kind = BlockKind.TABLE

        # Also tag Notes directly after a Figure/Table caption
        if caption_blocks:
            for block in page.blocks:
                if block.kind != BlockKind.PROSE:
                    continue
                if _NOTES_PREFIX_RE.match(block.text.strip()) and any(-5.0 <= (block.bbox[1] - cb.bbox[3]) <= 35.0 for cb in caption_blocks):
                    block.kind = BlockKind.CAPTION

    @staticmethod
    def _is_caption(first_line: str, block: Block) -> bool:
        if _CAPTION_PROSE_VERB_RE.match(first_line):
            return False
        if not _CAPTION_START_RE.match(first_line):
            return False
        # Require either explicit separator (: . — -) or short/bold title-like block
        has_sep = bool(re.match(r"^(?:Table|Figure|Fig\.|Chart|Panel)\s+(?:[A-Z]\.)?\d+[a-z]?\s*[:.\u2014\u2013-]", first_line, re.IGNORECASE))
        if has_sep:
            return True
        return block.is_bold or len(block.lines) <= 3

    def _rule_band_regions(self, page: Page, text_width: float) -> list[BBox]:
        full_rules = sorted(
            [r for r in page.horizontal_rules if (r[2] - r[0]) >= self._full_rule_ratio * text_width],
            key=lambda r: r[1],
        )
        if len(full_rules) < 2:
            return []

        # Cluster full-width rules separated by <= 0.45 * page.height into table groups
        groups: list[list[BBox]] = [[full_rules[0]]]
        for rule in full_rules[1:]:
            if rule[1] - groups[-1][-1][1] <= 0.45 * page.height:
                groups[-1].append(rule)
            else:
                groups.append([rule])

        regions: list[BBox] = []
        for grp in groups:
            if len(grp) < 2:
                continue
            top_y = grp[0][1]
            bot_y = grp[-1][3]
            if bot_y - top_y < 14.0 or bot_y - top_y > 0.78 * page.height:
                continue
            x0 = min(r[0] for r in grp) - 5.0
            x1 = max(r[2] for r in grp) + 5.0
            enclosed = [
                b
                for b in page.blocks
                if b.kind == BlockKind.PROSE and top_y - 4.0 <= (b.bbox[1] + b.bbox[3]) / 2 <= bot_y + 4.0
            ]
            if not enclosed:
                continue
            combined_text = " ".join(b.text for b in enclosed)
            num_ratio, eng_ratio = self._token_ratios(combined_text)
            if num_ratio >= 0.25 or eng_ratio < 0.45:
                regions.append((x0, top_y - 2.0, x1, bot_y + 2.0))
        return regions

    @staticmethod
    def _shaded_grid_regions(page: Page) -> list[BBox]:
        if len(page.filled_rects) < 4:
            return []
        rects = sorted(page.filled_rects, key=lambda r: (r[1], r[0]))
        clusters: list[list[BBox]] = []
        for rect in rects:
            placed = False
            for cluster in clusters:
                cy0 = min(r[1] for r in cluster)
                cy1 = max(r[3] for r in cluster)
                if rect[1] <= cy1 + 25.0 and rect[3] >= cy0 - 25.0:
                    cluster.append(rect)
                    placed = True
                    break
            if not placed:
                clusters.append([rect])

        regions: list[BBox] = []
        for cluster in clusters:
            if len(cluster) < 4:
                continue
            regions.append(
                (
                    min(r[0] for r in cluster) - 2.0,
                    min(r[1] for r in cluster) - 2.0,
                    max(r[2] for r in cluster) + 2.0,
                    max(r[3] for r in cluster) + 2.0,
                )
            )
        return regions

    def _is_numeric_table_block(self, block: Block) -> bool:
        num_ratio, eng_ratio = self._token_ratios(block.text)
        return num_ratio >= self._num_token_ratio and eng_ratio < self._max_eng_ratio

    @staticmethod
    def _token_ratios(text: str) -> tuple[float, float]:
        tokens = text.split()
        if not tokens:
            return 0.0, 0.0
        numeric = sum(1 for tok in tokens if _NUMERIC_TOKEN_RE.match(tok))
        english = sum(1 for tok in tokens if _ALPHA_WORD_RE.match(tok.strip(".,;:()[]\"'")))
        total = len(tokens)
        return numeric / total, english / total

    @staticmethod
    def _looks_like_long_prose_paragraph(block: Block) -> bool:
        tokens = block.text.split()
        if len(tokens) < 25:
            return False
        num_ratio, eng_ratio = TableCaptionFilter._token_ratios(block.text)
        return eng_ratio >= 0.55 and num_ratio < 0.15


class FootnoteFilter:
    """Tags footnote blocks via separator rules (including above bottom tables) or small-font fallback."""

    def __init__(self, cfg: dict[str, Any]):
        self._rule_max_h = float(cfg.get("footnote_rule_max_height", 2.0))
        self._rule_min_w_ratio = float(cfg.get("footnote_rule_min_width_ratio", 0.10))
        self._rule_max_w_ratio = float(cfg.get("footnote_rule_max_width_ratio", 0.55))
        self._rule_left_tol = float(cfg.get("footnote_rule_left_tolerance", 25.0))
        self._rule_min_y_ratio = float(cfg.get("footnote_rule_min_y_ratio", 0.35))
        self._size_delta = float(cfg.get("footnote_size_delta", 0.6))
        self._fallback_y_ratio = float(cfg.get("footnote_fallback_y_ratio", 0.65))
        self._fallback_size_delta = float(cfg.get("footnote_fallback_size_delta", 1.0))

    def apply(self, doc: Document) -> None:
        for page in doc.pages:
            self._clean_page(page)

    def _clean_page(self, page: Page) -> None:
        body_left, body_right = _body_horizontal_bounds(page)
        text_width = max(body_right - body_left, 0.5 * page.width)
        table_bboxes = [b.bbox for b in page.blocks if b.kind == BlockKind.TABLE] + list(page.table_bboxes)

        sep_y = self._find_separator_rule_y(page, body_left, text_width, table_bboxes)
        ordered = sorted(page.blocks, key=lambda b: (b.bbox[1], b.bbox[0]))

        if sep_y is not None:
            in_footnote_zone = False
            for block in ordered:
                if block.bbox[1] < sep_y - 2.0:
                    continue
                if block.kind in (BlockKind.TABLE, BlockKind.HEADER_FOOTER, BlockKind.CAPTION):
                    if in_footnote_zone:
                        break
                    continue
                if block.kind != BlockKind.PROSE:
                    continue
                if self._matches_rule_footnote(block, page.body_font_size) or in_footnote_zone:
                    block.kind = BlockKind.FOOTNOTE
                    in_footnote_zone = True
            return

        # Tier 2: No-rule fallback in bottom band
        in_fallback_fn = False
        for block in ordered:
            if block.bbox[1] <= self._fallback_y_ratio * page.height:
                continue
            if block.kind in (BlockKind.TABLE, BlockKind.HEADER_FOOTER):
                if in_fallback_fn:
                    break
                continue
            if block.kind != BlockKind.PROSE:
                continue
            is_small = block.modal_size <= page.body_font_size - self._fallback_size_delta
            if is_small and (self._has_footnote_marker(block) or in_fallback_fn):
                block.kind = BlockKind.FOOTNOTE
                in_fallback_fn = True

    def _find_separator_rule_y(self, page: Page, body_left: float, text_width: float, table_bboxes: list[BBox]) -> float | None:
        candidates: list[float] = []
        for rule in page.horizontal_rules:
            rw = rule[2] - rule[0]
            rh = rule[3] - rule[1]
            if rh > self._rule_max_h:
                continue
            if not (self._rule_min_w_ratio * text_width <= rw <= self._rule_max_w_ratio * text_width):
                continue
            if abs(rule[0] - body_left) > self._rule_left_tol:
                continue
            if rule[1] < self._rule_min_y_ratio * page.height:
                continue
            if any(tb[1] - 4.0 <= rule[1] <= tb[3] + 4.0 for tb in table_bboxes):
                continue
            candidates.append(rule[1])
        return min(candidates) if candidates else None

    def _matches_rule_footnote(self, block: Block, body_font_size: float) -> bool:
        if block.modal_size <= body_font_size - self._size_delta:
            return True
        return self._has_footnote_marker(block)

    @staticmethod
    def _has_footnote_marker(block: Block) -> bool:
        if _FOOTNOTE_MARKER_RE.match(block.text.strip()):
            return True
        if block.lines and block.lines[0].spans:
            first_span = block.lines[0].spans[0]
            first_text = first_span.text.strip()
            if first_text.isdigit() and len(first_text) <= 2 and first_span.size < block.modal_size:
                return True
        return False


class LayoutCleaner:
    """Orchestrates margin noise, table/caption, and footnote tagging across a Document."""

    def __init__(self, config: dict[str, Any] | None = None):
        cfg = config if config is not None else ConfigLoader().load("extraction.yaml").get("layout", {})
        self._margin_filter = MarginNoiseFilter(cfg)
        self._table_filter = TableCaptionFilter(cfg)
        self._footnote_filter = FootnoteFilter(cfg)

    def clean(self, doc: Document) -> Document:
        self._margin_filter.apply(doc)
        self._table_filter.apply(doc)
        self._footnote_filter.apply(doc)
        return doc
