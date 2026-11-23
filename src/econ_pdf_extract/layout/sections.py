from __future__ import annotations

import re
from typing import Any

from econ_pdf_extract.core.config import ConfigLoader
from econ_pdf_extract.core.models import (
    Block,
    BlockKind,
    Document,
    Section,
    SectionRole,
)

SECTION_NUM_RE = re.compile(r"^(?:[1-9]\d*(?:\.\d+)*|[A-Z])$")
SECTION_TITLE_RE = re.compile(r"^[A-Z][A-Za-z0-9\s,:'\u2019\(\)\-\/]{2,80}$")
NUM_HEADING_RE = re.compile(r"^[1-9]\d*(?:\.\d+)*\.?\s+[A-Z][A-Za-z0-9\s,:'\u2019\(\)\-\/]{2,80}$")
ALPHA_HEADING_RE = re.compile(r"^[A-Z](?:\.\d+)*\.\s+[A-Z][A-Za-z0-9\s,:'\u2019\(\)\-\/]{2,80}$")
STANDALONE_HEADING_RE = re.compile(
    r"^(?:Abstract|Introduction|Conclusion|Conclusions|Concluding\s+Remarks|References|Bibliography|Declarations|Acknowledgements?|Discussion|Summary)$",
    re.IGNORECASE,
)
APPENDIX_HEADING_RE = re.compile(r"^(?:Appendix(?:\s+[A-Z0-9]+)?|Appendices)(?::.*)?$", re.IGNORECASE)
BOLD_TITLE_RE = re.compile(
    r"^(?:(?!(?:Table|Figure|Fig\.|Chart|Panel|Notes?|Assumption|Theorem|Proposition|Lemma|Corollary|Definition|Algorithm)\b)[A-Z0-9])"
    r"[A-Za-z0-9 ,:'\u2019\(\)\-\/\.]{2,69}[A-Za-z0-9\!\?\.]+$"
)
FIRST_BODY_SECTION_RE = re.compile(r"^(?:1\.?\s+[A-Z]|Introduction$)", re.IGNORECASE)
MAJOR_NUM_RE = re.compile(r"^([1-9]\d*|[A-Z])(?:\.\d+)*\.?\s+")
ABSTRACT_RE = re.compile(r"^abstract\b", re.IGNORECASE)

_ROLE_PRIORITY = (
    SectionRole.FRONT_MATTER,
    SectionRole.REFERENCES,
    SectionRole.ABSTRACT,
    SectionRole.INTRODUCTION,
    SectionRole.CONCLUSION,
    SectionRole.APPENDIX,
    SectionRole.ROBUSTNESS,
    SectionRole.RESULTS,
    SectionRole.DATA,
    SectionRole.METHODOLOGY,
)


