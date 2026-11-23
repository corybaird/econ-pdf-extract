from __future__ import annotations

from pathlib import Path

from econ_pdf_extract.core.models import Block, BlockKind, Document, Line, Page, Span
from econ_pdf_extract.layout.cleaners import LayoutCleaner
from econ_pdf_extract.layout.reader import PdfReader


def _make_block(block_id: str, page: int, text: str, bbox: tuple[float, float, float, float], size: float = 10.0, is_bold: bool = False) -> Block:
    span = Span(text=text, bbox=bbox, font="helv", size=size, flags=16 if is_bold else 0, is_bold=is_bold, is_italic=False, is_math_font=False, is_big_op_font=False)
    line = Line(text=text, bbox=bbox, page=page, spans=[span], modal_size=size)
    return Block(block_id=block_id, page=page, bbox=bbox, lines=[line], kind=BlockKind.PROSE, is_bold=is_bold, max_size=size, modal_size=size, text=text)


def test_margin_noise_and_headers_filtered_on_synthetic_pdf(synthetic_paper_pdf: Path):
    doc = LayoutCleaner().clean(PdfReader().read(synthetic_paper_pdf))
    # Page 2 has margin line numbers and running chrome
    p2 = doc.pages[1]
    assert p2.printed_page == 1
    margin_blocks = [b for b in p2.blocks if b.kind == BlockKind.MARGIN_NOISE]
    header_blocks = [b for b in p2.blocks if b.kind == BlockKind.HEADER_FOOTER]
    assert len(margin_blocks) >= 10
    assert len(header_blocks) >= 1

    # No prose block on page 2 should be a bare line number
    prose_texts = [b.text.strip() for b in p2.blocks if b.kind == BlockKind.PROSE]
    assert all(not t.isdigit() for t in prose_texts)


def test_margin_line_numbers_on_a4_dimensions():
    a4_page = Page(
        page=1,
        width=595.0,
        height=842.0,
        body_font_size=10.0,
        blocks=[
            _make_block("p01_b01", 1, "1", (20.0, 100.0, 35.0, 110.0), size=8.0),
            _make_block("p01_b02", 1, "2", (540.0, 100.0, 560.0, 110.0), size=8.0),
            _make_block("p01_b03", 1, "Main body sentence on an A4 page.", (72.0, 100.0, 480.0, 112.0), size=10.0),
        ],
    )
    doc = Document(paper_id="a4", source_path=Path("a4.pdf"), page_count=1, body_font_size=10.0, pages=[a4_page])
    LayoutCleaner().clean(doc)
    assert a4_page.blocks[0].kind == BlockKind.MARGIN_NOISE
    assert a4_page.blocks[1].kind == BlockKind.MARGIN_NOISE
    assert a4_page.blocks[2].kind == BlockKind.PROSE


def test_footnote_excluded_from_prose(synthetic_paper_pdf: Path):
    doc = LayoutCleaner().clean(PdfReader().read(synthetic_paper_pdf))
    p3 = doc.pages[2]
    footnotes = [b for b in p3.blocks if b.kind == BlockKind.FOOTNOTE]
    assert any("footnote leakage" in b.text for b in footnotes)
    prose = " ".join(b.text for b in p3.blocks if b.kind == BlockKind.PROSE)
    assert "footnote leakage" not in prose


def test_footnote_above_bottom_table_and_no_rule_fallback():
    # Page 1: footnote sits at 55% height ABOVE a bottom float table
    p1 = Page(
        page=1,
        width=612.0,
        height=792.0,
        body_font_size=10.0,
        horizontal_rules=[
            (72.0, 430.0, 200.0, 430.6),  # footnote rule
            (72.0, 560.0, 530.0, 560.8),  # table top rule
            (72.0, 680.0, 530.0, 680.8),  # table bottom rule
        ],
        blocks=[
            _make_block("p01_b01", 1, "This is the main body text above the footnote separator.", (72.0, 120.0, 530.0, 134.0), size=10.0),
            _make_block("p01_b02", 1, "1 This footnote sits above the bottom table.", (72.0, 442.0, 490.0, 452.0), size=8.5),
            _make_block("p01_b03", 1, "Table 2: Bottom float results", (72.0, 540.0, 260.0, 552.0), size=10.0, is_bold=True),
            _make_block("p01_b04", 1, "Model 1.01 0.92 0.85\nAR 1.10 0.99 0.95\nVAR 1.05 0.96 0.91", (72.0, 575.0, 500.0, 660.0), size=9.0),
        ],
    )
    # Page 2: no footnote rule, small-font footnote in lower 35%
    p2 = Page(
        page=2,
        width=612.0,
        height=792.0,
        body_font_size=10.0,
        blocks=[
            _make_block("p02_b01", 2, "Regular prose paragraph in the upper half of the page.", (72.0, 150.0, 530.0, 164.0), size=10.0),
            _make_block("p02_b02", 2, "2 Fallback footnote without a separator rule.", (72.0, 650.0, 480.0, 660.0), size=8.0),
        ],
    )
    doc = Document(paper_id="fn", source_path=Path("fn.pdf"), page_count=2, body_font_size=10.0, pages=[p1, p2])
    LayoutCleaner().clean(doc)

    assert p1.blocks[0].kind == BlockKind.PROSE
    assert p1.blocks[1].kind == BlockKind.FOOTNOTE
    assert p1.blocks[2].kind == BlockKind.CAPTION
    assert p1.blocks[3].kind == BlockKind.TABLE
    assert p2.blocks[0].kind == BlockKind.PROSE
    assert p2.blocks[1].kind == BlockKind.FOOTNOTE


def test_booktabs_table_and_captions_tagged(synthetic_paper_pdf: Path):
    doc = LayoutCleaner().clean(PdfReader().read(synthetic_paper_pdf))
    p5 = doc.pages[4]
    captions = [b.text for b in p5.blocks if b.kind == BlockKind.CAPTION]
    tables = [b.text for b in p5.blocks if b.kind == BlockKind.TABLE]
    prose = " ".join(b.text for b in p5.blocks if b.kind == BlockKind.PROSE)

    assert any("Table 1:" in c for c in captions)
    assert any("Figure 1:" in c for c in captions)
    assert any("AR(1)" in t for t in tables)
    assert "AR(1)" not in prose
    assert "Figure 1:" not in prose
    assert "R2_oos reaches" in prose
