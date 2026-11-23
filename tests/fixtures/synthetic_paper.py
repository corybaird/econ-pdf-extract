from __future__ import annotations

from pathlib import Path

import pymupdf


def _add_running_chrome(page: pymupdf.Page, printed_page: int, width: float, height: float) -> None:
    page.insert_text((210, 24), "Forecasting Aggregate Returns", fontsize=8.5, fontname="helv")
    page.insert_text((width / 2 - 4, height - 20), str(printed_page), fontsize=9.0, fontname="helv")


def _add_margin_line_numbers(page: pymupdf.Page, start_y: float = 70.0, count: int = 28, step: float = 22.0) -> None:
    for idx in range(1, count + 1):
        y = start_y + (idx - 1) * step
        if y < 740:
            page.insert_text((22, y), str(idx), fontsize=8.0, fontname="helv")


def build_synthetic_paper(dest: Path) -> Path:
    """Create a deterministic 6-page synthetic econ PDF covering all layout/claim/math edge cases."""
    width, height = 612.0, 792.0
    doc = pymupdf.open()

    # Page 1: Duplicate Front Matter (author submission cover copy)
    p1 = doc.new_page(width=width, height=height)
    p1.insert_text((72, 95), "Forecasting Aggregate Returns with Factor Signals", fontsize=14.0, fontname="hebo")
    p1.insert_text((72, 118), "Alex Researcher, University of Economics", fontsize=10.5, fontname="helv")
    p1.insert_text((72, 155), "Abstract", fontsize=11.5, fontname="hebo")
    p1.insert_text(
        (72, 178),
        "I show that factor models substantially improve out-of-sample forecast accuracy across all horizons.",
        fontsize=10.0,
        fontname="helv",
    )
    p1.insert_text(
        (72, 194),
        "Author contact copy for editorial handling only.",
        fontsize=10.0,
        fontname="helv",
    )

    # Page 2: Anonymized Manuscript Start + Canonical Abstract
    p2 = doc.new_page(width=width, height=height)
    _add_running_chrome(p2, printed_page=1, width=width, height=height)
    _add_margin_line_numbers(p2)
    p2.insert_text((72, 90), "Forecasting Aggregate Returns with Factor Signals", fontsize=14.0, fontname="hebo")
    p2.insert_text((72, 130), "Abstract", fontsize=11.5, fontname="hebo")
    p2.insert_text(
        (72, 154),
        "I show that factor models substantially improve out-of-sample forecast accuracy across all horizons.",
        fontsize=10.0,
        fontname="helv",
    )
    p2.insert_text(
        (72, 170),
        "Measurement noise creates a significant challenge for standard linear panel specifications.",
        fontsize=10.0,
        fontname="helv",
    )
    p2.insert_text(
        (72, 186),
        "My estimator achieves lower RMSE than standard autoregressive benchmarks.",
        fontsize=10.0,
        fontname="helv",
    )

    # Page 3: 1 Introduction (part 1) + literature claim + citation break + footnote
    p3 = doc.new_page(width=width, height=height)
    _add_running_chrome(p3, printed_page=2, width=width, height=height)
    _add_margin_line_numbers(p3)
    p3.insert_text((72, 92), "1 Introduction", fontsize=12.0, fontname="hebo")
    p3.insert_text(
        (72, 120),
        "Smith et al. (2020) show that trade shocks explain 12 percent of export variance.",
        fontsize=10.0,
        fontname="helv",
    )
    p3.insert_text(
        (72, 140),
        "Following earlier studies (Miller et al.",
        fontsize=10.0,
        fontname="helv",
    )
    p3.insert_text(
        (72, 155),
        "2018), I decompose regional output into cyclical and trend components.",
        fontsize=10.0,
        fontname="helv",
    )
    p3.insert_text(
        (72, 180),
        "This paper proposes a parsimonious factor-augmented projection for asset returns.",
        fontsize=10.0,
        fontname="helv",
    )
    # Footnote separator rule + 8pt footnote
    p3.draw_line(pymupdf.Point(72, 668), pymupdf.Point(212, 668), width=0.6)
    p3.insert_text(
        (72, 684),
        "1 We find that footnote leakage should be filtered and never emitted as a body claim.",
        fontsize=8.0,
        fontname="helv",
    )

    # Page 4: 1 Introduction (part 2) + 2 Model and Estimation
    p4 = doc.new_page(width=width, height=height)
    _add_running_chrome(p4, printed_page=3, width=width, height=height)
    _add_margin_line_numbers(p4)
    p4.insert_text(
        (72, 90),
        "I further demonstrate that the extended specification delivers superior directional accuracy during recessions.",
        fontsize=10.0,
        fontname="helv",
    )
    p4.insert_text((72, 130), "2 Model and Estimation", fontsize=12.0, fontname="hebo")
    p4.insert_text((72, 155), "The baseline predictive regression takes the form", fontsize=10.0, fontname="helv")

    # Numbered display equation (1) with right-margin tag and Symbol span
    p4.insert_text((170, 185), "y_t ", fontsize=10.0, fontname="tiit")
    p4.insert_text((190, 185), "= ", fontsize=10.0, fontname="symb")
    p4.insert_text((202, 185), "b_0 + b_1 f_t + e_t", fontsize=10.0, fontname="tiit")
    p4.insert_text((500, 185), "(1)", fontsize=10.0, fontname="helv")

    p4.insert_text(
        (72, 212),
        "where y_t denotes excess returns and b_1 measures slope sensitivity.",
        fontsize=10.0,
        fontname="helv",
    )

    # Unnumbered centered display equation
    p4.insert_text((185, 250), "f_t ", fontsize=10.0, fontname="tiit")
    p4.insert_text((202, 250), "= ", fontsize=10.0, fontname="symb")
    p4.insert_text((214, 250), "a_0 + a_1 z_t", fontsize=10.0, fontname="tiit")

    p4.insert_text(
        (72, 286),
        "The optimal weights are obtained by solving",
        fontsize=10.0,
        fontname="helv",
    )

    # Tall stacked multi-line argmin equation (2.1) with fraction bar (triggers needs_ocr)
    p4.insert_text((175, 315), "w* = argmin_w ", fontsize=10.0, fontname="tiit")
    p4.insert_text((255, 315), "S ", fontsize=10.0, fontname="symb")
    p4.insert_text((266, 315), "(y_t - w' x_t)^2", fontsize=10.0, fontname="tiit")
    p4.draw_line(pymupdf.Point(255, 322), pymupdf.Point(340, 322), width=0.6)
    p4.insert_text((285, 336), "T", fontsize=10.0, fontname="tiit")
    p4.insert_text((175, 350), "s.t.  sum(w) = 1", fontsize=10.0, fontname="tiit")
    p4.insert_text((495, 330), "(2.1)", fontsize=10.0, fontname="helv")

    p4.insert_text(
        (72, 385),
        "Assumption 1. The innovation sequence is a martingale difference sequence with finite fourth moments.",
        fontsize=10.0,
        fontname="helv",
    )

    p4.insert_text((72, 422), "Algorithm 1: Recursive Forecast Combination", fontsize=10.5, fontname="hebo")
    p4.insert_text((82, 442), "1. Estimate factor loadings on the expanding sample window.", fontsize=10.0, fontname="helv")
    p4.insert_text((82, 458), "2. Update combination weights by minimizing squared forecast errors.", fontsize=10.0, fontname="helv")

    # Page 5: 3 Empirical Results + split decimal + CER radical formula + booktabs table + captions
    p5 = doc.new_page(width=width, height=height)
    _add_running_chrome(p5, printed_page=4, width=width, height=height)
    _add_margin_line_numbers(p5)
    p5.insert_text((72, 92), "3 Empirical Results", fontsize=12.0, fontname="hebo")
    p5.insert_text(
        (72, 120),
        "Using Equation (1), the out-of-sample R2_oos reaches 4 .",
        fontsize=10.0,
        fontname="helv",
    )
    p5.insert_text(
        (72, 134),
        "82% across the full evaluation window.",
        fontsize=10.0,
        fontname="helv",
    )
    p5.insert_text(
        (72, 158),
        "The equality test rejects the baseline benchmark at the 5% significance level (p < 0.01).",
        fontsize=10.0,
        fontname="helv",
    )
    p5.insert_text(
        (72, 182),
        "Portfolio allocation translates into economic gains with a higher CER than the historical mean.",
        fontsize=10.0,
        fontname="helv",
    )

    # Evaluation formula (3.1) containing radical fragment v u u t (triggers needs_ocr)
    p5.insert_text((160, 218), "CER ", fontsize=10.0, fontname="tiit")
    p5.insert_text((185, 218), "= ", fontsize=10.0, fontname="symb")
    p5.insert_text((197, 218), "mu - 0.5 * gamma * v u u t sigma2", fontsize=10.0, fontname="tiit")
    p5.insert_text((495, 218), "(3.1)", fontsize=10.0, fontname="helv")

    # Booktabs table with caption
    p5.insert_text((72, 275), "Table 1: Out-of-sample regression results", fontsize=10.0, fontname="hebo")
    p5.draw_line(pymupdf.Point(72, 286), pymupdf.Point(520, 286), width=0.8)
    p5.insert_text((78, 300), "Model          h=1       h=3       h=12      R2_oos", fontsize=9.5, fontname="cour")
    p5.draw_line(pymupdf.Point(72, 307), pymupdf.Point(520, 307), width=0.5)
    p5.insert_text((78, 322), "AR(1)         1.05      1.12      1.24       0.012", fontsize=9.5, fontname="cour")
    p5.insert_text((78, 338), "Factor        0.91      0.94      0.98       0.036", fontsize=9.5, fontname="cour")
    p5.insert_text((78, 354), "Combo         0.89      0.92      0.95       0.041", fontsize=9.5, fontname="cour")
    p5.insert_text((78, 370), "DM-p          0.01      0.03      0.04       0.005", fontsize=9.5, fontname="cour")
    p5.draw_line(pymupdf.Point(72, 378), pymupdf.Point(520, 378), width=0.8)

    p5.insert_text((72, 415), "Figure 1: Forecast errors across rolling evaluation windows", fontsize=10.0, fontname="hebo")

    # Page 6: 4 Conclusion (near-duplicate of Abstract) + References (excluded)
    p6 = doc.new_page(width=width, height=height)
    _add_running_chrome(p6, printed_page=5, width=width, height=height)
    _add_margin_line_numbers(p6)
    p6.insert_text((72, 92), "4 Conclusion", fontsize=12.0, fontname="hebo")
    p6.insert_text(
        (72, 120),
        "Overall, I show that factor models substantially improve out-of-sample forecast accuracy across all horizons.",
        fontsize=10.0,
        fontname="helv",
    )
    p6.insert_text(
        (72, 142),
        "The results are robust to alternative lag lengths and estimation windows.",
        fontsize=10.0,
        fontname="helv",
    )
    p6.insert_text((72, 200), "References", fontsize=12.0, fontname="hebo")
    p6.insert_text(
        (72, 228),
        "Doe, J. (2021). We find that interest rates predict inflation by 4 percent. Journal of Finance, 76(2), 100-120.",
        fontsize=9.5,
        fontname="helv",
    )

    dest.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(dest))
    doc.close()
    return dest
