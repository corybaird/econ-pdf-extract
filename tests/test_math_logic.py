from __future__ import annotations

from pathlib import Path

from econ_pdf_extract.core.models import (
    Block,
    BlockKind,
    Document,
    Line,
    MathKind,
    MathObject,
    Page,
    Section,
    SectionRole,
    Sentence,
    Span,
)
from econ_pdf_extract.layout import (
    LayoutCleaner,
    PdfReader,
    SectionBuilder,
    SentenceSegmenter,
)
from econ_pdf_extract.math_extract import (
    LogicExtractor,
    MathExtractor,
    SymbolDefinitionExtractor,
)


def _prose_block(bid: str, page: int, text: str, y: float) -> Block:
    bbox = (72.0, y, 500.0, y + 12.0)
    span = Span(text=text, bbox=bbox, font="helv", size=10.0, flags=0, is_bold=False, is_italic=False, is_math_font=False, is_big_op_font=False)
    line = Line(text=text, bbox=bbox, page=page, spans=[span], modal_size=10.0)
    return Block(block_id=bid, page=page, bbox=bbox, lines=[line], kind=BlockKind.PROSE, max_size=10.0, modal_size=10.0, text=text)


def test_empirical_math_kinds_and_symbols_on_synthetic_pdf(synthetic_paper_pdf: Path):
    doc = PdfReader().read(synthetic_paper_pdf)
    LayoutCleaner().clean(doc)
    SectionBuilder().build(doc)
    SentenceSegmenter().segment(doc)

    math_objects, symbols, ocr_calls = MathExtractor().extract(doc)
    assert ocr_calls == 0

    by_tag = {m.tag: m for m in math_objects if m.tag is not None}
    assert by_tag["(1)"].kind == MathKind.MODEL_SPECIFICATION
    assert by_tag["(2.1)"].kind == MathKind.ESTIMATION_PROBLEM
    assert by_tag["(3.1)"].kind == MathKind.EVALUATION_FORMULA

    # Prose logic: Assumption 1 and Algorithm 1
    kinds = {m.kind for m in math_objects}
    assert MathKind.ASSUMPTION in kinds
    assert MathKind.ALGORITHM in kinds

    algo = next(m for m in math_objects if m.kind == MathKind.ALGORITHM)
    assert "Estimate factor loadings" in algo.raw_text
    assert "Update combination weights" in algo.raw_text

    # Symbol definitions extracted from "where y_t denotes excess returns and b_1 measures slope sensitivity."
    sym_map = {s.normalized: s for s in symbols}
    assert "yt" in sym_map
    assert "excess returns" in sym_map["yt"].description
    assert sym_map["yt"].equation_id == by_tag["(1)"].math_id
    assert "b1" in sym_map
    assert "slope sensitivity" in sym_map["b1"].description


def test_proposition_and_definition_and_in_eq_symbol_epilogue():
    b_prop = _prose_block("p01_b01", 1, "Proposition 1. Under weak dependence, the estimator is consistent.", 100.0)
    b_def = _prose_block("p01_b02", 1, "Definition 2. A forecast combination is optimal if it minimizes MSPE.", 140.0)
    sec = Section(section_id="S01", heading="2 Theory", role=SectionRole.METHODOLOGY, page_start=1, page_end=1, blocks=[b_prop, b_def])
    sent = Sentence(
        sentence_id="S01_sent001",
        text="In (2.4), K_{t-1} denotes lagged capital stock and γ represents risk aversion.",
        page=1,
        page_end=1,
        bbox=(72.0, 220.0, 500.0, 232.0),
        section_id="S01",
        section_heading="2 Theory",
        section_role=SectionRole.METHODOLOGY,
        math_tokens=["K_{t-1}", "γ"],
    )
    doc = Document(
        paper_id="theory",
        source_path=Path("theory.pdf"),
        page_count=1,
        body_font_size=10.0,
        pages=[Page(page=1, width=612.0, height=792.0, body_font_size=10.0, blocks=[b_prop, b_def])],
        sections=[sec],
        sentences=[sent],
    )
    prose_objs = LogicExtractor().extract_prose_logic(doc)
    assert {m.kind for m in prose_objs} == {MathKind.PROPOSITION, MathKind.DEFINITION}

    eq24 = MathObject(
        math_id="EQ-001",
        paper_id="theory",
        kind=MathKind.MODEL_SPECIFICATION,
        tag="(2.4)",
        raw_text="y_t = γ K_{t-1} + e_t",
        latex=None,
        page=1,
        page_end=1,
        section="2 Theory",
        bbox=(150.0, 180.0, 480.0, 195.0),
    )
    symbols = SymbolDefinitionExtractor().extract(doc, [eq24])
    by_norm = {s.normalized: s for s in symbols}
    assert "kt-1" in by_norm
    assert by_norm["kt-1"].equation_id == "EQ-001"
    assert "gamma" in by_norm
    assert "risk aversion" in by_norm["gamma"].description
