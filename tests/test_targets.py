from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from econ_pdf_extract.claims.extractor import ClaimExtractor
from econ_pdf_extract.core.models import (
    Attribution,
    Claim,
    ClaimType,
    Document,
    PaperMetadata,
    Section,
    SectionRole,
    Sentence,
    Statistic,
)
from econ_pdf_extract.layout import (
    LayoutCleaner,
    PdfReader,
    SectionBuilder,
    SentenceSegmenter,
)
from econ_pdf_extract.targets import StatisticExtractor, TargetDrafter


def _doc_from_sentences(texts: list[str], page: int = 1, heading: str = "1 Results", role: SectionRole = SectionRole.RESULTS) -> Document:
    sec = Section(section_id="S01", heading=heading, role=role, page_start=page, page_end=page)
    sents = [
        Sentence(
            sentence_id=f"S01_sent{idx:03d}",
            text=t,
            page=page,
            page_end=page,
            bbox=(72.0, 100.0 + idx * 20.0, 500.0, 112.0 + idx * 20.0),
            section_id="S01",
            section_heading=heading,
            section_role=role,
        )
        for idx, t in enumerate(texts, 1)
    ]
    return Document(paper_id="testpaper", source_path=Path("x.pdf"), page_count=page, body_font_size=10.0, sections=[sec], sentences=sents)


def _claim(text: str, claim_id: str = "CLM-001", heading: str = "1 Results", page: int = 2, attribution: Attribution = Attribution.OWN, duplicate_of: str | None = None) -> Claim:
    return Claim(
        claim_id=claim_id,
        paper_id="testpaper",
        claim_types=[ClaimType.MAGNITUDE],
        attribution=attribution,
        page=page,
        page_end=page,
        section=heading,
        section_role=SectionRole.RESULTS,
        bbox=(72.0, 120.0, 500.0, 134.0),
        quote=text,
        duplicate_of=duplicate_of,
    )


@pytest.mark.parametrize(
    ("sentence", "kind", "value"),
    [
        ("The R-squared is 0.85 across all columns of the table.", "r_squared", 0.85),
        ("The coefficient of 0.53 is significant at the five percent level.", "estimate", 0.53),
        ("The estimate is -2.10 and significant, as reported above.", "estimate", -2.10),
        ("The coefficient on exports is 0.44 under the baseline specification here.", "estimate", 0.44),
        ("This effect is significant in every column (p < 0.01) shown above.", "p_value", 0.01),
        ("The p-value of the test equals 0.03, so we reject the null.", "p_value", 0.03),
        ("The t-statistic is 2.34 for the main specification reported there.", "t_stat", 2.34),
        ("Our panel includes 12,405 observations from twenty countries overall.", "sample_size", 12405.0),
        ("In the model N = 404 months are used, matching the source series.", "sample_size", 404.0),
        ("Inflation falls by 1.5 pp after the shock hits the economy.", "percent", 1.5),
        ("Yields compressed by 25 basis points on the announcement day itself.", "percent", 25.0),
        ("The 95% CI [0.12, 0.34] excludes zero, so the effect is real.", "confidence_interval", 0.12),
    ],
)
def test_statistic_extraction(sentence: str, kind: str, value: float):
    stats = StatisticExtractor().extract(_doc_from_sentences([sentence]))
    assert any(s.kind == kind and s.value == value and s.page == 1 for s in stats), stats


def test_statistic_dedup():
    sentence = "The R-squared is 0.85 in every column of every table we show."
    stats = [s for s in StatisticExtractor().extract(_doc_from_sentences([sentence, sentence])) if s.kind == "r_squared"]
    assert len(stats) == 1


def test_no_table_bleed_on_synthetic_pdf(synthetic_paper_pdf: Path):
    doc = PdfReader().read(synthetic_paper_pdf, paper_id="synthetic")
    LayoutCleaner().clean(doc)
    SectionBuilder().build(doc)
    SentenceSegmenter().segment(doc)

    stats = StatisticExtractor().extract(doc)
    # 4.82% and p < 0.01 from cleaned Results prose on page 5 are captured
    assert any(s.kind == "percent" and s.value == pytest.approx(4.82) and s.page == 5 for s in stats)
    assert any(s.kind == "p_value" and s.value == pytest.approx(0.01) and s.page == 5 for s in stats)
    # Table rows (e.g. AR(1) 1.05 / 0.012) must not bleed into statistics
    assert all("AR(1)" not in s.context for s in stats)

    claims = ClaimExtractor().extract(doc)
    paper = PaperMetadata(paper_id="synthetic", source_path=str(synthetic_paper_pdf), authors="Alex Researcher", title="Synthetic")
    drafts = TargetDrafter(paper, claims, stats).targets()
    assert any(d["source"] == "claim" and d["paper_value"] == pytest.approx(4.82) for d in drafts)
    # Literature claim ("Smith et al. (2020)... 12 percent") is excluded from claim targets by default
    assert all("Smith et al." not in d["description"] for d in drafts if d["source"] == "claim")


