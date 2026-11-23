from __future__ import annotations

import re
from typing import Any

from econ_pdf_extract.core.config import ConfigLoader
from econ_pdf_extract.core.models import Attribution

_DIRECT_RESULTS_RE = re.compile(
    r"\b(?:Table\s+\d+|Figure\s+\d+|For\s+(?:all|none|every|the)|At\s+(?:the|every)|"
    r"The\s+(?:R2|R\^2|RMSE|CRPS|MSE|TUs?|null\s+hypothesis|p-value|results?|findings?|factors?|"
    r"extended\s+model|proposed|suggested|baseline|algorithm|first\s+\w+\s+factor|multi-factor|"
    r"historical\s+shock|robustness\s+check|relative\s+reduction|average\s+accuracy|forecast\s+errors?|"
    r"statistical\s+evidence|predictive\s+power)|Overall,|In\s+particular,|In\s+contrast,|However,|"
    r"Additionally,|Further\s+analysis|It\s+produces|Isotonic|Under\s+the\s+assumed|First,|Second,|"
    r"Both\s+in\s+terms|While\s+heterogeneous|When\s+business|Using\s+out-of-sample|Using\s+Equation)\b",
    re.IGNORECASE,
)
_FIRST_PERSON_CLAIM_RE = re.compile(
    r"\b(?:we|I)\s+(?:find|show|demonstrate|propose|provide|introduce|develop|document|confirm|conclude|report)\b",
    re.IGNORECASE,
)


class AttributionClassifier:
    """Classifies each extracted claim as own, literature, comparison, or unclear."""

    def __init__(self, config: dict[str, Any] | None = None):
        cfg = config if config is not None else ConfigLoader().load("claim_patterns.yaml")
        attr_cfg = cfg.get("attribution_patterns", {})
        self._citation_re = re.compile(
            attr_cfg.get(
                "citation",
                r"[A-Z][A-Za-z\-''’]+(?:\s+(?:and|&)\s+[A-Z][A-Za-z\-''’]+|\s+et\s+al\.?)?\s*\(\s*(?:19|20)\d{2}[a-z]?\s*\)",
            )
        )
        self._own_res = [re.compile(rx, re.IGNORECASE) for rx in attr_cfg.get("own_work", [])]
        self._comp_res = [re.compile(rx, re.IGNORECASE) for rx in attr_cfg.get("comparison", [])]
        self._lit_res = [re.compile(rx) for rx in attr_cfg.get("literature_subject", [])]

    def classify(self, text: str) -> Attribution:
        stripped = text.strip()
        has_citation = bool(self._citation_re.search(stripped))
        has_own = any(rx.search(stripped) for rx in self._own_res)
        has_comp = any(rx.search(stripped) for rx in self._comp_res)
        has_lit_subject = any(rx.search(stripped) for rx in self._lit_res)
        has_first_person = bool(_FIRST_PERSON_CLAIM_RE.search(stripped))

        # 1. Author-year or earlier-studies subject at sentence start -> LITERATURE
        #    (unless the sentence is explicitly an own-confirmation comparison like "They find - and we confirm this -")
        if has_lit_subject:
            if has_comp and re.search(r"\b(?:we|I)\s+confirm\b", stripped, re.IGNORECASE):
                return Attribution.COMPARISON
            return Attribution.LITERATURE

        # 2. Comparison against benchmark or cited study
        if has_citation and (has_comp or (has_own and not has_first_person)):
            return Attribution.COMPARISON

        # 3. Own work or direct results reporting
        if has_own or _DIRECT_RESULTS_RE.search(stripped):
            return Attribution.OWN

        if has_citation:
            return Attribution.LITERATURE

        return Attribution.UNCLEAR
