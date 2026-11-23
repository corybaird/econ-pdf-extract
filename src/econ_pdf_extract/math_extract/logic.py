from __future__ import annotations

import re
from typing import Any

from econ_pdf_extract.core.config import ConfigLoader
from econ_pdf_extract.core.models import (
    BBox,
    Block,
    BlockKind,
    Document,
    MathKind,
    MathObject,
    Section,
    SectionRole,
    SourceChannel,
)

_SKIP_ROLES = frozenset({SectionRole.FRONT_MATTER, SectionRole.REFERENCES})
_STEP_START_RE = re.compile(r"^(?:(?:\d+|Step\s+\d+|[ivxIVX]+)[.):]\s+|[-•*]\s+)")
_TAG_EXTRACT_RE = re.compile(r"^(?:Assumption|Algorithm|Proposition|Theorem|Lemma|Corollary|Definition)(?:\s+[A-Z0-9.]+)?", re.IGNORECASE)


def _union_bbox(bboxes: list[BBox]) -> BBox:
    return (
        min(b[0] for b in bboxes),
        min(b[1] for b in bboxes),
        max(b[2] for b in bboxes),
        max(b[3] for b in bboxes),
    )


class LogicExtractor:
    """Classifies display equations by math kind and extracts prose assumptions, algorithms, and theorems."""

    def __init__(self, math_cfg: dict[str, Any] | None = None):
        cfg = math_cfg if math_cfg is not None else ConfigLoader().load("math_patterns.yaml")
        cues = cfg.get("math_kind_cues", {})
        self._estimation_res = [re.compile(rx, re.IGNORECASE) for rx in cues.get("estimation_problem", [])]
        self._evaluation_res = [re.compile(rx, re.IGNORECASE) for rx in cues.get("evaluation_formula", [])]
        self._model_res = [re.compile(rx, re.IGNORECASE) for rx in cues.get("model_specification", [])]

        prose = cfg.get("prose_logic_patterns", {})
        self._assumption_re = re.compile(prose.get("assumption", r"^Assumption(?:\s+[A-Z0-9.]+)?(?:\s*[:.\(\-]|\s+[A-Z]|\s*$)"), re.IGNORECASE)
        self._algorithm_re = re.compile(prose.get("algorithm", r"^(?:(?:\d+(?:\.\d+)*\.?\s+)?(?:Suggested\s+)?Algorithm(?:\s+[A-Z0-9.]+)?(?:\s*[:.\-\(].*)?)$"), re.IGNORECASE)
        self._proposition_re = re.compile(prose.get("proposition", r"^(?:Proposition|Theorem|Lemma|Corollary)\s+[A-Z0-9.]+"), re.IGNORECASE)
        self._definition_re = re.compile(prose.get("definition", r"^Definition\s+[A-Z0-9.]+"), re.IGNORECASE)

    def classify_displays(self, displays: list[MathObject]) -> list[MathObject]:
        for obj in displays:
            if obj.kind != MathKind.DISPLAY_EQUATION:
                continue
            target = f"{obj.context_before} {obj.raw_text}".strip()
            if any(rx.search(target) for rx in self._estimation_res):
                obj.kind = MathKind.ESTIMATION_PROBLEM
            elif any(rx.search(target) for rx in self._evaluation_res):
                obj.kind = MathKind.EVALUATION_FORMULA
            elif any(rx.search(target) for rx in self._model_res):
                obj.kind = MathKind.MODEL_SPECIFICATION
        return displays

    def extract_prose_logic(self, doc: Document) -> list[MathObject]:
        extracted: list[MathObject] = []
        counters = {
            MathKind.ASSUMPTION: 0,
            MathKind.ALGORITHM: 0,
            MathKind.PROPOSITION: 0,
            MathKind.DEFINITION: 0,
        }
        prefixes = {
            MathKind.ASSUMPTION: "ASM",
            MathKind.ALGORITHM: "ALG",
            MathKind.PROPOSITION: "PRP",
            MathKind.DEFINITION: "DEF",
        }

        for sec in doc.sections:
            if sec.role in _SKIP_ROLES or sec.is_duplicate_front_matter:
                continue

            # Section-level algorithm (e.g., "2.4 Suggested Algorithm")
            if self._algorithm_re.match(sec.heading.strip()):
                prose_blocks = [b for b in sec.blocks if b.kind == BlockKind.PROSE]
                if prose_blocks:
                    counters[MathKind.ALGORITHM] += 1
                    extracted.append(self._make_algorithm_from_section(doc.paper_id, sec, prose_blocks, counters[MathKind.ALGORITHM]))
                continue

            blocks = [b for b in sec.blocks if b.kind == BlockKind.PROSE]
            i = 0
            while i < len(blocks):
                block = blocks[i]
                first_line = block.lines[0].text.strip() if block.lines else block.text.strip()
                if self._algorithm_re.match(first_line):
                    group = [block]
                    j = i + 1
                    while j < len(blocks) and self._is_algorithm_step(blocks[j]):
                        group.append(blocks[j])
                        j += 1
                    counters[MathKind.ALGORITHM] += 1
                    extracted.append(self._make_prose_object(doc.paper_id, sec, group, MathKind.ALGORITHM, f"ALG-{counters[MathKind.ALGORITHM]:03d}"))
                    i = j
                    continue

                kind = self._match_prose_kind(first_line)
                if kind is not None:
                    counters[kind] += 1
                    math_id = f"{prefixes[kind]}-{counters[kind]:03d}"
                    extracted.append(self._make_prose_object(doc.paper_id, sec, [block], kind, math_id))
                i += 1

        return extracted

    def _match_prose_kind(self, first_line: str) -> MathKind | None:
        if self._assumption_re.match(first_line):
            return MathKind.ASSUMPTION
        if self._proposition_re.match(first_line):
            return MathKind.PROPOSITION
        if self._definition_re.match(first_line):
            return MathKind.DEFINITION
        return None

    @staticmethod
    def _is_algorithm_step(block: Block) -> bool:
        text = block.text.strip()
        if not text:
            return False
        first = block.lines[0].text.strip() if block.lines else text
        return bool(_STEP_START_RE.match(first))

    @staticmethod
    def _make_algorithm_from_section(paper_id: str, sec: Section, blocks: list[Block], seq: int) -> MathObject:
        raw_text = "\n".join(b.text.strip() for b in blocks if b.text.strip())
        first_page = blocks[0].page
        page_bboxes = [b.bbox for b in blocks if b.page == first_page]
        return MathObject(
            math_id=f"ALG-{seq:03d}",
            paper_id=paper_id,
            kind=MathKind.ALGORITHM,
            tag=sec.heading,
            raw_text=raw_text,
            latex=None,
            page=first_page,
            page_end=max(b.page for b in blocks),
            section=sec.heading,
            bbox=_union_bbox(page_bboxes),
            source_channel=SourceChannel.TEXT,
            needs_ocr=False,
        )

    @staticmethod
    def _make_prose_object(paper_id: str, sec: Section, blocks: list[Block], kind: MathKind, math_id: str) -> MathObject:
        raw_text = "\n".join(b.text.strip() for b in blocks if b.text.strip())
        first_line = blocks[0].lines[0].text.strip() if blocks[0].lines else raw_text
        tag_match = _TAG_EXTRACT_RE.match(first_line)
        tag = tag_match.group(0).strip() if tag_match else None
        first_page = blocks[0].page
        page_bboxes = [b.bbox for b in blocks if b.page == first_page]
        return MathObject(
            math_id=math_id,
            paper_id=paper_id,
            kind=kind,
            tag=tag,
            raw_text=raw_text,
            latex=None,
            page=first_page,
            page_end=max(b.page for b in blocks),
            section=sec.heading,
            bbox=_union_bbox(page_bboxes),
            source_channel=SourceChannel.TEXT,
            needs_ocr=False,
        )
