from __future__ import annotations

import re
from typing import Any

from econ_pdf_extract.core.config import ConfigLoader
from econ_pdf_extract.core.models import ClaimType, SectionRole
from econ_pdf_extract.core.paths import load_dictionary

_TYPE_ORDER = (
    ClaimType.FORECAST_ACCURACY,
    ClaimType.SIGNIFICANCE,
    ClaimType.ECONOMIC_VALUE,
    ClaimType.NEGATIVE_RESULT,
    ClaimType.ROBUSTNESS,
    ClaimType.MECHANISM,
    ClaimType.MAGNITUDE,
    ClaimType.PROPOSAL,
)


class ClaimClassifier:
    """YAML-driven 8-category empirical claim classifier with significance collision guards."""

    def __init__(self, config: dict[str, Any] | None = None):
        cfg = config if config is not None else ConfigLoader().load("claim_patterns.yaml")
        collision_nouns = load_dictionary("abbreviations").SIGNIFICANCE_COLLISION_NOUNS
        outcome_nouns = load_dictionary("macro_outcomes").MACRO_OUTCOME_NOUNS

        outcome_alt = "(?:" + "|".join(
            re.escape(w).replace(r"\ ", r"\s+")
            for w in sorted(outcome_nouns, key=len, reverse=True)
        ) + ")"
        raw_types = cfg.get("claim_types", {})
        self._patterns: dict[ClaimType, list[re.Pattern[str]]] = {
            ctype: [
                re.compile(rx.replace("{macro_outcomes}", outcome_alt), re.IGNORECASE)
                for rx in raw_types.get(ctype.value, [])
            ]
            for ctype in _TYPE_ORDER
        }
        self._general_finding_res = [
            re.compile(rx, re.IGNORECASE) for rx in cfg.get("general_finding_patterns", [])
        ]
        self._sig_context_res = [
            re.compile(rx, re.IGNORECASE) for rx in cfg.get("significance_context_patterns", [])
        ]
        self._exclude_res = [
            re.compile(rx, re.IGNORECASE) for rx in cfg.get("exclude_patterns", [])
        ]

        nouns = "|".join(re.escape(w) for w in sorted(collision_nouns))
        self._sig_collision_re = re.compile(rf"\bsignificant\s+(?:{nouns})\b", re.IGNORECASE)

    def classify(self, text: str, section_role: SectionRole = SectionRole.OTHER) -> tuple[list[ClaimType], list[str]]:
        if any(rx.search(text) for rx in self._exclude_res):
            return [], []

        matched_types: list[ClaimType] = []
        matched_cues: list[str] = []

        for ctype in _TYPE_ORDER:
            hits: list[str] = []
            for rx in self._patterns.get(ctype, []):
                m = rx.search(text)
                if m:
                    hits.append(m.group(0).strip())
            if not hits:
                continue
            if ctype == ClaimType.SIGNIFICANCE and self._is_significance_collision(text):
                continue
            matched_types.append(ctype)
            matched_cues.extend(hits[:2])

        if not matched_types:
            for rx in self._general_finding_res:
                m = rx.search(text)
                if m:
                    matched_types.append(ClaimType.GENERAL)
                    matched_cues.append(m.group(0).strip())
                    break

        # Guard: bare magnitude numbers without an empirical context in non-results sections
        if matched_types == [ClaimType.MAGNITUDE] and section_role in {SectionRole.DATA, SectionRole.METHODOLOGY}:
            return [], []

        return matched_types, matched_cues

    def is_claim(self, text: str, section_role: SectionRole = SectionRole.OTHER) -> bool:
        types, _ = self.classify(text, section_role=section_role)
        return bool(types)

    def _is_significance_collision(self, text: str) -> bool:
        if not self._sig_collision_re.search(text):
            return False
        return not any(rx.search(text) for rx in self._sig_context_res)
