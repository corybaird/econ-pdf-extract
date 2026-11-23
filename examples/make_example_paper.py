from pathlib import Path

import pymupdf

PDF = Path(__file__).resolve().parent / "example_paper.pdf"

TITLE = "The Output Response to Monetary Policy Shocks: A Direct Projection Approach"
AUTHORS = "Example A. Author and Example B. Author"

# Known statistics are asserted in tests/test_example_paper.py.
# Sentence wording must keep matching references/configs/target_patterns.yaml;
# regenerate this PDF after editing: uv run python examples/make_example_paper.py
PAGES = {
    1: [
        TITLE,
        AUTHORS,
        "1 Introduction",
        "We find that monetary policy surprises reduce industrial production by 3.2 percent on impact.",
        "The estimate on the policy surprise is -0.42 and is significant at the one percent level (p < 0.01).",
        "Our results show that this estimate is robust to alternative identification schemes and sample windows.",
    ],
    2: [
        "2 Results and Diagnostics",
        "The regression R-squared is 0.21, the t-statistic is 3.45, and N = 214 observations.",
        "The 95% CI is [-1.8, -0.9] percent wide, and the placebo regression yields an R-squared of 0.02.",
        "Section 3 shows that these findings are concentrated in recession periods.",
    ],
}


def run():
    doc = pymupdf.open()
    for page_number, lines in PAGES.items():
        page = doc.new_page(width=612, height=792)
        for i, line in enumerate(lines):
            size = 13 if i == 0 and page_number == 1 else 12 if is_heading(i, page_number) else 10
            font = "hebo" if i == 0 and page_number == 1 or is_heading(i, page_number) else "helv"
            page.insert_text((72, 90 + 34 * i), line, fontsize=size, fontname=font)
    doc.save(str(PDF))
    doc.close()
    print(f"wrote {PDF}")


def is_heading(i, page_number):
    return (page_number == 1 and i in (2,)) or (page_number == 2 and i == 0)


if __name__ == "__main__":
    run()
