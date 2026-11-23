from __future__ import annotations

from pathlib import Path

from econ_pdf_extract.core.models import (
    Block,
    BlockKind,
    Document,
    Line,
    Page,
    Section,
    SectionRole,
    Span,
)
from econ_pdf_extract.layout import LayoutCleaner, PdfReader, SectionBuilder
from econ_pdf_extract.math_extract import DisplayEquationDetector


def _span(text: str, bbox: tuple[float, float, float, float], font: str = "helv", is_math: bool = False, is_big_op: bool = False) -> Span:
    return Span(text=text, bbox=bbox, font=font, size=10.0, flags=0, is_bold=False, is_italic=False, is_math_font=is_math, is_big_op_font=is_big_op)


def _block(bid: str, page: int, lines: list[Line]) -> Block:
    bbox = (
        min(ln.bbox[0] for ln in lines),
        min(ln.bbox[1] for ln in lines),
        max(ln.bbox[2] for ln in lines),
        max(ln.bbox[3] for ln in lines),
    )
    return Block(block_id=bid, page=page, bbox=bbox, lines=lines, kind=BlockKind.PROSE, max_size=10.0, modal_size=10.0, text="\n".join(ln.text for ln in lines))


def test_raw_text_not_mangled_and_tables_excluded(synthetic_paper_pdf: Path):
    doc = SectionBuilder().build(LayoutCleaner().clean(PdfReader().read(synthetic_paper_pdf)))
    displays = DisplayEquationDetector().detect(doc)

    tags = [d.tag for d in displays]
    assert "(1)" in tags
    assert "(2.1)" in tags
    assert "(3.1)" in tags

    # Unnumbered centered display f_t = a_0 + a_1 z_t also detected
    assert any(d.tag is None and "f_t" in d.raw_text for d in displays)

    eq1 = next(d for d in displays if d.tag == "(1)")
    assert eq1.page == 4
    assert eq1.section == "2 Model and Estimation"
    assert eq1.tag_bbox is not None
    assert "b_0" in eq1.raw_text and "\\beta" not in eq1.raw_text
    assert eq1.latex is None

    # Tables and captions from page 5 must not be emitted as displays
    all_raw = " ".join(d.raw_text for d in displays)
    assert "AR(1)" not in all_raw
    assert "Table 1" not in all_raw
    assert "Figure 1" not in all_raw


def test_radical_fragment_and_stacked_fraction_trigger_ocr(synthetic_paper_pdf: Path):
    doc = SectionBuilder().build(LayoutCleaner().clean(PdfReader().read(synthetic_paper_pdf)))
    displays = DisplayEquationDetector().detect(doc)

    eq21 = next(d for d in displays if d.tag == "(2.1)")
    assert eq21.needs_ocr is True
    assert "stacked_fraction" in eq21.ocr_reasons or "tall_multiline" in eq21.ocr_reasons

    eq31 = next(d for d in displays if d.tag == "(3.1)")
    assert eq31.needs_ocr is True
    assert "radical_fragment" in eq31.ocr_reasons


