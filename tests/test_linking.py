from __future__ import annotations

from econ_pdf_extract.core.models import (
    Attribution,
    Claim,
    ClaimType,
    MathKind,
    MathObject,
    SectionRole,
    SymbolDef,
)
from econ_pdf_extract.linking import CrossReferenceLinker


def _claim(cid: str, quote: str, page: int = 5, math_tokens: list[str] | None = None) -> Claim:
    return Claim(
        claim_id=cid,
        paper_id="demo",
        claim_types=[ClaimType.FORECAST_ACCURACY],
        attribution=Attribution.OWN,
        page=page,
        page_end=page,
        section="3 Results",
        section_role=SectionRole.RESULTS,
        bbox=(72.0, 120.0, 500.0, 134.0),
        quote=quote,
        math_tokens=math_tokens or [],
    )


def test_explicit_ref_named_metric_and_symbol_linking():
    eq1 = MathObject(
        math_id="EQ-001",
        paper_id="demo",
        kind=MathKind.MODEL_SPECIFICATION,
        tag="(1)",
        raw_text="y_t = b_0 + b_1 f_t + e_t",
        latex=None,
        page=4,
        page_end=4,
        section="2 Model",
        bbox=(150.0, 180.0, 500.0, 195.0),
    )
    eq31 = MathObject(
        math_id="EQ-002",
        paper_id="demo",
        kind=MathKind.EVALUATION_FORMULA,
        tag="(3.1)",
        raw_text="CER = mu - 0.5 * gamma * sigma^2",
        latex=None,
        page=5,
        page_end=5,
        section="3 Results",
        bbox=(150.0, 210.0, 500.0, 225.0),
    )
    symbols = [
        SymbolDef(symbol_id="SYM-001", symbol="b_1", normalized="b1", description="slope sensitivity", equation_id="EQ-001", page=4, section="2 Model", bbox=(72.0, 200.0, 400.0, 212.0)),
        SymbolDef(symbol_id="SYM-002", symbol="t", normalized="t", description="time index", equation_id="EQ-001", page=4, section="2 Model", bbox=(72.0, 200.0, 400.0, 212.0)),
    ]

    c1 = _claim("CLM-001", "Using Equation (1), we find that b_1 is positive and improves CER.")
    c2 = _claim("CLM-002", "At time t the average return is modest without mentioning symbols.")

    edges = CrossReferenceLinker().link([c1, c2], [eq1, eq31], symbols)

    assert "EQ-001" in c1.linked_equation_ids
    assert "EQ-002" in c1.linked_equation_ids
    assert "b_1" in c1.linked_symbols
    assert "CER" in c1.linked_symbols
    assert "CLM-001" in eq1.linked_claim_ids
    assert "CLM-001" in eq31.linked_claim_ids

    vias = {(e.claim_id, e.math_id, e.via) for e in edges}
    assert ("CLM-001", "EQ-001", "explicit_ref") in vias
    assert ("CLM-001", "EQ-002", "named_metric") in vias
    assert ("CLM-001", "EQ-001", "symbol") in vias

    # Bare single-letter symbol "t" must NOT spuriously link c2 to EQ-001
    assert c2.linked_equation_ids == []
    assert c2.linked_symbols == []
