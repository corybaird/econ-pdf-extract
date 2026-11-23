from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

from econ_pdf_extract.claims import ClaimExtractor, ClaimRefiner
from econ_pdf_extract.core import (
    CausalTriple,
    ConfigLoader,
    ExtractionResult,
    PaperMetadata,
)
from econ_pdf_extract.layout import (
    LayoutCleaner,
    PdfReader,
    SectionBuilder,
    SentenceSegmenter,
)
from econ_pdf_extract.linking import CrossReferenceLinker
from econ_pdf_extract.math_extract import MathExtractor
from econ_pdf_extract.nlp import CausalTripleExtractor, SpacyClaimFilter
from econ_pdf_extract.ocr import OcrBackendFactory, RegionCropper
from econ_pdf_extract.targets import StatisticExtractor

logger = logging.getLogger(__name__)


class ExtractionPipeline:
    """Single-PDF end-to-end extraction orchestrator returning a full-provenance ExtractionResult."""

    def __init__(self, pdf_path: Path | str, paper: PaperMetadata | None = None, ocr_backend: str = "none", ocr_policy: str = "fallback", include_appendix: bool = False, refiner: ClaimRefiner | None = None, config_dir: Path | None = None, extract_causal_triples: bool = False, spacy_model: str | None = None):
        self._pdf_path = Path(pdf_path)
        self._paper = paper or PaperMetadata(paper_id=self._pdf_path.stem, source_path=str(self._pdf_path), title=self._pdf_path.name)
        self._ocr_backend_name = (ocr_backend or "none").strip().lower()
        self._ocr_policy = "none" if self._ocr_backend_name == "none" else (ocr_policy or "fallback").strip().lower()
        self._include_appendix = include_appendix
        self._refiner = refiner
        self._extract_causal_triples = extract_causal_triples
        self._spacy_model = spacy_model
        self._loader = ConfigLoader(config_dir=config_dir)

    def run(self) -> ExtractionResult:
        extraction_cfg = self._loader.load("extraction.yaml")
        claim_cfg = self._loader.load("claim_patterns.yaml")
        math_cfg = self._loader.load("math_patterns.yaml")
        target_cfg = self._loader.load("target_patterns.yaml")

        # Stage 1: Layout
        doc = PdfReader().read(self._pdf_path, paper_id=self._paper.paper_id)
        LayoutCleaner(extraction_cfg.get("layout", {})).clean(doc)
        SectionBuilder(extraction_cfg.get("sections", {})).build(doc)
        SentenceSegmenter(extraction_cfg.get("layout", {})).segment(doc)

        # Stage 2A: Claims
        claims = ClaimExtractor(
            extraction_cfg=extraction_cfg.get("claims", {}),
            pattern_cfg=claim_cfg,
            refiner=self._refiner,
            include_appendix=self._include_appendix,
        ).extract(doc)

        # Stage 2A-bis: Optional all-sentences causal triples (never rewrites claim types)
        causal_triples: list[CausalTriple] = []
        run_triples = self._extract_causal_triples or bool(extraction_cfg.get("nlp", {}).get("enable_causal_triples", False))
        if run_triples:
            shared_nlp = None
            if isinstance(self._refiner, SpacyClaimFilter) and (self._spacy_model is None or self._spacy_model == self._refiner.model_name):
                shared_nlp = self._refiner.get_nlp()
            nlp_cfg = self._loader.load("nlp_patterns.yaml")
            causal_triples = CausalTripleExtractor(
                model_name=self._spacy_model,
                nlp=shared_nlp,
                extraction_cfg=extraction_cfg,
                nlp_cfg=nlp_cfg,
                include_appendix=self._include_appendix,
            ).extract(doc)

        # Stage 2B: Math & Logic (+ optional targeted OCR)
        ocr_cfg = extraction_cfg.get("ocr", {})
        backend = OcrBackendFactory.create(self._ocr_backend_name, config=ocr_cfg)
        cropper = RegionCropper.from_config(ocr_cfg) if self._ocr_backend_name != "none" else None
        math_objects, symbols, ocr_calls = MathExtractor(extraction_cfg, math_cfg).extract(
            doc,
            ocr_backend=backend,
            ocr_policy=self._ocr_policy,
            cropper=cropper,
        )

        # Stage 3: Linking & Statistics
        links = CrossReferenceLinker(math_cfg).link(claims, math_objects, symbols, doc=doc)
        statistics = StatisticExtractor(target_cfg.get("statistic_patterns")).extract(doc)

        section_index = [
            {
                "section_id": s.section_id,
                "heading": s.heading,
                "role": s.role.value,
                "page_start": s.page_start,
                "page_end": s.page_end,
                "is_duplicate_front_matter": s.is_duplicate_front_matter,
            }
            for s in doc.sections
        ]

        scanned_pages = [p.page for p in doc.pages if p.char_count < 20 and p.image_count > 0]
        warnings: list[str] = []
        if scanned_pages:
            warnings.append(f"Pages may be scanned (low text, images present): {scanned_pages}")

        diagnostics = {
            "total_sentences": len(doc.sentences),
            "total_claims": len(claims),
            "canonical_claims": sum(1 for c in claims if c.duplicate_of is None),
            "duplicate_claims": sum(1 for c in claims if c.duplicate_of is not None),
            "math_objects": len(math_objects),
            "needs_ocr_displays": sum(1 for m in math_objects if m.needs_ocr),
            "ocr_calls": ocr_calls,
            "symbols": len(symbols),
            "links": len(links),
            "statistics": len(statistics),
            "causal_triples": len(causal_triples),
            "duplicate_front_matter_pages": list(doc.duplicate_front_matter_pages),
            "warnings": warnings,
        }

        logger.info(
            "Extracted %s: %d claims, %d math objects, %d symbols, %d links",
            self._paper.paper_id,
            len(claims),
            len(math_objects),
            len(symbols),
            len(links),
        )

        return ExtractionResult(
            paper=self._paper,
            page_count=doc.page_count,
            ocr_backend=self._ocr_backend_name,
            ocr_policy=self._ocr_policy,
            extracted_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            sections=section_index,
            claims=claims,
            math_objects=math_objects,
            symbols=symbols,
            links=links,
            statistics=statistics,
            causal_triples=causal_triples,
            diagnostics=diagnostics,
        )
