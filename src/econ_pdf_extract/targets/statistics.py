from __future__ import annotations

import re

from econ_pdf_extract.core.config import ConfigLoader
from econ_pdf_extract.core.models import Document, SectionRole, Sentence, Statistic

_EXCLUDED_ROLES = frozenset({SectionRole.FRONT_MATTER, SectionRole.REFERENCES})


def clause(text: str, limit: int = 120) -> str:
    collapsed = " ".join(text.split())
    return collapsed if len(collapsed) <= limit else collapsed[:limit].rstrip() + "..."


class StatisticExtractor:
    """Extracts quantitative statistics from cleaned provenance-bearing sentences without table bleed."""

    def __init__(self, raw_patterns: dict[str, list[str]] | None = None):
        raw = raw_patterns if raw_patterns is not None else ConfigLoader().load("target_patterns.yaml")["statistic_patterns"]
        self._patterns = {kind: [re.compile(rx, re.IGNORECASE) for rx in regexes] for kind, regexes in raw.items()}

    def extract(self, doc: Document) -> list[Statistic]:
        dup_ids = {s.section_id for s in doc.sections if s.is_duplicate_front_matter}
        sentences = [
            s
            for s in doc.sentences
            if s.section_id not in dup_ids and s.section_role not in _EXCLUDED_ROLES
        ]
        return self.extract_from_sentences(sentences)

    def extract_from_sentences(self, sentences: list[Sentence]) -> list[Statistic]:
        stats: list[Statistic] = []
        seen: set[tuple[str, float, int, str]] = set()
        for sent in sentences:
            ctx = clause(sent.text)
            for kind, regexes in self._patterns.items():
                for regex in regexes:
                    for match in regex.finditer(sent.text):
                        raw_val = match.group("value").replace(",", "").strip("()")
                        try:
                            value = float(raw_val)
                        except ValueError:
                            continue
                        key = (kind, value, sent.page, ctx)
                        if key in seen:
                            continue
                        seen.add(key)
                        stats.append(
                            Statistic(
                                kind=kind,
                                text=match.group(0),
                                value=value,
                                page=sent.page,
                                section=sent.section_heading,
                                bbox=sent.bbox,
                                context=ctx,
                            )
                        )
        return stats
