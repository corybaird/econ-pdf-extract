from __future__ import annotations

from pathlib import Path

from econ_pdf_extract.claims.attribution import AttributionClassifier
from econ_pdf_extract.claims.classifier import ClaimClassifier
from econ_pdf_extract.claims.dedup import ClaimDeduplicator
from econ_pdf_extract.claims.extractor import ClaimExtractor
from econ_pdf_extract.claims.refiner import ClaimRefiner, NullClaimRefiner
from econ_pdf_extract.core.models import (
    Attribution,
    Claim,
    ClaimType,
    Document,
    SectionRole,
)
from econ_pdf_extract.layout import (
    LayoutCleaner,
    PdfReader,
    SectionBuilder,
    SentenceSegmenter,
)


def _extract_synthetic(pdf_path: Path, refiner: ClaimRefiner | None = None) -> tuple[Document, list[Claim]]:
    doc = PdfReader().read(pdf_path, paper_id="synthetic")
    LayoutCleaner().clean(doc)
    SectionBuilder().build(doc)
    SentenceSegmenter().segment(doc)
    claims = ClaimExtractor(refiner=refiner).extract(doc)
    return doc, claims


def test_results_section_claims_extracted(synthetic_paper_pdf: Path):
    _, claims = _extract_synthetic(synthetic_paper_pdf)
    results_claims = [c for c in claims if c.section_role == SectionRole.RESULTS]
    assert len(results_claims) >= 3
    assert any("4.82%" in c.quote and c.page == 5 for c in results_claims)
    assert any(ClaimType.SIGNIFICANCE in c.claim_types and c.page == 5 for c in results_claims)
    assert any(ClaimType.ECONOMIC_VALUE in c.claim_types and c.page == 5 for c in results_claims)

    # References section claims must be excluded
    assert all(c.section_role != SectionRole.REFERENCES for c in claims)
    assert all("interest rates predict inflation" not in c.quote for c in claims)


def test_single_author_and_cue_families():
    clf = ClaimClassifier()

    c_acc, _ = clf.classify("I show that seasonal shipping indicators achieve lower RMSE across regional ports.")
    assert ClaimType.FORECAST_ACCURACY in c_acc

    c_mag, _ = clf.classify("The estimated pass-through ranges from 4.2 to 7.8 percent across manufacturing sectors.", SectionRole.RESULTS)
    assert ClaimType.MAGNITUDE in c_mag

    c_sig, _ = clf.classify("The benchmark equality test is rejected at the 5% significance level (p < 0.01).")
    assert ClaimType.SIGNIFICANCE in c_sig

    c_rob, _ = clf.classify("A sensitivity analysis confirms that these findings persist across alternative sample windows.")
    assert ClaimType.ROBUSTNESS in c_rob

    c_mech, _ = clf.classify("Variance decomposition attributes the manufacturing slowdown primarily to higher input tariffs.")
    assert ClaimType.MECHANISM in c_mech

    c_prop, _ = clf.classify("My main contribution is that I propose a sparse regional factor estimator.")
    assert ClaimType.PROPOSAL in c_prop

    c_neg, _ = clf.classify("Across all tested subperiods, the static autoregressive rule fails to outperform a driftless walk.")
    assert ClaimType.NEGATIVE_RESULT in c_neg

    c_econ, _ = clf.classify("The improved forecasts translate into economic gains with a higher Sharpe ratio.")
    assert ClaimType.ECONOMIC_VALUE in c_econ


def test_significance_keyword_collision_rejected(synthetic_paper_pdf: Path):
    clf = ClaimClassifier()
    types, _ = clf.classify("Measurement noise creates a significant challenge for standard linear panel specifications.")
    assert types == []

    # Genuine statistical significance with context passes
    ok_types, _ = clf.classify("There is a statistically significant difference between the models (p < 0.01).")
    assert ClaimType.SIGNIFICANCE in ok_types

    # Verify synthetic PDF never emits the F5 collision sentence
    _, claims = _extract_synthetic(synthetic_paper_pdf)
    assert all("significant challenge" not in c.quote for c in claims)


def test_literature_vs_own_attribution(synthetic_paper_pdf: Path):
    attr = AttributionClassifier()
    assert attr.classify("Smith et al. (2020) show that trade shocks explain 12 percent of export variance.") == Attribution.LITERATURE
    assert attr.classify("They find that regional tariff reductions boost bilateral trade by 18%.") == Attribution.LITERATURE
    assert attr.classify("I show that factor models substantially improve out-of-sample forecast accuracy.") == Attribution.OWN
    assert attr.classify("Our proposed algorithm outperforms the random-walk benchmark suggested in Doe and Roe (2023).") == Attribution.COMPARISON

    _, claims = _extract_synthetic(synthetic_paper_pdf)
    smith = next(c for c in claims if "Smith et al. (2020)" in c.quote)
    assert smith.attribution == Attribution.LITERATURE
    own_p4 = next(c for c in claims if "superior directional accuracy" in c.quote)
    assert own_p4.attribution == Attribution.OWN
    assert own_p4.page == 4


