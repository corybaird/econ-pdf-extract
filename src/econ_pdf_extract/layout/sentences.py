from __future__ import annotations

import re
from typing import Any

from econ_pdf_extract.core.config import ConfigLoader
from econ_pdf_extract.core.models import (
    BBox,
    BlockKind,
    Document,
    Line,
    Section,
    Sentence,
)
from econ_pdf_extract.core.paths import load_dictionary

_LIGATURE_MAP = str.maketrans(
    {
        "\ufb00": "ff",
        "\ufb01": "fi",
        "\ufb02": "fl",
        "\ufb03": "ffi",
        "\ufb04": "ffl",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "-",
        "\u00a0": " ",
    }
)
_INLINE_SPLIT_DECIMAL_RE = re.compile(r"(\d)\s+\.\s*(\d)")
_YEAR_FOLLOW_RE = re.compile(r"^(?:19|20)\d{2}[a-z]?(?:[\)\],;\s]|$)")
_SINGLE_INITIAL_RE = re.compile(r"(?:^|[\s(])[A-Z]\.$")
_URL_PREFIX_RE = re.compile(r"^(?:https?://|doi:|url:)", re.IGNORECASE)
_END_HYPHEN_WORD_RE = re.compile(r"([A-Za-z]+)-$")
_END_SPLIT_DEC_RE = re.compile(r"(\d)\s*\.$")


def _normalize_line_text(text: str) -> str:
    cleaned = text.translate(_LIGATURE_MAP)
    cleaned = _INLINE_SPLIT_DECIMAL_RE.sub(r"\1.\2", cleaned)
    return re.sub(r"[ \t]+", " ", cleaned).strip()


def _union_bbox(bboxes: list[BBox]) -> BBox:
    return (
        min(b[0] for b in bboxes),
        min(b[1] for b in bboxes),
        max(b[2] for b in bboxes),
        max(b[3] for b in bboxes),
    )


