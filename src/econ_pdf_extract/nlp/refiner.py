from __future__ import annotations

import dataclasses
import logging
import re
from typing import Any

from econ_pdf_extract.claims.refiner import ClaimRefiner
from econ_pdf_extract.core.config import ConfigLoader
from econ_pdf_extract.core.models import Claim, Document
from econ_pdf_extract.nlp.loader import SpacyModelLoader

logger = logging.getLogger(__name__)

_FINITE_TAGS = frozenset({"VBZ", "VBP", "VBD", "MD"})
_AUX_DEPS = frozenset({"aux", "auxpass"})
_SECTION_RE = re.compile(r"\bsection\b", re.IGNORECASE)


class SpacyClaimFilter(ClaimRefiner):
    """Dependency-based claim filter refiner with parse fixes for auxiliaries, passives, and fronted PPs."""

    def __init__(self, model_name: str | None = None, nlp: Any = None, config: dict[str, Any] | None = None, extraction_cfg: dict[str, Any] | None = None):
        cfg = config if config is not None else ConfigLoader().load("nlp_patterns.yaml")
        self._claim_verbs = frozenset(str(v).lower() for v in cfg.get("claim_verbs", []))
        self._roadmap_verbs = frozenset(str(v).lower() for v in cfg.get("roadmap_verbs", []))
        self._roadmap_res = [re.compile(rx, re.IGNORECASE) for rx in cfg.get("roadmap_patterns", [])]
        raw_dir = cfg.get("direction_lemmas", {})
        self._direction_lemmas = frozenset(
            str(v).lower()
            for bucket in raw_dir.values()
            for v in bucket
        )
        self._loader = SpacyModelLoader(model_name=model_name, config=extraction_cfg)
        self._nlp = nlp

    @property
    def model_name(self) -> str:
        return self._loader.model_name

    def get_nlp(self) -> Any:
        if self._nlp is None:
            self._nlp = self._loader.load()
        return self._nlp

    def refine(self, claims: list[Claim], document: Document) -> list[Claim]:
        if not claims:
            return []
        nlp = self.get_nlp()
        docs = nlp.pipe([c.quote for c in claims])
        kept: list[Claim] = []
        for claim, parsed in zip(claims, docs, strict=True):
            if self.should_keep(claim.quote, parsed):
                kept.append(claim)
        logger.info("SpacyClaimFilter kept %d/%d claims for %s", len(kept), len(claims), document.paper_id)
        return self._reconcile_duplicates(kept)

    def should_keep(self, quote: str, parsed_doc: Any) -> bool:
        verb = self._resolve_main_verb(parsed_doc)
        if verb is None:
            return False
        if any(rx.search(quote) for rx in self._roadmap_res):
            return False
        if _SECTION_RE.search(quote) and verb.lemma_.lower() in self._roadmap_verbs:
            return False
        if verb.lemma_.lower() in self._claim_verbs:
            return True
        if any(
            c.dep_ in {"conj", "ccomp", "parataxis"} and self._is_finite_verb(c) and c.lemma_.lower() in self._claim_verbs
            for c in verb.children
        ):
            return True
        return any(tok.lemma_.lower() in self._direction_lemmas for tok in parsed_doc)

    @classmethod
    def _is_finite_verb(cls, tok: Any) -> bool:
        if tok.pos_ not in {"VERB", "AUX"}:
            return False
        if tok.tag_ in _FINITE_TAGS:
            return True
        # Fix 1: VB under auxiliary / negation ("do not predict", "can improve")
        if tok.tag_ == "VB":
            return any(
                c.dep_ in _AUX_DEPS and (c.tag_ in _FINITE_TAGS or c.pos_ == "AUX")
                for c in tok.children
            )
        # Fix 2: VBN with finite auxiliary / passive ("is rejected", "has shown", "has been preferred")
        if tok.tag_ == "VBN":
            return any(
                c.dep_ in _AUX_DEPS and c.tag_ in _FINITE_TAGS
                for c in tok.children
            )
        return False

    @classmethod
    def _resolve_main_verb(cls, parsed_doc: Any) -> Any:
        root = next((t for t in parsed_doc if t.dep_ == "ROOT"), None)
        if root is None:
            return None
        if cls._is_finite_verb(root):
            return root
        # Fix 3: fall back to nearest finite verb when ROOT is a noun (fronted PP parse)
        # or a non-finite modifier attached above a finite main clause verb.
        if root.pos_ in {"NOUN", "PROPN"} or root.tag_ == "VBN":
            finite_verbs = [t for t in parsed_doc if cls._is_finite_verb(t)]
            if finite_verbs:
                return min(finite_verbs, key=lambda t: abs(t.i - root.i))
        return None

    @staticmethod
    def _reconcile_duplicates(claims: list[Claim]) -> list[Claim]:
        kept_ids = {c.claim_id for c in claims}
        promoted: dict[str, str] = {}
        reconciled: list[Claim] = []
        for claim in claims:
            if claim.duplicate_of is None or claim.duplicate_of in kept_ids:
                reconciled.append(claim)
                continue
            orig_parent = claim.duplicate_of
            if orig_parent not in promoted:
                promoted[orig_parent] = claim.claim_id
                reconciled.append(dataclasses.replace(claim, duplicate_of=None))
            else:
                reconciled.append(dataclasses.replace(claim, duplicate_of=promoted[orig_parent]))
        return reconciled
