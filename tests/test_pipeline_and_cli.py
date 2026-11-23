from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from econ_pdf_extract import (
    BatchPipeline,
    ExtractionPipeline,
    PaperMetadata,
)
from econ_pdf_extract.cli import Cli

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_PDF = ROOT / "examples" / "example_paper.pdf"


def test_end_to_end_pipeline_on_synthetic_pdf(synthetic_paper_pdf: Path):
    paper = PaperMetadata(paper_id="synthetic", source_path=str(synthetic_paper_pdf), authors="Alex Researcher", title="Synthetic Paper", journal="WP")
    res = ExtractionPipeline(synthetic_paper_pdf, paper=paper).run()

    assert res.page_count == 6
    assert res.ocr_backend == "none"
    assert res.ocr_policy == "none"
    assert 1 in res.diagnostics["duplicate_front_matter_pages"]

    # Claims carry full provenance, links, attribution, and dedup
    assert len(res.claims) >= 7
    r2_claim = next(c for c in res.claims if "4.82%" in c.quote)
    assert r2_claim.page == 5
    assert r2_claim.section == "3 Empirical Results"
    assert r2_claim.linked_equation_ids  # linked via Equation (1)

    cer_claim = next(c for c in res.claims if "higher CER" in c.quote)
    assert cer_claim.linked_equation_ids  # linked via named metric CER

    # Math objects include displays, assumption, algorithm, and symbol defs
    assert len(res.math_objects) >= 5
    assert len(res.symbols) >= 2
    assert len(res.links) >= 2


def test_cli_json_preserves_full_provenance(synthetic_paper_pdf: Path, capsys: pytest.CaptureFixture[str]):
    Cli(["extract", str(synthetic_paper_pdf), "--json"]).run()
    out = capsys.readouterr().out
    payload = json.loads(out)

    assert "claims" in payload and "math_objects" in payload and "symbols" in payload and "links" in payload
    assert payload["claims"]
    for claim in payload["claims"]:
        assert isinstance(claim["page"], int) and claim["page"] >= 1
        assert isinstance(claim["page_end"], int) and claim["page_end"] >= claim["page"]
        assert isinstance(claim["section"], str) and claim["section"]
        assert isinstance(claim["bbox"], list) and len(claim["bbox"]) == 4
        assert claim["source_channel"] == "text"
        assert "attribution" in claim and "claim_types" in claim

    assert payload["math_objects"]
    for obj in payload["math_objects"]:
        assert isinstance(obj["page"], int) and obj["page"] >= 1
        assert isinstance(obj["bbox"], list) and len(obj["bbox"]) == 4
        assert obj["source_channel"] == "text"


def test_cli_markdown_report_and_targets(synthetic_paper_pdf: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    Cli(["extract", str(synthetic_paper_pdf), "--markdown", "--output-dir", str(tmp_path)]).run()
    md_files = list(tmp_path.glob("extracted_report_*.md"))
    assert len(md_files) == 1
    md = md_files[0].read_text(encoding="utf-8")
    assert "## Headline Claims" in md
    assert "## Math & Logic Catalog" in md

    rep_dir = tmp_path / "reports"
    Cli(["report", "--pdf", str(synthetic_paper_pdf), "--reports-dir", str(rep_dir), "--format", "both"]).run()
    assert len(list(rep_dir.glob("extracted_*.json"))) == 1
    assert len(list(rep_dir.glob("extracted_report_*.md"))) == 1

    tgt_dir = tmp_path / "targets"
    Cli(["targets", str(synthetic_paper_pdf), "--reports-dir", str(tgt_dir)]).run()
    yaml_files = list(tgt_dir.glob("draft_paper_targets_*.yaml"))
    assert len(yaml_files) == 1
    parsed = yaml.safe_load(yaml_files[0].read_text(encoding="utf-8"))
    assert parsed["targets"]
    capsys.readouterr()


def test_batch_pipeline_writes_summary(synthetic_paper_pdf: Path, tmp_path: Path):
    papers = [
        PaperMetadata(paper_id="syn1", source_path=str(synthetic_paper_pdf), authors="Author A", title="Paper 1"),
        PaperMetadata(paper_id="syn2", source_path=str(EXAMPLE_PDF), authors="Author B", title="Paper 2"),
    ]
    results = BatchPipeline(papers=papers, reports_dir=tmp_path, output_format="both").run()
    assert len(results) == 2
    assert len(list(tmp_path.glob("extracted_report_*.md"))) == 2
    assert len(list(tmp_path.glob("extracted_summary_all_*.md"))) == 1
    assert len(list(tmp_path.glob("extracted_syn*.json"))) == 2


def test_cli_subprocess_json_stdout_is_valid_json(synthetic_paper_pdf: Path):
    targets = [synthetic_paper_pdf]
    shapiro = ROOT / "examples" / "papers" / "shapiro_2017-01_sentiment.pdf"
    if shapiro.exists():
        targets.append(shapiro)
    for pdf in targets:
        proc = subprocess.run(
            [sys.executable, "-m", "econ_pdf_extract.cli", "extract", str(pdf), "--json"],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(proc.stdout)
        assert "claims" in payload and "math_objects" in payload
        assert "pymupdf_layout" not in proc.stdout
