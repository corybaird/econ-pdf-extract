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
from econ_pdf_extract.layout import (
    LayoutCleaner,
    PdfReader,
    SectionBuilder,
    SentenceSegmenter,
)


def _line(page: int, text: str, y: float) -> Line:
    bbox = (72.0, y, 500.0, y + 12.0)
    span = Span(text=text, bbox=bbox, font="helv", size=10.0, flags=0, is_bold=False, is_italic=False, is_math_font=False, is_big_op_font=False)
    return Line(text=text, bbox=bbox, page=page, spans=[span], modal_size=10.0)


def test_decimal_and_citation_splits(synthetic_paper_pdf: Path):
    doc = PdfReader().read(synthetic_paper_pdf)
    LayoutCleaner().clean(doc)
    SectionBuilder().build(doc)
    SentenceSegmenter().segment(doc)

    texts = [s.text for s in doc.sentences]
    # Split decimal "4 .\n82%" must be rejoined into a single sentence on page 5
    r2_sents = [s for s in doc.sentences if "4.82%" in s.text]
    assert len(r2_sents) == 1
    assert r2_sents[0].page == 5
    assert r2_sents[0].section_role == SectionRole.RESULTS

    # Citation break "(Miller et al.\n2018)" must stay intact as one sentence on page 3
    cit_sents = [s for s in doc.sentences if "Miller et al." in s.text]
    assert len(cit_sents) == 1
    assert "2018), I decompose regional output" in cit_sents[0].text
    assert cit_sents[0].page == 3

    # Footnote text never enters sentences
    assert all("footnote leakage" not in t for t in texts)


def test_multipage_section_true_page(synthetic_paper_pdf: Path):
    doc = PdfReader().read(synthetic_paper_pdf)
    LayoutCleaner().clean(doc)
    SectionBuilder().build(doc)
    SentenceSegmenter().segment(doc)

    # Continuation claim in "1 Introduction" sits on page 4, not section start page 3
    p4_claims = [s for s in doc.sentences if "superior directional accuracy" in s.text]
    assert len(p4_claims) == 1
    assert p4_claims[0].section_heading == "1 Introduction"
    assert p4_claims[0].page == 4
    assert p4_claims[0].page_end == 4


def test_hyphen_rejoin_and_page_wrap():
    l1 = _line(7, "We show that out-of-sample fore-", 720.0)
    l2 = _line(8, "casting accuracy improves markedly across horizons.", 80.0)
    b1 = Block(block_id="p07_b01", page=7, bbox=l1.bbox, lines=[l1], kind=BlockKind.PROSE, text=l1.text)
    b2 = Block(block_id="p08_b01", page=8, bbox=l2.bbox, lines=[l2], kind=BlockKind.PROSE, text=l2.text)
    sec = Section(section_id="S01", heading="4 Results", role=SectionRole.RESULTS, page_start=7, page_end=8, blocks=[b1, b2])
    doc = Document(
        paper_id="wrap",
        source_path=Path("wrap.pdf"),
        page_count=8,
        body_font_size=10.0,
        pages=[Page(page=7, width=612.0, height=792.0, body_font_size=10.0), Page(page=8, width=612.0, height=792.0, body_font_size=10.0)],
        sections=[sec],
    )
    SentenceSegmenter().segment(doc)
    assert len(doc.sentences) == 1
    sent = doc.sentences[0]
    assert "out-of-sample forecasting accuracy" in sent.text
    assert sent.page == 7
    assert sent.page_end == 8
