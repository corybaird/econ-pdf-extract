from __future__ import annotations

import json
from pathlib import Path

import pytest

from econ_pdf_extract.core import (
    CONFIGS_DIR,
    PROJECT_ROOT,
    Attribution,
    Block,
    BlockKind,
    Claim,
    ClaimType,
    ConfigLoader,
    CrossRefEdge,
    ExtractionResult,
    MathKind,
    MathObject,
    PaperMetadata,
    ProvenanceRef,
    SectionRole,
    SourceChannel,
    Statistic,
    SymbolDef,
)


def test_project_root_points_to_repo_root():
    assert (PROJECT_ROOT / "pyproject.toml").is_file()
    assert CONFIGS_DIR.is_dir()


def test_dataclass_defaults_are_not_shared():
    b1 = Block(block_id="p01_b01", page=1, bbox=(0.0, 0.0, 10.0, 10.0))
    b2 = Block(block_id="p01_b02", page=1, bbox=(0.0, 10.0, 10.0, 20.0))
    b1.lines.append("sentinel")  # type: ignore[arg-type]
    assert b2.lines == []

    c1 = Claim(
        claim_id="CLM-001",
        paper_id="demo",
        claim_types=[ClaimType.PROPOSAL],
        attribution=Attribution.OWN,
        page=1,
        page_end=1,
        section="Abstract",
        section_role=SectionRole.ABSTRACT,
        bbox=(10.0, 20.0, 300.0, 40.0),
        quote="We propose a new method.",
    )
    c2 = Claim(
        claim_id="CLM-002",
        paper_id="demo",
        claim_types=[ClaimType.MAGNITUDE],
        attribution=Attribution.OWN,
        page=2,
        page_end=2,
        section="Results",
        section_role=SectionRole.RESULTS,
        bbox=(10.0, 20.0, 300.0, 40.0),
        quote="The effect is 3 percent.",
    )
    c1.linked_equation_ids.append("EQ-001")
    assert c2.linked_equation_ids == []


def test_extraction_result_to_dict_json_roundtrip():
    sym = SymbolDef(
        symbol_id="SYM-001",
        symbol="R2_oos",
        normalized="r2oos",
        description="out-of-sample R-squared",
        equation_id="EQ-001",
        page=4,
        section="3 Results",
        bbox=(72.0, 200.0, 500.0, 215.0),
    )
    math_obj = MathObject(
        math_id="EQ-001",
        paper_id="demo",
        kind=MathKind.EVALUATION_FORMULA,
        tag="(1)",
        raw_text="R2_oos = 1 - MSE_m / MSE_b",
        latex=None,
        page=4,
        page_end=4,
        section="3 Results",
        bbox=(100.0, 160.0, 500.0, 185.0),
        tag_bbox=(480.0, 160.0, 500.0, 185.0),
        symbols_defined=[sym],
        linked_claim_ids=["CLM-001"],
    )
    claim = Claim(
        claim_id="CLM-001",
        paper_id="demo",
        claim_types=[ClaimType.FORECAST_ACCURACY, ClaimType.MAGNITUDE],
        attribution=Attribution.OWN,
        page=5,
        page_end=5,
        section="3 Results",
        section_role=SectionRole.RESULTS,
        bbox=(72.0, 120.0, 520.0, 140.0),
        quote="Using Equation (1), R2_oos reaches 4.82%.",
        printed_page=3,
        linked_equation_ids=["EQ-001"],
        linked_symbols=["R2_oos"],
        also_seen_on=[ProvenanceRef(page=1, section="Abstract", bbox=(72.0, 90.0, 500.0, 110.0))],
    )
    result = ExtractionResult(
        paper=PaperMetadata(paper_id="demo", source_path="examples/example_paper.pdf", authors="Author", title="Title"),
        page_count=6,
        ocr_backend="none",
        ocr_policy="none",
        extracted_at="2026-11-20T00:00:00Z",
        sections=[{"section_id": "S01", "heading": "Abstract", "role": "abstract", "page_start": 1, "page_end": 1}],
        claims=[claim],
        math_objects=[math_obj],
        symbols=[sym],
        links=[CrossRefEdge(claim_id="CLM-001", math_id="EQ-001", via="explicit_ref", matched_token="(1)")],
        statistics=[Statistic(kind="percent", text="4.82%", value=4.82, page=5, section="3 Results", bbox=(72.0, 120.0, 520.0, 140.0), context="R2_oos reaches 4.82%.")],
        diagnostics={"ocr_calls": 0},
    )

    payload = result.to_dict()
    encoded = json.dumps(payload)
    decoded = json.loads(encoded)
    assert decoded["claims"][0]["claim_types"] == ["forecast_accuracy", "magnitude"]
    assert decoded["claims"][0]["attribution"] == "own"
    assert decoded["claims"][0]["source_channel"] == SourceChannel.TEXT.value
    assert decoded["claims"][0]["bbox"] == [72.0, 120.0, 520.0, 140.0]
    assert decoded["math_objects"][0]["kind"] == MathKind.EVALUATION_FORMULA.value
    assert decoded["links"][0]["via"] == "explicit_ref"


def test_config_loader_loads_example_papers_and_validates(tmp_path: Path):
    loader = ConfigLoader()
    papers = loader.load_papers(CONFIGS_DIR / "papers.example.yaml")
    assert any(p.paper_id == "example" for p in papers)
    assert all(Path(p.source_path).is_absolute() for p in papers)

    with pytest.raises(FileNotFoundError):
        ConfigLoader(config_dir=tmp_path).load_papers()

    bad = tmp_path / "bad.yaml"
    bad.write_text("- not-a-mapping\n", encoding="utf-8")
    with pytest.raises(TypeError):
        ConfigLoader(config_dir=tmp_path).load("bad.yaml")


def test_enum_values_cover_taxonomy():
    assert BlockKind.FOOTNOTE.value == "footnote"
    assert SectionRole.FRONT_MATTER.value == "front_matter"
    assert len(ClaimType) == 9
    assert len(MathKind) == 8