def test_multiline_and_subsup_grouping_and_separate_stacked_tags():
    # Wrapped 2-line eq (9) vs stacked align eqs (10) and (11)
    l_prose = Line(text="The model implies the following relations:", bbox=(72.0, 90.0, 420.0, 102.0), page=1, spans=[_span("The model implies the following relations:", (72.0, 90.0, 420.0, 102.0))])
    # Sub/sup split on baseline for eq (9)
    l9a = Line(
        text="q",
        bbox=(160.0, 120.0, 260.0, 130.0),
        page=1,
        spans=[
            _span("q", (160.0, 120.0, 175.0, 130.0), font="CMMI10", is_math=True),
            _span("(k)", (176.0, 117.0, 190.0, 125.0), font="CMR7", is_math=False),
            _span("= a_0 + b_1 y_t", (195.0, 120.0, 275.0, 130.0), font="CMMI10", is_math=True),
        ],
        has_math_font=True,
    )
    l9b = Line(
        text="+ b_2 z_t",
        bbox=(180.0, 133.0, 520.0, 143.0),
        page=1,
        spans=[
            _span("+ b_2 z_t", (180.0, 133.0, 240.0, 143.0), font="CMMI10", is_math=True),
            _span("(9)", (500.0, 133.0, 520.0, 143.0), font="CMR10"),
        ],
        has_math_font=True,
    )
    l10 = Line(
        text="x_t = rho x_{t-1} + u_t (10)",
        bbox=(160.0, 152.0, 520.0, 162.0),
        page=1,
        spans=[
            _span("x_t = rho x_{t-1} + u_t", (160.0, 152.0, 310.0, 162.0), font="CMMI10", is_math=True),
            _span("(10)", (495.0, 152.0, 520.0, 162.0), font="CMR10"),
        ],
        has_math_font=True,
    )
    l11 = Line(
        text="y_t = phi y_{t-1} + e_t (11)",
        bbox=(160.0, 168.0, 520.0, 178.0),
        page=1,
        spans=[
            _span("y_t = phi y_{t-1} + e_t", (160.0, 168.0, 310.0, 178.0), font="CMMI10", is_math=True),
            _span("(11)", (495.0, 168.0, 520.0, 178.0), font="CMR10"),
        ],
        has_math_font=True,
    )
    block = _block("p01_b01", 1, [l_prose, l9a, l9b, l10, l11])
    page = Page(page=1, width=612.0, height=792.0, body_font_size=10.0, blocks=[block])
    sec = Section(section_id="S01", heading="2 Model", role=SectionRole.METHODOLOGY, page_start=1, page_end=1, blocks=[block])
    doc = Document(paper_id="align", source_path=Path("align.pdf"), page_count=1, body_font_size=10.0, pages=[page], sections=[sec])

    displays = DisplayEquationDetector().detect(doc)
    by_tag = {d.tag: d for d in displays}
    assert set(by_tag.keys()) == {"(9)", "(10)", "(11)"}
    assert "q" in by_tag["(9)"].raw_text and "(k)" in by_tag["(9)"].raw_text and "b_2 z_t" in by_tag["(9)"].raw_text
    assert "rho" in by_tag["(10)"].raw_text and "phi" not in by_tag["(10)"].raw_text
    assert "phi" in by_tag["(11)"].raw_text


def test_case_brace_pua_and_tx_big_op_trigger_ocr():
    l_pua = Line(
        text="L(e) = \uf8f1 e if e > 0 (2.5)",
        bbox=(150.0, 120.0, 520.0, 132.0),
        page=1,
        spans=[
            _span("L(e) = \uf8f1 e if e > 0", (150.0, 120.0, 310.0, 132.0), font="CMSY10", is_math=True),
            _span("(2.5)", (490.0, 120.0, 520.0, 132.0), font="CMR10"),
        ],
        has_math_font=True,
    )
    l_tx = Line(
        text="CRPS = Z ∞ F(y)^2 dy (2.6)",
        bbox=(150.0, 170.0, 520.0, 182.0),
        page=1,
        spans=[
            _span("CRPS = ", (150.0, 170.0, 195.0, 182.0), font="rtxmi", is_math=True),
            _span("Z", (196.0, 170.0, 206.0, 182.0), font="txex", is_math=True, is_big_op=True),
            _span(" ∞ F(y)^2 dy", (207.0, 170.0, 300.0, 182.0), font="rtxmi", is_math=True),
            _span("(2.6)", (490.0, 170.0, 520.0, 182.0), font="rtxr"),
        ],
        has_math_font=True,
        has_big_op_font=True,
    )
    block = _block("p01_b01", 1, [l_pua, l_tx])
    page = Page(page=1, width=612.0, height=792.0, body_font_size=10.0, blocks=[block])
    doc = Document(paper_id="deg", source_path=Path("deg.pdf"), page_count=1, body_font_size=10.0, pages=[page])

    displays = DisplayEquationDetector().detect(doc)
    by_tag = {d.tag: d for d in displays}
    assert by_tag["(2.5)"].needs_ocr is True
    assert "private_use_glyph" in by_tag["(2.5)"].ocr_reasons
    assert by_tag["(2.6)"].needs_ocr is True
    assert "big_op_font" in by_tag["(2.6)"].ocr_reasons
    assert "flattened_big_op" in by_tag["(2.6)"].ocr_reasons
