from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

from econ_pdf_extract.claims import ClaimRefiner
from econ_pdf_extract.core import ConfigLoader, ExtractionResult, PaperMetadata
from econ_pdf_extract.pipeline.runner import ExtractionPipeline
from econ_pdf_extract.reporting import (
    BatchSummaryWriter,
    JsonReportWriter,
    MarkdownReportWriter,
)

logger = logging.getLogger(__name__)


class BatchPipeline:
    """Multi-paper registry runner writing timestamped per-paper and summary reports."""

    def __init__(self, papers: list[PaperMetadata], reports_dir: Path, ocr_backend: str = "none", ocr_policy: str = "fallback", output_format: str = "both", include_appendix: bool = False, refiner: ClaimRefiner | None = None, extract_causal_triples: bool = False, spacy_model: str | None = None):
        self._papers = papers
        self._reports_dir = Path(reports_dir)
        self._ocr_backend = ocr_backend
        self._ocr_policy = ocr_policy
        self._output_format = output_format
        self._include_appendix = include_appendix
        self._refiner = refiner
        self._extract_causal_triples = extract_causal_triples
        self._spacy_model = spacy_model

    @classmethod
    def from_config(cls, config_path: Path | None, reports_dir: Path, ocr_backend: str = "none", ocr_policy: str = "fallback", output_format: str = "both", include_appendix: bool = False, refiner: ClaimRefiner | None = None, extract_causal_triples: bool = False, spacy_model: str | None = None) -> BatchPipeline:
        papers = ConfigLoader().load_papers(config_path)
        return cls(
            papers=papers,
            reports_dir=reports_dir,
            ocr_backend=ocr_backend,
            ocr_policy=ocr_policy,
            output_format=output_format,
            include_appendix=include_appendix,
            refiner=refiner,
            extract_causal_triples=extract_causal_triples,
            spacy_model=spacy_model,
        )

    def run(self, ids: list[str] | None = None) -> list[ExtractionResult]:
        self._reports_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        selected = [p for p in self._papers if ids is None or p.paper_id in ids]
        results: list[ExtractionResult] = []
        json_writer = JsonReportWriter()
        md_writer = MarkdownReportWriter()

        for paper in selected:
            pdf_path = paper.pdf_path
            if not pdf_path.exists():
                raise FileNotFoundError(f"PDF not found for {paper.paper_id}: {pdf_path}")
            result = ExtractionPipeline(
                pdf_path=pdf_path,
                paper=paper,
                ocr_backend=self._ocr_backend,
                ocr_policy=self._ocr_policy,
                include_appendix=self._include_appendix,
                refiner=self._refiner,
                extract_causal_triples=self._extract_causal_triples,
                spacy_model=self._spacy_model,
            ).run()
            results.append(result)

            if self._output_format in {"json", "both"}:
                j_dest = json_writer.write(result, self._reports_dir, timestamp=ts)
                logger.info("Wrote JSON report for %s -> %s", paper.paper_id, j_dest)
            if self._output_format in {"markdown", "both"}:
                m_dest = md_writer.write(result, self._reports_dir, timestamp=ts)
                logger.info("Wrote Markdown report for %s -> %s", paper.paper_id, m_dest)

        if len(results) > 1 and self._output_format in {"markdown", "both"}:
            summary_dest = BatchSummaryWriter().write(results, self._reports_dir, timestamp=ts)
            logger.info("Wrote batch summary -> %s", summary_dest)

        return results
