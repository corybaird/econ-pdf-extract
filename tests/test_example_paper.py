from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from econ_pdf_extract import ExtractionPipeline, PaperMetadata, TargetDrafter

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_PDF = ROOT / "examples" / "example_paper.pdf"
PUBLIC_FRBSF_PDFS = [
    ROOT / "examples" / "papers" / "shapiro_2017-01_sentiment.pdf",
    ROOT / "examples" / "papers" / "acosta_et_al_2025-30_usmpd.pdf",
]


@pytest.fixture(scope="module")
def example_result():
    if not EXAMPLE_PDF.exists():
        pytest.skip("Example paper not generated; run uv run python examples/make_example_paper.py")
    paper = PaperMetadata(paper_id="example", source_path=str(EXAMPLE_PDF), authors="A", title="T", journal="J")
    return ExtractionPipeline(EXAMPLE_PDF, paper=paper).run()


def test_example_statistics(example_result):
    by_key = {(s.kind, s.value): s for s in example_result.statistics}
    assert ("percent", 3.2) in by_key
    assert ("p_value", 0.01) in by_key
    assert ("r_squared", 0.21) in by_key
    assert ("r_squared", 0.02) in by_key
    assert ("t_stat", 3.45) in by_key
    assert ("sample_size", 214.0) in by_key


def test_example_claims_found(example_result):
    texts = " ".join(c.quote.lower() for c in example_result.claims)
    assert "we find" in texts
    assert "results show" in texts
    assert all(c.page >= 1 for c in example_result.claims)
    assert all(len(c.bbox) == 4 for c in example_result.claims)


def test_example_sections(example_result):
    headings = [s["heading"] for s in example_result.sections]
    assert any("Introduction" in h for h in headings)
    assert any("Results" in h for h in headings)


def test_example_full_draft_yaml(example_result, tmp_path: Path):
    dest = TargetDrafter(example_result.paper, example_result.claims, example_result.statistics).run(tmp_path)
    raw = dest.read_text(encoding="utf-8")
    parsed = yaml.safe_load(raw)
    targets = parsed["targets"]
    assert targets, "expected at least one matched claim-statistic target"
    for target in targets:
        assert target["our_key"] is None and "TODO" in raw
        assert target["paper_units"] in {"coefficient", "R-squared", "p-value", "t-stat", "observations", "pp", "unspecified"}
        assert "Section '" in target["location"] and "page" in target["location"]
    descriptions = " ".join(t["description"] for t in targets).lower()
    assert "policy surprise" in descriptions


@pytest.mark.parametrize("pdf_path", PUBLIC_FRBSF_PDFS)
def test_public_frbsf_smoke(pdf_path: Path):
    if not pdf_path.exists():
        pytest.skip(f"Public FRBSF PDF absent: {pdf_path.name}")
    res = ExtractionPipeline(pdf_path).run()
    assert res.page_count >= 10
    assert len(res.sections) >= 3
    assert len(res.claims) >= 1
    assert all(c.page >= 1 and c.section and len(c.bbox) == 4 for c in res.claims)
