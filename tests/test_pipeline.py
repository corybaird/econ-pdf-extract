from __future__ import annotations

import json
from pathlib import Path

from econ_pdf_extract.core.models import (
    Attribution,
    CausalTriple,
    Claim,
    ClaimType,
    CrossRefEdge,
    ExtractionResult,
    MathKind,
    MathObject,
    PaperMetadata,
    ProvenanceRef,
    SectionRole,
    SymbolDef,
)
from econ_pdf_extract.reporting import (
    BatchSummaryWriter,
    JsonReportWriter,
    MarkdownReportWriter,
)


def _sample_result() -> ExtractionResult:
    c1 = Claim(
        claim_id="CLM-001",
        paper_id="sample_paper",
        claim_types=[ClaimType.FORECAST_ACCURACY, ClaimType.MAGNITUDE],
        attribution=Attribution.OWN,
        page=5,
        page_end=5,
        section="3 Results",
        section_role=SectionRole.RESULTS,
        bbox=(72.0, 120.0, 500.0, 134.0),
        quote="Using Equation (1), R2_oos reaches 4.82%.",
        linked_equation_ids=["EQ-001"],
        linked_symbols=["R2_oos"],
        also_seen_on=[ProvenanceRef(page=6, section="4 Conclusion", bbox=(72.0, 110.0, 490.0, 124.0))],
    )
    c2 = Claim(
        claim_id="CLM-002",
        paper_id="sample_paper",
        claim_types=[ClaimType.PROPOSAL],
        attribution=Attribution.LITERATURE,
        page=3,
        page_end=3,
        section="1 Introduction",
        section_role=SectionRole.INTRODUCTION,
        bbox=(72.0, 140.0, 500.0, 154.0),
        quote="Smith et al. (2020) show that factors explain 12 percent of variance.",
    )
    c3 = Claim(
        claim_id="CLM-003",
        paper_id="sample_paper",
        claim_types=[ClaimType.FORECAST_ACCURACY],
        attribution=Attribution.OWN,
        page=6,
        page_end=6,
        section="4 Conclusion",
        section_role=SectionRole.CONCLUSION,
        bbox=(72.0, 110.0, 490.0, 124.0),
        quote="Overall, R2_oos reaches 4.82%.",
        duplicate_of="CLM-001",
    )
    sym = SymbolDef(
        symbol_id="SYM-001",
        symbol="y_t",
        normalized="yt",
        description="excess bond returns",
        equation_id="EQ-001",
        page=4,
        section="2 Model",
        bbox=(72.0, 210.0, 400.0, 224.0),
    )
    eq = MathObject(
        math_id="EQ-001",
        paper_id="sample_paper",
        kind=MathKind.MODEL_SPECIFICATION,
        tag="(1)",
        raw_text="y_t = b_0 + b_1 f_t + e_t",
        latex=None,
        page=4,
        page_end=4,
        section="2 Model",
        bbox=(160.0, 180.0, 500.0, 195.0),
        symbols_defined=[sym],
        linked_claim_ids=["CLM-001"],
    )
    return ExtractionResult(
        paper=PaperMetadata(paper_id="sample_paper", source_path="examples/example_paper.pdf", authors="Author (2026)", title="Sample Paper", journal="WP"),
        page_count=6,
        ocr_backend="none",
        ocr_policy="none",
        extracted_at="2026-11-20T00:00:00Z",
        sections=[{"section_id": "S01", "heading": "3 Results", "role": "results", "page_start": 5, "page_end": 5}],
        claims=[c1, c2, c3],
        math_objects=[eq],
        symbols=[sym],
        links=[CrossRefEdge(claim_id="CLM-001", math_id="EQ-001", via="explicit_ref", matched_token="(1)")],
        diagnostics={"ocr_calls": 0, "duplicate_front_matter_pages": [1]},
    )


def test_json_report_writer_preserves_full_provenance_and_filters(tmp_path: Path):
    res = _sample_result()
    dest = JsonReportWriter().write(res, tmp_path, timestamp="20261120_000000")
    assert dest.name == "extracted_sample_paper_20261120_000000.json"
    loaded = json.loads(dest.read_text(encoding="utf-8"))
    assert len(loaded["claims"]) == 3
    assert loaded["claims"][0]["page"] == 5
    assert loaded["claims"][0]["section"] == "3 Results"
    assert loaded["claims"][0]["bbox"] == [72.0, 120.0, 500.0, 134.0]
    assert loaded["math_objects"][0]["page"] == 4
    assert loaded["links"][0]["via"] == "explicit_ref"

    filtered = JsonReportWriter(include_literature=False, include_duplicates=False).to_payload(res)
    assert [c["claim_id"] for c in filtered["claims"]] == ["CLM-001"]


def test_markdown_and_batch_summary_writers(tmp_path: Path):
    res = _sample_result()
    md_path = MarkdownReportWriter().write(res, tmp_path, timestamp="20261120_000000")
    assert md_path.name == "extracted_report_sample_paper_20261120_000000.md"
    md = md_path.read_text(encoding="utf-8")

    assert "## Headline Claims" in md
    assert "| `CLM-001` | 5 | 3 Results |" in md
    assert "also seen on: p.6 (4 Conclusion)" in md
    assert "CLM-003" not in md  # duplicate hidden by default
    assert "## Literature Claims Appendix" in md
    assert "Smith et al. (2020)" in md
    assert "## Math & Logic Catalog" in md
    assert "| `EQ-001` | model_specification | (1) | 4 |" in md
    assert "## Symbol Glossary" in md
    assert "| `y_t` | excess bond returns | EQ-001 | 4 |" in md

    summary_path = BatchSummaryWriter().write([res], tmp_path, timestamp="20261120_000000")
    assert summary_path.name == "extracted_summary_all_20261120_000000.md"
    summary = summary_path.read_text(encoding="utf-8")
    assert "| `sample_paper` | Author (2026) | *Sample Paper* | **1** | 1 | 1 | 1 |" in summary


def test_causal_triples_render_in_json_and_markdown():
    res = _sample_result()
    res.causal_triples = [
        CausalTriple(
            triple_id="TRP-001",
            paper_id="sample_paper",
            cause="monetary tightening",
            direction="decrease",
            outcome="industrial output",
            verb="reduce",
            sentence="Monetary tightening reduces industrial output by 2%.",
            page=5,
            section="3 Results",
            section_role=SectionRole.RESULTS,
        )
    ]
    payload = JsonReportWriter().to_payload(res)
    assert len(payload["causal_triples"]) == 1
    assert payload["causal_triples"][0]["cause"] == "monetary tightening"
    assert payload["causal_triples"][0]["direction"] == "decrease"
    assert payload["causal_triples"][0]["outcome"] == "industrial output"
    assert payload["causal_triples"][0]["page"] == 5
    assert payload["causal_triples"][0]["section"] == "3 Results"

    md = MarkdownReportWriter().render(res)
    assert "## Causal Triples" in md
    assert "| `TRP-001` | 5 | 3 Results | monetary tightening | decrease | industrial output |" in md
