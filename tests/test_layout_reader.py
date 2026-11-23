from __future__ import annotations

from pathlib import Path

import pytest

from econ_pdf_extract.layout.reader import PdfReader


def test_embedded_text_metrics(synthetic_paper_pdf: Path):
    doc = PdfReader().read(synthetic_paper_pdf, paper_id="synthetic")
    assert doc.paper_id == "synthetic"
    assert doc.page_count == 6
    assert 9.5 <= doc.body_font_size <= 10.5
    assert len(doc.pages) == 6

    for page in doc.pages:
        assert page.width == pytest.approx(612.0, abs=1.0)
        assert page.height == pytest.approx(792.0, abs=1.0)
        assert page.char_count > 100
        assert page.image_count == 0
        assert page.body_font_size > 0


def test_horizontal_rules_and_math_fonts_detected(synthetic_paper_pdf: Path):
    doc = PdfReader().read(synthetic_paper_pdf)
    # Page 3 has footnote separator rule
    p3 = doc.pages[2]
    assert any(120.0 <= (r[2] - r[0]) <= 160.0 and (r[3] - r[1]) <= 2.5 for r in p3.horizontal_rules)

    # Page 4 has Symbol math spans and a fraction bar rule
    p4 = doc.pages[3]
    math_lines = [line for block in p4.blocks for line in block.lines if line.has_math_font]
    assert len(math_lines) >= 3
    assert any(60.0 <= (r[2] - r[0]) <= 120.0 for r in p4.horizontal_rules)

    # Page 5 has booktabs horizontal rules for Table 1
    p5 = doc.pages[4]
    full_rules = [r for r in p5.horizontal_rules if (r[2] - r[0]) >= 400.0]
    assert len(full_rules) >= 3


def test_missing_pdf_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        PdfReader().read(tmp_path / "does_not_exist.pdf")