class SentenceSegmenter:
    """Segments section prose into cleaned sentences while tracking true line-level page and bbox."""

    def __init__(self, config: dict[str, Any] | None = None):
        cfg = config if config is not None else ConfigLoader().load("extraction.yaml").get("layout", {})
        self._min_length = int(cfg.get("min_sentence_length", 25))
        abbreviations = load_dictionary("abbreviations")
        self._abbreviations = abbreviations.NON_TERMINAL_ABBREVIATIONS
        self._keep_hyphen_prefixes = abbreviations.KEEP_HYPHEN_PREFIXES

    def segment(self, doc: Document) -> Document:
        all_sentences: list[Sentence] = []
        for section in doc.sections:
            all_sentences.extend(self._segment_section(section))
        doc.sentences = all_sentences
        return doc

    def _segment_section(self, section: Section) -> list[Sentence]:
        stream_chars: list[str] = []
        char_lines: list[Line] = []
        char_blocks: list[str] = []

        for block in section.blocks:
            if block.kind != BlockKind.PROSE:
                continue
            for line in block.lines:
                norm_text = _normalize_line_text(line.text)
                if not norm_text:
                    continue
                self._append_line(stream_chars, char_lines, char_blocks, norm_text, line, block.block_id)

        if not stream_chars:
            return []

        stream = "".join(stream_chars)
        spans = self._split_spans(stream)
        sentences: list[Sentence] = []
        sent_idx = 0

        for start, end in spans:
            while start < end and stream[start].isspace():
                start += 1
            while end > start and stream[end - 1].isspace():
                end -= 1
            if end <= start:
                continue
            text = re.sub(r"\s+", " ", stream[start:end]).strip()
            if len(text) < self._min_length or _URL_PREFIX_RE.match(text):
                continue

            seen_line_ids: set[int] = set()
            lines_in_sent: list[Line] = []
            block_ids: list[str] = []
            seen_blocks: set[str] = set()
            for pos in range(start, end):
                ln = char_lines[pos]
                if id(ln) not in seen_line_ids:
                    seen_line_ids.add(id(ln))
                    lines_in_sent.append(ln)
                bid = char_blocks[pos]
                if bid not in seen_blocks:
                    seen_blocks.add(bid)
                    block_ids.append(bid)

            start_page = lines_in_sent[0].page
            end_page = max(ln.page for ln in lines_in_sent)
            page_bboxes = [ln.bbox for ln in lines_in_sent if ln.page == start_page]
            bbox = _union_bbox(page_bboxes) if page_bboxes else lines_in_sent[0].bbox
            math_tokens = self._collect_math_tokens(lines_in_sent)

            sent_idx += 1
            sentences.append(
                Sentence(
                    sentence_id=f"{section.section_id}_sent{sent_idx:03d}",
                    text=text,
                    page=start_page,
                    page_end=end_page,
                    bbox=bbox,
                    section_id=section.section_id,
                    section_heading=section.heading,
                    section_role=section.role,
                    block_ids=block_ids,
                    math_tokens=math_tokens,
                )
            )
        return sentences

    def _append_line(self, chars: list[str], char_lines: list[Line], char_blocks: list[str], text: str, line: Line, block_id: str) -> None:
        if chars:
            tail = "".join(chars[-32:])
            # Case 1: Split decimal across line break ("3 ." + "55%.")
            dec_match = _END_SPLIT_DEC_RE.search(tail)
            if dec_match and text[0].isdigit():
                # Strip spaces between the digit and the trailing dot if any
                dot_idx = len(chars) - 1
                while dot_idx > 0 and chars[dot_idx - 1] == " ":
                    chars.pop(dot_idx - 1)
                    char_lines.pop(dot_idx - 1)
                    char_blocks.pop(dot_idx - 1)
                    dot_idx -= 1
            # Case 2: End-of-line word hyphenation
            elif (hyph_match := _END_HYPHEN_WORD_RE.search(tail)) and text[0].islower():
                prefix = hyph_match.group(1).lower()
                if prefix not in self._keep_hyphen_prefixes:
                    chars.pop()
                    char_lines.pop()
                    char_blocks.pop()
            else:
                chars.append(" ")
                char_lines.append(char_lines[-1])
                char_blocks.append(char_blocks[-1])

        for ch in text:
            chars.append(ch)
            char_lines.append(line)
            char_blocks.append(block_id)

    def _split_spans(self, text: str) -> list[tuple[int, int]]:
        spans: list[tuple[int, int]] = []
        n = len(text)
        start = 0
        paren_depth = 0
        bracket_depth = 0
        open_since = -1
        i = 0

        while i < n:
            ch = text[i]
            if ch == "(":
                if paren_depth == 0:
                    open_since = i
                paren_depth += 1
            elif ch == ")":
                paren_depth = max(0, paren_depth - 1)
            elif ch == "[":
                if bracket_depth == 0:
                    open_since = i
                bracket_depth += 1
            elif ch == "]":
                bracket_depth = max(0, bracket_depth - 1)

            # Guard against stray unmatched open delimiter swallowing paragraphs
            if (paren_depth > 0 or bracket_depth > 0) and open_since >= 0 and (i - open_since) > 350:
                paren_depth = 0
                bracket_depth = 0
                open_since = -1

            if ch in ".!?" and paren_depth == 0 and bracket_depth == 0:
                end_punct = i
                while end_punct + 1 < n and text[end_punct + 1] in "\"')]}":
                    end_punct += 1
                next_ws = end_punct + 1
                if next_ws < n and text[next_ws].isspace():
                    next_char = next_ws
                    while next_char < n and text[next_char].isspace():
                        next_char += 1
                    if next_char < n and self._should_split(text, i, next_char):
                        spans.append((start, end_punct + 1))
                        start = next_char
                        i = next_char
                        continue
            i += 1

        if start < n:
            spans.append((start, n))
        return spans

    def _should_split(self, text: str, dot_idx: int, next_idx: int) -> bool:
        next_ch = text[next_idx]
        if next_ch.islower():
            return False
        if not (next_ch.isupper() or next_ch in "\"'(["):
            return False

        ch = text[dot_idx]
        if ch in "!?":
            return True

        # Check decimal surrounded by digits
        if dot_idx > 0 and text[dot_idx - 1].isdigit() and next_ch.isdigit():
            return False

        # Check trailing word before dot against non-terminal abbreviations
        prefix_window = text[max(0, dot_idx - 20) : dot_idx + 1]
        token_match = re.search(r"([A-Za-z][A-Za-z.]*\.)$", prefix_window)
        if token_match:
            tok = token_match.group(1).lower()
            if tok in self._abbreviations:
                return False
            # Handle multi-dot abbreviations like "e.g." / "u.s." / "s.t."
            if len(tok) <= 4 and tok.count(".") >= 2:
                return False

        if _SINGLE_INITIAL_RE.search(prefix_window):
            return False

        # Protect citation year right after period ("et al. 2007")
        return not _YEAR_FOLLOW_RE.match(text[next_idx : next_idx + 10])

    @staticmethod
    def _collect_math_tokens(lines: list[Line]) -> list[str]:
        tokens: list[str] = []
        seen: set[str] = set()
        for line in lines:
            for span in line.spans:
                if not span.is_math_font:
                    continue
                for raw_tok in span.text.split():
                    tok = raw_tok.strip(".,;:()[]{}")
                    if tok and tok not in seen:
                        seen.add(tok)
                        tokens.append(tok)
        return tokens
