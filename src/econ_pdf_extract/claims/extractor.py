from __future__ import annotations

from typing import Any

from econ_pdf_extract.claims.attribution import AttributionClassifier
from econ_pdf_extract.claims.classifier import ClaimClassifier
from econ_pdf_extract.claims.dedup import ClaimDeduplicator
from econ_pdf_extract.claims.refiner import ClaimRefiner, NullClaimRefiner
from econ_pdf_extract.core.config import ConfigLoader
from econ_pdf_extract.core.models import (
    Claim,
    Document,
    SectionRole,
    SourceChannel,
)


class ClaimExtractor:
    """Extracts typed, attributed, deduplicated empirical claims with true page and bbox provenance."""

    def __init__(self, extraction_cfg: dict[str, Any] | None = None, pattern_cfg: dict[str, Any] | None = None, refiner: ClaimRefiner | None = None, include_appendix: bool = False):
        loader = ConfigLoader()
        ecfg = extraction_cfg if extraction_cfg is not None else loader.load("extraction.yaml").get("claims", {})
        pcfg = pattern_cfg if pattern_cfg is not None else loader.load("claim_patterns.yaml")

        raw_roles = ecfg.get("eligible_roles", ["abstract", "introduction", "results", "robustness", "conclusion"])
        self._eligible_roles = {SectionRole(r) for r in raw_roles}
        if include_appendix or bool(ecfg.get("include_appendix_by_default", False)):
            self._eligible_roles.add(SectionRole.APPENDIX)

        self._classifier = ClaimClassifier(pcfg)
        self._attribution = AttributionClassifier(pcfg)
        self._dedup = ClaimDeduplicator(ecfg.get("dedup", {}))
        self._refiner = refiner if refiner is not None else NullClaimRefiner()

    def extract(self, doc: Document) -> list[Claim]:
        dup_section_ids = {s.section_id for s in doc.sections if s.is_duplicate_front_matter}
        printed_by_page = {p.page: p.printed_page for p in doc.pages}

        # Numbered topical body sections (SectionRole.OTHER) appearing between Introduction and References
        # often hold empirical results in applied econ papers (e.g. "4 Treasury Yields", "5 Risk Assets").
        body_other_ids = self._body_other_section_ids(doc)

        claims: list[Claim] = []
        seq = 0
        for sent in doc.sentences:
            if sent.section_id in dup_section_ids:
                continue
            in_body_other = sent.section_role == SectionRole.OTHER and sent.section_id in body_other_ids
            if sent.section_role not in self._eligible_roles and not in_body_other:
                continue
            claim_types, matched_cues = self._classifier.classify(sent.text, section_role=sent.section_role)
            if not claim_types:
                continue
            if in_body_other and claim_types == [claim_types[0]] and claim_types[0].value == "general":
                continue
            attribution = self._attribution.classify(sent.text)
            seq += 1
            claims.append(
                Claim(
                    claim_id=f"CLM-{seq:03d}",
                    paper_id=doc.paper_id,
                    claim_types=claim_types,
                    attribution=attribution,
                    page=sent.page,
                    page_end=sent.page_end,
                    section=sent.section_heading,
                    section_role=sent.section_role,
                    bbox=sent.bbox,
                    quote=sent.text,
                    source_channel=SourceChannel.TEXT,
                    printed_page=printed_by_page.get(sent.page),
                    matched_cues=matched_cues,
                    math_tokens=list(sent.math_tokens),
                )
            )

        self._dedup.deduplicate(claims)
        return self._refiner.refine(claims, doc)

    @staticmethod
    def _body_other_section_ids(doc: Document) -> set[str]:
        seen_intro = False
        ids: set[str] = set()
        for sec in doc.sections:
            if sec.is_duplicate_front_matter:
                continue
            if sec.role == SectionRole.INTRODUCTION:
                seen_intro = True
                continue
            if sec.role in {SectionRole.REFERENCES, SectionRole.APPENDIX}:
                break
            if seen_intro and sec.role == SectionRole.OTHER and sec.heading[:1].isdigit():
                ids.add(sec.section_id)
        return ids
