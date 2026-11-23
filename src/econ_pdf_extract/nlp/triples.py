from __future__ import annotations

import logging
import re
from typing import Any

from econ_pdf_extract.claims.extractor import ClaimExtractor
from econ_pdf_extract.core.config import ConfigLoader
from econ_pdf_extract.core.models import CausalTriple, Document, SectionRole, Sentence
from econ_pdf_extract.nlp.loader import SpacyModelLoader

logger = logging.getLogger(__name__)

_UNSPECIFIED = "(unspecified)"
_UNIT_MODIFIERS = frozenset({"%", "percent", "percentage", "point", "points", "pp", "p.p.", "bp", "bps"})
_CAUSE_PREPS = frozenset({"from", "after", "following", "under", "through", "by", "during"})


class CausalTripleExtractor:
    """Extracts (cause, direction, outcome) triples across eligible sentences using spaCy dependencies."""

    def __init__(self, model_name: str | None = None, nlp: Any = None, extraction_cfg: dict[str, Any] | None = None, nlp_cfg: dict[str, Any] | None = None, include_appendix: bool = False):
        loader = ConfigLoader()
        root_cfg = extraction_cfg if extraction_cfg is not None else loader.load("extraction.yaml")
        claims_cfg = root_cfg.get("claims", {})
        model_cfg = root_cfg.get("nlp", {})
        pat_cfg = nlp_cfg if nlp_cfg is not None else loader.load("nlp_patterns.yaml")

        raw_roles = claims_cfg.get("eligible_roles", ["abstract", "introduction", "results", "robustness", "conclusion"])
        self._eligible_roles = {SectionRole(r) for r in raw_roles}
        if include_appendix or bool(claims_cfg.get("include_appendix_by_default", False)):
            self._eligible_roles.add(SectionRole.APPENDIX)

        self._dir_map: dict[str, str] = {}
        for direction, lemmas in pat_cfg.get("direction_lemmas", {}).items():
            for lemma in lemmas:
                self._dir_map[str(lemma).lower()] = str(direction).lower()
        self._intransitive = frozenset(str(v).lower() for v in pat_cfg.get("intransitive_direction_lemmas", []))

        self._loader = SpacyModelLoader(model_name=model_name, config=model_cfg)
        self._nlp = nlp

    def get_nlp(self) -> Any:
        if self._nlp is None:
            self._nlp = self._loader.load()
        return self._nlp

    def eligible_sentences(self, doc: Document) -> list[Sentence]:
        dup_section_ids = {s.section_id for s in doc.sections if s.is_duplicate_front_matter}
        body_other_ids = ClaimExtractor._body_other_section_ids(doc)
        selected: list[Sentence] = []
        seen_texts: set[str] = set()
        for sent in doc.sentences:
            if sent.section_id in dup_section_ids:
                continue
            in_body_other = sent.section_role == SectionRole.OTHER and sent.section_id in body_other_ids
            if sent.section_role not in self._eligible_roles and not in_body_other:
                continue
            norm = re.sub(r"\s+", " ", sent.text).strip()
            if not norm or norm in seen_texts:
                continue
            seen_texts.add(norm)
            selected.append(sent)
        return selected

    def extract(self, doc: Document) -> list[CausalTriple]:
        sentences = self.eligible_sentences(doc)
        if not sentences:
            return []
        nlp = self.get_nlp()
        parsed_docs = nlp.pipe([s.text for s in sentences])
        triples: list[CausalTriple] = []
        seq = 0
        for sent, parsed in zip(sentences, parsed_docs, strict=True):
            for cause, direction, outcome, verb in self.extract_from_doc(parsed):
                seq += 1
                triples.append(
                    CausalTriple(
                        triple_id=f"TRP-{seq:03d}",
                        paper_id=doc.paper_id,
                        cause=cause,
                        direction=direction,
                        outcome=outcome,
                        verb=verb,
                        sentence=sent.text,
                        page=sent.page,
                        page_end=sent.page_end,
                        section=sent.section_heading,
                        section_role=sent.section_role,
                        bbox=sent.bbox,
                    )
                )
        logger.info("Extracted %d causal triples from %d sentences for %s", len(triples), len(sentences), doc.paper_id)
        return triples

    def extract_from_doc(self, parsed_doc: Any) -> list[tuple[str, str, str, str]]:
        root = next((t for t in parsed_doc if t.dep_ == "ROOT"), None)
        out: list[tuple[str, str, str, str]] = []
        seen: set[tuple[str, str, str]] = set()
        for tok in parsed_doc:
            lemma = tok.lemma_.lower()
            direction = self._dir_map.get(lemma)
            if direction is None:
                continue
            if tok.pos_ in {"VERB", "AUX"}:
                cause, outcome = self._verb_arguments(tok, parsed_doc, root, lemma)
            elif tok.pos_ == "NOUN":
                cause, outcome = self._noun_arguments(tok)
            else:
                continue
            if cause == _UNSPECIFIED and outcome == _UNSPECIFIED:
                continue
            dedup_key = (cause.lower(), direction, outcome.lower())
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            out.append((cause, direction, outcome, lemma))
        return out

    def _verb_arguments(self, tok: Any, parsed_doc: Any, root: Any, lemma: str) -> tuple[str, str]:
        subj = next((s for s in parsed_doc if s.dep_ in {"nsubj", "nsubjpass"} and s.head.i == tok.i), None)
        if subj is None and root is not None and tok.i == root.i:
            subj = next((s for s in parsed_doc if s.dep_ in {"nsubj", "nsubjpass"}), None)
        obj = next((o for o in parsed_doc if o.dep_ in {"dobj", "obj", "attr"} and o.head.i == tok.i), None)

        if subj is not None and subj.dep_ == "nsubjpass":
            outcome = self._chunk_of(subj)
            by_obj = self._prep_object(tok, {"by"})
            cause = self._chunk_of(by_obj) if by_obj is not None else _UNSPECIFIED
            return cause, outcome

        if obj is None and lemma in self._intransitive:
            outcome = self._chunk_of(subj) if subj is not None else _UNSPECIFIED
            cause_obj = self._prep_object(tok, _CAUSE_PREPS)
            cause = self._chunk_of(cause_obj) if cause_obj is not None else _UNSPECIFIED
            return cause, outcome

        if obj is None:
            obj = self._prep_object(tok, None, exclude={"by"})
        cause = self._chunk_of(subj) if subj is not None else _UNSPECIFIED
        outcome = self._chunk_of(obj) if obj is not None else _UNSPECIFIED
        return cause, outcome

    def _noun_arguments(self, tok: Any) -> tuple[str, str]:
        out_obj = self._prep_object(tok, {"in", "of"})
        outcome = self._chunk_of(out_obj) if out_obj is not None else _UNSPECIFIED
        cause_tok = next(
            (
                c
                for c in tok.children
                if c.dep_ in {"nmod", "poss", "compound", "npadvmod"} and c.lower_ not in _UNIT_MODIFIERS and not c.like_num
            ),
            None,
        )
        cause = self._chunk_of(cause_tok) if cause_tok is not None else _UNSPECIFIED
        return cause, outcome

    @staticmethod
    def _prep_object(tok: Any, allowed: set[str] | frozenset[str] | None, exclude: set[str] | None = None) -> Any:
        for child in tok.children:
            if child.dep_ not in {"prep", "agent"}:
                continue
            prep_low = child.lower_
            if allowed is not None and prep_low not in allowed:
                continue
            if exclude is not None and prep_low in exclude:
                continue
            pobj = next((o for o in child.children if o.dep_ == "pobj"), None)
            if pobj is not None:
                return pobj
        return None

    @staticmethod
    def _chunk_of(tok: Any) -> str:
        if tok is None:
            return _UNSPECIFIED
        for chunk in tok.doc.noun_chunks:
            if chunk.start <= tok.i < chunk.end:
                return chunk.text.strip()
        return tok.text.strip()