def test_target_draft_links_claim_to_statistic():
    paper = PaperMetadata(paper_id="testpaper", source_path="x.pdf", authors="A", title="T", journal="J")
    stats = [Statistic(kind="percent", text="1.5 pp", value=1.5, page=2, section="1 Results", bbox=(0.0, 0.0, 10.0, 10.0), context="Inflation falls by 1.5 pp.")]
    drafter = TargetDrafter(paper, [_claim("Inflation falls by 1.5 pp after the shock hits the economy.")], stats)
    targets = drafter.targets()
    assert len(targets) == 1
    t = targets[0]
    assert t["description"] == "Inflation falls by 1.5 pp after the shock hits the economy."
    assert t["location"] == "Section '1 Results', page 2"
    assert t["paper_value"] == 1.5
    assert t["paper_units"] == "pp"
    assert t["our_key"] is None and t["tolerance"] is None and t["tolerance_kind"] is None


def test_target_draft_skips_literature_duplicates_and_unmatched():
    paper = PaperMetadata(paper_id="testpaper", source_path="x.pdf", authors="A", title="T", journal="J")
    stats = [Statistic(kind="percent", text="1.5 pp", value=1.5, page=2, section="1 Results", bbox=(0.0, 0.0, 10.0, 10.0), context="Inflation falls by 1.5 pp.")]
    claims = [
        _claim("Prior work shows 1.5 pp.", claim_id="CLM-001", attribution=Attribution.LITERATURE),
        _claim("Inflation falls by 1.5 pp after the shock hits the economy.", claim_id="CLM-002"),
        _claim("Inflation falls by 1.5 pp in conclusion.", claim_id="CLM-003", duplicate_of="CLM-002"),
    ]
    duplicated = stats + [Statistic(kind="percent", text="1.5 pp", value=1.5, page=2, section="1 Results", bbox=(0.0, 0.0, 10.0, 10.0), context="Inflation falls by 1.5 pp.")]
    targets = TargetDrafter(paper, claims, duplicated).targets()
    assert len(targets) == 1
    assert "after the shock" in targets[0]["description"]


def test_target_draft_truncates_description():
    paper = PaperMetadata(paper_id="testpaper", source_path="x.pdf", authors="A", title="T", journal="J")
    text = "The effect is 2.0 pp and " + "we keep repeating this sentence on purpose " * 3
    stats = [Statistic(kind="percent", text="2.0 pp", value=2.0, page=1, section="1 Results", bbox=(0.0, 0.0, 10.0, 10.0), context=text)]
    target = TargetDrafter(paper, [_claim(text)], stats).targets()[0]
    assert target["description"].endswith("...") and len(target["description"]) <= 123


def test_unlinked_statistic_falls_back_to_section_source():
    paper = PaperMetadata(paper_id="testpaper", source_path="x.pdf", authors="A", title="T", journal="J")
    stats = [Statistic(kind="r_squared", text="R-squared of 0.7", value=0.7, page=4, section="4 Results", bbox=(0.0, 0.0, 10.0, 10.0), context="The regression R-squared is 0.7.")]
    drafts = TargetDrafter(paper, [_claim("We find that monetary policy moves output.")], stats).targets()
    assert len(drafts) == 1 and drafts[0]["source"] == "section"
    assert "Results" in drafts[0]["location"] and drafts[0]["description"].startswith("The regression")


def test_yaml_output_structure_and_run(tmp_path: Path):
    paper = PaperMetadata(paper_id="testpaper", source_path="x.pdf", authors="A", title="T", journal="J")
    stats = [Statistic(kind="percent", text="1.5 pp", value=1.5, page=2, section="1 Results", bbox=(0.0, 0.0, 10.0, 10.0), context="Inflation falls by 1.5 pp.")]
    dest = TargetDrafter(paper, [_claim("Inflation falls by 1.5 pp after the shock hits the economy.")], stats).run(tmp_path)
    assert dest.name.startswith("draft_paper_targets_testpaper_") and dest.suffix == ".yaml"
    text = dest.read_text(encoding="utf-8")
    assert "# TODO: fill in our_key / tolerance / tolerance_kind" in text
    parsed = yaml.safe_load(text)
    assert parsed["targets"][0]["paper_value"] == 1.5
    assert parsed["targets"][0]["our_key"] is None

    empty_text = TargetDrafter(paper, [], []).to_yaml()
    assert yaml.safe_load(empty_text)["targets"] == []