def test_near_duplicate_clustering(synthetic_paper_pdf: Path):
    _, claims = _extract_synthetic(synthetic_paper_pdf)
    matches = [c for c in claims if "substantially improve out-of-sample forecast accuracy" in c.quote]
    assert len(matches) == 2
    canonical = [c for c in matches if c.duplicate_of is None]
    duplicates = [c for c in matches if c.duplicate_of is not None]
    assert len(canonical) == 1
    assert len(duplicates) == 1
    assert canonical[0].section_role == SectionRole.ABSTRACT
    assert duplicates[0].duplicate_of == canonical[0].claim_id
    assert any(ref.page == 6 and ref.section == "4 Conclusion" for ref in canonical[0].also_seen_on)


def test_refiner_hook_called(synthetic_paper_pdf: Path):
    class _TaggingRefiner(ClaimRefiner):
        def refine(self, claims: list[Claim], document: Document) -> list[Claim]:
            for c in claims:
                c.matched_cues.append("refined")
            return claims

    doc, claims = _extract_synthetic(synthetic_paper_pdf, refiner=_TaggingRefiner())
    assert claims
    assert all("refined" in c.matched_cues for c in claims)
    assert NullClaimRefiner().refine(claims, doc) is claims
    assert ClaimDeduplicator().deduplicate([]) == []


def test_macro_effects_roadmap_filter_and_coordinated_literature():
    clf = ClaimClassifier()
    attr = AttributionClassifier()

    # Macro effect sentences should classify as mechanism, not only proposal
    macro_types, _ = clf.classify("We find that positive innovations to sentiment increase consumption, output, and interest rates while reducing inflation.")
    assert ClaimType.MECHANISM in macro_types
    assert ClaimType.PROPOSAL not in macro_types

    # Roadmap/overview sentences must be suppressed
    assert clf.classify("In section 2 we provide an overview of the general methodologies for panel estimation.")[0] == []
    assert clf.classify("Before discussing our specific application, here we provide an overview of standard approaches.")[0] == []
    assert clf.classify("Section 4 shows results for bond markets and Section 5 concludes.")[0] == []

    # Coordinated author-year citation subjects must be attributed to literature
    lit_sent = "Baker and Lane (2022) and Carter et al. (2023) estimated positive short-run effects of rate surprises on asset prices, while we show that longer maturities respond negatively."
    assert attr.classify(lit_sent) == Attribution.LITERATURE
    assert attr.classify("Some early studies of inflation anchoring estimated negative responses of long-horizon yields.") == Attribution.LITERATURE


def test_wider_non_forecasting_claim_cues():
    clf = ClaimClassifier()

    # General contribution verbs
    t_prop, _ = clf.classify("We document the design and benchmark the workflow across five empirical specifications.")
    assert ClaimType.PROPOSAL in t_prop

    # Interval / band statements
    t_band_zero, _ = clf.classify("Across both sample windows, the 90% credible band on output includes zero throughout.")
    assert ClaimType.NEGATIVE_RESULT in t_band_zero

    t_band_excl, _ = clf.classify("The 95% confidence interval on core inflation excludes zero after two quarters.")
    assert ClaimType.SIGNIFICANCE in t_band_excl

    # Test statistics
    t_fstat, _ = clf.classify("The external instrument yields a first-stage F statistic of 24.2 across all horizons.")
    assert ClaimType.SIGNIFICANCE in t_fstat

    # Replication outcomes
    t_rep1, _ = clf.classify("On the archived dataset, reproduction is exact across all reported horizons.")
    assert ClaimType.ROBUSTNESS in t_rep1

    t_rep2, _ = clf.classify("The recomputed impulse responses match the original estimates to numerical precision.")
    assert ClaimType.ROBUSTNESS in t_rep2

    # Macro outcome nouns seeded from macro_outcomes dictionary
    t_macro, _ = clf.classify("Unanticipated fiscal expansions raise long-term inflation expectations and increase sovereign debt.")
    assert ClaimType.MECHANISM in t_macro

    # Percentage-point notation with periods
    t_pp, _ = clf.classify("Long-run expectations increase by 0.3 p.p. within two years.", SectionRole.RESULTS)
    assert ClaimType.MAGNITUDE in t_pp
