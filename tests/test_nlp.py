from __future__ import annotations

import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from econ_pdf_extract import (
    Attribution,
    CausalTriple,
    CausalTripleExtractor,
    Claim,
    ClaimType,
    ConfigLoader,
    Document,
    ExtractionPipeline,
    SectionRole,
    SpacyClaimFilter,
    SpacyModelLoader,
    SpacyUnavailableError,
)
from econ_pdf_extract.nlp.loader import DEFAULT_SPACY_MODEL


def test_core_nlp_config_default():
    cfg = ConfigLoader().load("extraction.yaml")
    assert cfg["nlp"]["spacy_model"] == DEFAULT_SPACY_MODEL
    assert SpacyModelLoader().model_name == "en_core_web_sm"


def test_loader_missing_spacy_raises_actionable_error(monkeypatch: pytest.MonkeyPatch):
    SpacyModelLoader.clear_cache()

    def _raise_import(name: str):
        raise ImportError(f"No module named {name!r}")

    monkeypatch.setattr(importlib, "import_module", _raise_import)
    loader = SpacyModelLoader(model_name="en_core_web_sm")
    assert loader.is_spacy_available() is False
    assert loader.is_model_available() is False
    with pytest.raises(SpacyUnavailableError) as exc_info:
        loader.load()
    msg = str(exc_info.value)
    assert "nlp" in msg
    assert "spacy" in msg.lower()


def test_loader_missing_model_raises_install_hint(monkeypatch: pytest.MonkeyPatch):
    SpacyModelLoader.clear_cache()

    def _fake_load(name: str, disable: list[str] | None = None):
        raise OSError(f"[E050] Can't find model '{name}'")

    fake_spacy = SimpleNamespace(load=_fake_load, util=SimpleNamespace(is_package=lambda name: False))
    monkeypatch.setattr(importlib, "import_module", lambda name: fake_spacy)

    loader = SpacyModelLoader(model_name="en_core_web_sm")
    assert loader.is_spacy_available() is True
    assert loader.is_model_available() is False
    with pytest.raises(SpacyUnavailableError) as exc_info:
        loader.load()
    msg = str(exc_info.value)
    assert "python -m spacy download en_core_web_sm" in msg


def test_loader_loads_installed_sm_model():
    loader = SpacyModelLoader(model_name="en_core_web_sm")
    if not loader.is_model_available():
        pytest.skip("spaCy or en_core_web_sm is not installed")
    nlp = loader.load()
    doc = nlp("Monetary policy tightening reduces output.")
    assert [t.text for t in doc[:2]] == ["Monetary", "policy"]
    assert loader.load() is nlp


def _make_claim(claim_id: str, quote: str, duplicate_of: str | None = None) -> Claim:
    return Claim(
        claim_id=claim_id,
        paper_id="synthetic",
        claim_types=[ClaimType.GENERAL],
        attribution=Attribution.OWN,
        page=1,
        page_end=1,
        section="3 Results",
        section_role=SectionRole.RESULTS,
        bbox=(0.0, 0.0, 100.0, 12.0),
        quote=quote,
        duplicate_of=duplicate_of,
    )


def test_spacy_claim_filter_parse_fixes_on_mock_tokens():
    # Synthetic token graph testing all 3 parse fixes independent of spaCy installation.
    def _tok(i: int, text: str, lemma: str, pos: str, tag: str, dep: str, children: list[SimpleNamespace] | None = None) -> SimpleNamespace:
        return SimpleNamespace(i=i, text=text, lemma_=lemma, pos_=pos, tag_=tag, dep_=dep, children=children or [])

    filt = SpacyClaimFilter()

    # Fix 1: VB under auxiliary/negation ("do not predict")
    aux_do = _tok(1, "do", "do", "AUX", "VBP", "aux")
    neg_not = _tok(2, "not", "not", "PART", "RB", "neg")
    vb_predict = _tok(3, "predict", "predict", "VERB", "VB", "ROOT", [aux_do, neg_not])
    assert filt.should_keep("Spreads do not predict output.", [aux_do, neg_not, vb_predict]) is True

    # Fix 2: VBN with finite auxiliary/passive ("is rejected")
    aux_is = _tok(1, "is", "be", "AUX", "VBZ", "auxpass")
    vbn_rej = _tok(2, "rejected", "reject", "VERB", "VBN", "ROOT", [aux_is])
    assert filt.should_keep("The null hypothesis is rejected at 5%.", [aux_is, vbn_rej]) is True

    # Fix 2 does NOT let non-claim passive verbs through ("is bolded")
    vbn_bold = _tok(2, "bolded", "bold", "VERB", "VBN", "ROOT", [aux_is])
    assert filt.should_keep("The smallest number is bolded in Table 3.", [aux_is, vbn_bold]) is False

    # Fix 3: ROOT is a NOUN (fronted PP parse) -> fall back to nearest finite verb ("has")
    noun_root = _tok(3, "rate", "rate", "NOUN", "NN", "ROOT")
    fin_has = _tok(6, "has", "have", "VERB", "VBZ", "relcl")
    assert filt.should_keep("In the second sample the larger specification has smaller errors.", [noun_root, fin_has]) is True

    # Equation fragment with NOUN root and no finite verb is still dropped
    eq_root = _tok(0, "MSE", "mse", "NOUN", "NN", "ROOT")
    eq_part = _tok(3, "summed", "sum", "VERB", "VBN", "acl")
    assert filt.should_keep("MSE = 1 summed over H + M.", [eq_root, eq_part]) is False

    # Duplicate promotion when canonical parent is filtered out
    doc = Document(paper_id="synthetic", source_path=pytest.importorskip("pathlib").Path("x.pdf"), page_count=1, body_font_size=10.0)
    fake_nlp = SimpleNamespace(
        pipe=lambda texts: [
            [eq_root, eq_part],
            [aux_is, vbn_rej],
            [aux_do, neg_not, vb_predict],
        ]
    )
    filt_mock = SpacyClaimFilter(nlp=fake_nlp)
    claims = [
        _make_claim("CLM-001", "MSE = 1 summed over H + M."),
        _make_claim("CLM-002", "The null hypothesis is rejected at 5%.", duplicate_of="CLM-001"),
        _make_claim("CLM-003", "Spreads do not predict output.", duplicate_of="CLM-001"),
    ]
    out = filt_mock.refine(claims, doc)
    assert [c.claim_id for c in out] == ["CLM-002", "CLM-003"]
    assert out[0].duplicate_of is None
    assert out[1].duplicate_of == "CLM-002"


