from __future__ import annotations

from pathlib import Path

from econ_pdf_extract.core.models import (
    Block,
    BlockKind,
    Document,
    Line,
    Page,
    SectionRole,
    Span,
)
from econ_pdf_extract.layout.cleaners import LayoutCleaner
from econ_pdf_extract.layout.reader import PdfReader
from econ_pdf_extract.layout.sections import SectionBuilder


def _heading_block(page: int, idx: int, text: str, y: float) -> Block:
    bbox = (72.0, y, 420.0, y + 14.0)
    span = Span(text=text, bbox=bbox, font="hebo", size=12.0, flags=16, is_bold=True, is_italic=False, is_math_font=False, is_big_op_font=False)
    line = Line(text=text, bbox=bbox, page=page, spans=[span], modal_size=12.0)
    return Block(block_id=f"p{page:02d}_b{idx:02d}", page=page, bbox=bbox, lines=[line], kind=BlockKind.PROSE, is_bold=True, max_size=12.0, modal_size=12.0, text=text)


def _prose_block(page: int, idx: int, text: str, y: float) -> Block:
    bbox = (72.0, y, 500.0, y + 12.0)
    span = Span(text=text, bbox=bbox, font="helv", size=10.0, flags=0, is_bold=False, is_italic=False, is_math_font=False, is_big_op_font=False)
    line = Line(text=text, bbox=bbox, page=page, spans=[span], modal_size=10.0)
    return Block(block_id=f"p{page:02d}_b{idx:02d}", page=page, bbox=bbox, lines=[line], kind=BlockKind.PROSE, is_bold=False, max_size=10.0, modal_size=10.0, text=text)


def test_duplicate_front_matter_prefers_manuscript(synthetic_paper_pdf: Path):
    doc = SectionBuilder().build(LayoutCleaner().clean(PdfReader().read(synthetic_paper_pdf)))

    abstracts = [s for s in doc.sections if s.role == SectionRole.ABSTRACT]
    assert len(abstracts) == 1
    assert abstracts[0].page_start == 2
    assert 1 in doc.duplicate_front_matter_pages

    demoted = [s for s in doc.sections if s.is_duplicate_front_matter]
    assert any(s.heading == "Abstract" and s.page_start == 1 for s in demoted)

    roles_by_heading = {s.heading: s.role for s in doc.sections if not s.is_duplicate_front_matter}
    assert roles_by_heading["1 Introduction"] == SectionRole.INTRODUCTION
    assert roles_by_heading["2 Model and Estimation"] == SectionRole.METHODOLOGY
    assert roles_by_heading["3 Empirical Results"] == SectionRole.RESULTS
    assert roles_by_heading["4 Conclusion"] == SectionRole.CONCLUSION
    assert roles_by_heading["References"] == SectionRole.REFERENCES

    intro = next(s for s in doc.sections if s.heading == "1 Introduction")
    assert intro.page_start == 3
    assert intro.page_end == 4


def test_subsection_role_inheritance():
    p1 = Page(
        page=1,
        width=612.0,
        height=792.0,
        body_font_size=10.0,
        blocks=[
            _heading_block(1, 1, "5 Forecast Results", 80.0),
            _prose_block(1, 2, "Overview of forecasting exercise across macro series.", 105.0),
            _heading_block(1, 3, "5.1 Exports", 140.0),
            _prose_block(1, 4, "Regional export growth improves under the alternative tariff schedule.", 165.0),
            _heading_block(1, 5, "5.2 Inflation", 200.0),
            _prose_block(1, 6, "For inflation the benchmark performs comparably.", 225.0),
        ],
    )
    doc = Document(paper_id="inherit", source_path=Path("inherit.pdf"), page_count=1, body_font_size=10.0, pages=[p1])
    SectionBuilder().build(doc)

    by_heading = {s.heading: s.role for s in doc.sections}
    assert by_heading["5 Forecast Results"] == SectionRole.RESULTS
    assert by_heading["5.1 Exports"] == SectionRole.RESULTS
    assert by_heading["5.2 Inflation"] == SectionRole.RESULTS