class SectionBuilder:
    """Detects headings, resolves duplicate front matter, and classifies SectionRole."""

    def __init__(self, config: dict[str, Any] | None = None):
        cfg = config if config is not None else ConfigLoader().load("extraction.yaml").get("sections", {})
        raw_roles = cfg.get("role_patterns", {})
        self._role_patterns: dict[SectionRole, list[re.Pattern[str]]] = {}
        for role in _ROLE_PRIORITY:
            patterns = raw_roles.get(role.value, [])
            self._role_patterns[role] = [re.compile(rx, re.IGNORECASE) for rx in patterns]

    def build(self, doc: Document) -> Document:
        raw_sections: list[Section] = []
        current_heading: str | None = None
        current_page_start = 1
        current_blocks: list[Block] = []
        pre_heading_blocks: list[Block] = []

        in_references = False
        for page in doc.pages:
            body_size = page.body_font_size or doc.body_font_size or 10.0
            for block in page.blocks:
                if block.kind != BlockKind.PROSE:
                    continue
                heading = self._detect_heading(block, body_size)
                if heading is not None and in_references and not (APPENDIX_HEADING_RE.match(heading) or ALPHA_HEADING_RE.match(heading)):
                    heading = None
                if heading is not None:
                    # Skip exact duplicate heading on same page with no content between (overprint)
                    if heading == current_heading and not current_blocks and page.page == current_page_start:
                        block.kind = BlockKind.HEADING
                        continue
                    if current_heading is not None:
                        raw_sections.append(self._make_section(current_heading, current_page_start, current_blocks))
                    elif pre_heading_blocks:
                        raw_sections.append(self._make_section("Front Matter", pre_heading_blocks[0].page, pre_heading_blocks, force_role=SectionRole.FRONT_MATTER))
                        pre_heading_blocks = []
                    block.kind = BlockKind.HEADING
                    current_heading = heading
                    current_page_start = page.page
                    current_blocks = []
                    if self._classify_role(heading) == SectionRole.REFERENCES:
                        in_references = True
                    elif APPENDIX_HEADING_RE.match(heading) or ALPHA_HEADING_RE.match(heading):
                        in_references = False
                elif current_heading is not None:
                    current_blocks.append(block)
                else:
                    pre_heading_blocks.append(block)

        if current_heading is not None:
            raw_sections.append(self._make_section(current_heading, current_page_start, current_blocks))
        elif pre_heading_blocks:
            raw_sections.append(self._make_section("Document", pre_heading_blocks[0].page, pre_heading_blocks, force_role=SectionRole.OTHER))

        self._resolve_front_matter(doc, raw_sections)
        self._apply_parent_inheritance(raw_sections)

        for idx, sec in enumerate(raw_sections, 1):
            sec.section_id = f"S{idx:02d}"

        doc.sections = raw_sections
        return doc

    def _detect_heading(self, block: Block, body_size: float) -> str | None:
        lines_text = [line.text.strip() for line in block.lines if line.text.strip()]
        if not lines_text:
            return None
        if block.max_size < max(8.5, body_size - 1.0):
            return None

        if len(lines_text) == 2 and block.is_bold and block.max_size >= body_size:
            first, second = lines_text[0], lines_text[1]
            if SECTION_NUM_RE.match(first) and SECTION_TITLE_RE.match(second):
                return f"{first} {second}"
            if first == second and BOLD_TITLE_RE.match(first):
                return first
            if (NUM_HEADING_RE.match(first) or ALPHA_HEADING_RE.match(first)) and len(second) <= 60 and not second.endswith("."):
                joined = f"{first[:-1]}{second}" if first.endswith("-") else f"{first} {second}"
                return joined

        if len(lines_text) == 1:
            line = lines_text[0]
            if len(line) > 90:
                return None
            if (block.is_bold or block.max_size >= body_size + 1.0) and (NUM_HEADING_RE.match(line) or ALPHA_HEADING_RE.match(line)):
                return line
            if (block.is_bold or block.max_size >= body_size + 0.4) and (STANDALONE_HEADING_RE.match(line) or APPENDIX_HEADING_RE.match(line)):
                return line
            # Standalone uppercase/title headings like "ABSTRACT" or "INTRODUCTION" at body size
            if STANDALONE_HEADING_RE.match(line) and (block.is_bold or line.isupper() or block.max_size >= body_size):
                return line
            if block.is_bold and BOLD_TITLE_RE.match(line) and block.max_size >= body_size and not line.endswith("."):
                return line
        return None

    def _make_section(self, heading: str, page_start: int, blocks: list[Block], force_role: SectionRole | None = None) -> Section:
        page_end = max((b.page for b in blocks), default=page_start)
        role = force_role if force_role is not None else self._classify_role(heading)
        return Section(
            section_id="",
            heading=heading,
            role=role,
            page_start=page_start,
            page_end=page_end,
            blocks=list(blocks),
        )

    def _classify_role(self, heading: str) -> SectionRole:
        for role in _ROLE_PRIORITY:
            for pattern in self._role_patterns.get(role, []):
                if pattern.search(heading):
                    return role
        return SectionRole.OTHER

    def _resolve_front_matter(self, doc: Document, sections: list[Section]) -> None:
        intro_idx: int | None = None
        for idx, sec in enumerate(sections):
            if sec.role == SectionRole.INTRODUCTION or FIRST_BODY_SECTION_RE.match(sec.heading):
                intro_idx = idx
                break

        search_end = intro_idx if intro_idx is not None else len(sections)
        abstract_indices = [idx for idx in range(search_end) if ABSTRACT_RE.match(sections[idx].heading)]

        dup_pages: set[int] = set()
        if len(abstract_indices) >= 2:
            canonical_idx = abstract_indices[-1]
            canonical_page = sections[canonical_idx].page_start
            for idx in range(canonical_idx):
                sec = sections[idx]
                sec.role = SectionRole.FRONT_MATTER
                sec.is_duplicate_front_matter = True
                for p in range(sec.page_start, sec.page_end + 1):
                    if p < canonical_page:
                        dup_pages.add(p)
            sections[canonical_idx].role = SectionRole.ABSTRACT
        elif len(abstract_indices) == 1:
            canonical_idx = abstract_indices[0]
            for idx in range(canonical_idx):
                sections[idx].role = SectionRole.FRONT_MATTER

        doc.duplicate_front_matter_pages = sorted(dup_pages)

    @staticmethod
    def _apply_parent_inheritance(sections: list[Section]) -> None:
        major_roles: dict[str, SectionRole] = {}
        seen_references = False
        for sec in sections:
            if sec.role == SectionRole.REFERENCES:
                seen_references = True
                continue
            if sec.is_duplicate_front_matter or sec.role == SectionRole.FRONT_MATTER:
                continue

            m = MAJOR_NUM_RE.match(sec.heading)
            if m:
                major = m.group(1)
                is_subsection = "." in sec.heading.split()[0].rstrip(".")
                if not is_subsection:
                    if sec.role != SectionRole.OTHER:
                        major_roles[major] = sec.role
                elif sec.role == SectionRole.OTHER and major in major_roles:
                    sec.role = major_roles[major]
            elif seen_references and sec.role == SectionRole.OTHER:
                sec.role = SectionRole.APPENDIX
