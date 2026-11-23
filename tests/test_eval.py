from __future__ import annotations

import json
from pathlib import Path

import yaml

from econ_pdf_extract.core import (
    Attribution,
    Claim,
    ClaimType,
    PaperMetadata,
    SectionRole,
)
from econ_pdf_extract.eval import ClaimEvaluator
from econ_pdf_extract.eval.evaluator import role_section_matches, strict_section_matches


def test_claim_evaluator_on_synthetic_pdf(synthetic_paper_pdf: Path, tmp_path: Path):
    refs = [
        {
            "paper": "synthetic",
            "page": 2,
            "section": "Abstract",
            "type": "forecast_accuracy",
            "quote": "I show that factor models substantially improve out-of-sample forecast accuracy across all horizons.",
        },
        {
            "paper": "synthetic",
            "page": 4,
            "section": "1 Introduction",
            "type": "forecast_accuracy",
            "quote": "I further demonstrate that the extended specification delivers superior directional accuracy during recessions.",
        },
        {
            "paper": "synthetic",
            "page": 5,
            "section": "3 Empirical Results",
            "type": "magnitude",
            "quote": "Using Equation (1), the out-of-sample R2_oos reaches 4.82% across the full evaluation window.",
        },
        {
            "paper": "synthetic",
            "page": 5,
            "section": "3 Empirical Results",
            "type": "significance",
            "quote": "The equality test rejects the baseline benchmark at the 5% significance level (p < 0.01).",
        },
    ]
    refs_dir = tmp_path / "refs"
    refs_dir.mkdir()
    (refs_dir / "ref_claims_synthetic.yaml").write_text(yaml.safe_dump(refs), encoding="utf-8")

    out_dir = tmp_path / "eval_out"
    paper = PaperMetadata(paper_id="synthetic", source_path=str(synthetic_paper_pdf), authors="Alex Researcher", title="Synthetic")
    summary = ClaimEvaluator(refs_dir=refs_dir, output_dir=out_dir, papers=[paper]).run()

    agg = summary["aggregate"]
    assert agg["refs"] == 4
    assert agg["tp"] == 4
    assert agg["recall"] == 1.0
    assert agg["exact_page_accuracy"] == 1.0
    assert agg["strict_section_accuracy"] == 1.0
    assert agg["role_section_accuracy"] == 1.0
    assert agg["precision"] >= 0.4

    json_files = list(out_dir.glob("eval_claims_*.json"))
    md_files = list(out_dir.glob("eval_claims_*.md"))
    assert len(json_files) == 1
    assert len(md_files) == 1
    loaded = json.loads(json_files[0].read_text(encoding="utf-8"))
    assert loaded["aggregate"]["recall"] == 1.0
    assert loaded["aggregate"]["strict_section_accuracy"] == 1.0
    assert loaded["aggregate"]["role_section_accuracy"] == 1.0


def test_strict_vs_role_section_matching():
    claim = Claim(
        claim_id="CLM-001",
        paper_id="demo",
        claim_types=[ClaimType.MAGNITUDE],
        attribution=Attribution.OWN,
        page=5,
        page_end=5,
        section="3.2 Out-of-Sample Analysis",
        section_role=SectionRole.RESULTS,
        bbox=(72.0, 100.0, 500.0, 112.0),
        quote="The estimate rises by 2 percent.",
    )
    assert strict_section_matches("3.2 Out-of-Sample Analysis", claim.section) is True
    assert strict_section_matches("3 Results", claim.section) is False
    assert role_section_matches("3 Results", claim) is True