def test_spacy_claim_filter_real_model_and_pipeline(synthetic_paper_pdf):
    loader = SpacyModelLoader(model_name="en_core_web_sm")
    if not loader.is_model_available():
        pytest.skip("spaCy or en_core_web_sm is not installed")

    nlp = loader.load()
    filt = SpacyClaimFilter(nlp=nlp)

    # Real spaCy parses of all 3 fix categories + junk drops
    assert filt.should_keep("Lagged spreads do not predict quarterly output growth.", nlp("Lagged spreads do not predict quarterly output growth.")) is True
    assert filt.should_keep("The null hypothesis of equal accuracy is rejected at the 5% level.", nlp("The null hypothesis of equal accuracy is rejected at the 5% level.")) is True
    assert filt.should_keep("In the second sample the larger specification has smaller errors than the simple one.", nlp("In the second sample the larger specification has smaller errors than the simple one.")) is True
    assert filt.should_keep("Section 3 describes the dataset and presents summary statistics.", nlp("Section 3 describes the dataset and presents summary statistics.")) is False
    assert filt.should_keep("The smallest number is bolded and underlined in Table 3.", nlp("The smallest number is bolded and underlined in Table 3.")) is False
    assert filt.should_keep("The test statistic addresses sampling noise through a variance estimate.", nlp("The test statistic addresses sampling noise through a variance estimate.")) is False

    # End-to-end via ClaimRefiner hook on synthetic PDF
    res = ExtractionPipeline(synthetic_paper_pdf, refiner=filt).run()
    assert res.claims
    assert any("4.82%" in c.quote for c in res.claims)


def test_causal_triple_extractor_and_no_claim_type_rewrite(synthetic_paper_pdf):
    loader = SpacyModelLoader(model_name="en_core_web_sm")
    if not loader.is_model_available():
        pytest.skip("spaCy or en_core_web_sm is not installed")

    nlp = loader.load()
    extractor = CausalTripleExtractor(nlp=nlp)

    # Transitive active
    t_active = extractor.extract_from_doc(nlp("Monetary tightening reduces industrial output."))
    assert any(d == "decrease" and "tightening" in c.lower() and "output" in o.lower() for c, d, o, _ in t_active)

    # Passive
    t_passive = extractor.extract_from_doc(nlp("Inflation expectations are raised by fiscal surprises."))
    assert any(d == "increase" and "surprises" in c.lower() and "expectations" in o.lower() for c, d, o, _ in t_passive)

    # Intransitive
    t_intrans = extractor.extract_from_doc(nlp("Commodity prices fall after policy hikes."))
    assert any(d == "decrease" and "prices" in o.lower() for _, d, o, _ in t_intrans)

    # Nominalized direction noun
    t_nom = extractor.extract_from_doc(nlp("A sharp increase in unemployment follows the recession."))
    assert any(d == "increase" and "unemployment" in o.lower() for _, d, o, _ in t_nom)

    # End-to-end pipeline: emits causal_triples and NEVER rewrites claim_types
    example_pdf = Path(__file__).resolve().parents[1] / "examples" / "example_paper.pdf"
    base_res = ExtractionPipeline(example_pdf).run()
    tri_res = ExtractionPipeline(example_pdf, extract_causal_triples=True).run()
    assert tri_res.causal_triples
    assert tri_res.diagnostics["causal_triples"] == len(tri_res.causal_triples)
    assert all(isinstance(t, CausalTriple) and t.page >= 1 and t.section and t.sentence for t in tri_res.causal_triples)
    assert [(c.claim_id, c.claim_types) for c in tri_res.claims] == [(c.claim_id, c.claim_types) for c in base_res.claims]

    syn_base = ExtractionPipeline(synthetic_paper_pdf).run()
    syn_tri = ExtractionPipeline(synthetic_paper_pdf, extract_causal_triples=True).run()
    assert [(c.claim_id, c.claim_types) for c in syn_tri.claims] == [(c.claim_id, c.claim_types) for c in syn_base.claims]
