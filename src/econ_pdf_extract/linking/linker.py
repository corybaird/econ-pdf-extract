from __future__ import annotations

import re
from typing import Any

from econ_pdf_extract.core.config import ConfigLoader
from econ_pdf_extract.core.models import (
    Claim,
    CrossRefEdge,
    Document,
    MathKind,
    MathObject,
    SymbolDef,
)
from econ_pdf_extract.core.paths import load_dictionary
from econ_pdf_extract.math_extract.symbols import normalize_symbol

_ANAPHORIC_START_RE = re.compile(r"^(?:This|These|It|Such)\b")


class CrossReferenceLinker:
    """Builds bidirectional links between Claims, MathObjects, and SymbolDefs."""

    def __init__(self, math_cfg: dict[str, Any] | None = None):
        cfg = math_cfg if math_cfg is not None else ConfigLoader().load("math_patterns.yaml")
        self._ref_res = [re.compile(rx, re.IGNORECASE) for rx in cfg.get("cross_ref_patterns", [])]
        raw_metrics = cfg.get("named_metrics", {})
        self._metric_res: dict[str, list[re.Pattern[str]]] = {
            metric: [re.compile(rx, re.IGNORECASE) for rx in regexes]
            for metric, regexes in raw_metrics.items()
        }
        self._greek_map = load_dictionary("greek_to_latex").GREEK_TO_LATEX

    def link(self, claims: list[Claim], math_objects: list[MathObject], symbols: list[SymbolDef], doc: Document | None = None) -> list[CrossRefEdge]:
        by_tag = {m.tag: m for m in math_objects if m.tag is not None}
        by_id = {m.math_id: m for m in math_objects}
        metric_to_eqs = self._index_metric_equations(math_objects)
        primary_symbol_defs = self._index_primary_symbols(symbols)
        prev_sentence_map = self._build_prev_sentence_map(doc) if doc is not None else {}

        edges: list[CrossRefEdge] = []
        seen_edges: set[tuple[str, str, str, str]] = set()

        for claim in claims:
            scan_text = claim.quote
            if _ANAPHORIC_START_RE.match(claim.quote):
                prev_text = prev_sentence_map.get((claim.page, claim.quote))
                if prev_text:
                    scan_text = f"{prev_text} {claim.quote}"

            # 1. Explicit equation cross-references
            for tag in self._extract_ref_tags(scan_text):
                eq_obj = by_tag.get(tag)
                if eq_obj is None:
                    continue
                self._add_edge(claim, eq_obj, "explicit_ref", tag, edges, seen_edges)

            # 2. Named evaluation-metric linking
            for metric, patterns in self._metric_res.items():
                if metric not in metric_to_eqs:
                    continue
                if any(rx.search(claim.quote) for rx in patterns):
                    for eq_obj in metric_to_eqs[metric]:
                        self._add_edge(claim, eq_obj, "named_metric", metric, edges, seen_edges)
                    if metric not in claim.linked_symbols:
                        claim.linked_symbols.append(metric)

            # 3. Defined-symbol overlap with bare single-letter guard
            claim_math_norms = {normalize_symbol(t, self._greek_map) for t in claim.math_tokens}
            for norm_key, sym_def in primary_symbol_defs.items():
                if not self._is_linkable_symbol(sym_def):
                    continue
                matched = norm_key in claim_math_norms or self._symbol_in_quote(sym_def.symbol, claim.quote)
                if not matched:
                    continue
                if sym_def.symbol not in claim.linked_symbols:
                    claim.linked_symbols.append(sym_def.symbol)
                if sym_def.equation_id and sym_def.equation_id in by_id:
                    self._add_edge(claim, by_id[sym_def.equation_id], "symbol", sym_def.symbol, edges, seen_edges)

        return edges

    def _extract_ref_tags(self, text: str) -> list[str]:
        tags: list[str] = []
        for rx in self._ref_res:
            for m in rx.finditer(text):
                gd = m.groupdict()
                for key in ("tag", "tag1", "tag2"):
                    val = gd.get(key)
                    if val:
                        tag_str = f"({val})"
                        if tag_str not in tags:
                            tags.append(tag_str)
        return tags

    def _index_metric_equations(self, math_objects: list[MathObject]) -> dict[str, list[MathObject]]:
        index: dict[str, list[MathObject]] = {}
        for obj in math_objects:
            if obj.kind != MathKind.EVALUATION_FORMULA:
                continue
            target = f"{obj.raw_text} {obj.context_before}"
            for metric, patterns in self._metric_res.items():
                if any(rx.search(target) for rx in patterns):
                    index.setdefault(metric, []).append(obj)
        return index

    @staticmethod
    def _index_primary_symbols(symbols: list[SymbolDef]) -> dict[str, SymbolDef]:
        primary: dict[str, SymbolDef] = {}
        for sym in symbols:
            if not sym.normalized:
                continue
            if sym.normalized not in primary or primary[sym.normalized].equation_id is None and sym.equation_id is not None:
                primary[sym.normalized] = sym
        return primary

    def _is_linkable_symbol(self, sym_def: SymbolDef) -> bool:
        raw = sym_def.symbol.strip()
        if not raw:
            return False
        # Reject bare single-character ASCII letters (e.g. "a", "i", "n", "t", "x", "y")
        if len(raw) == 1 and raw.isascii() and raw.isalpha():
            return False
        # Accept symbols with subscripts/superscripts/digits/Greek or multi-char uppercase acronyms
        if any(ch in raw for ch in ("_", "^", "\\", "'")) or any(ch.isdigit() for ch in raw):
            return True
        if any(ch in self._greek_map for ch in raw):
            return True
        return bool(raw.isupper() and len(raw) >= 2)

    @staticmethod
    def _symbol_in_quote(symbol: str, quote: str) -> bool:
        escaped = re.escape(symbol)
        if symbol[0].isalnum() and symbol[-1].isalnum():
            return bool(re.search(rf"(?<![A-Za-z0-9_]){escaped}(?![A-Za-z0-9_])", quote))
        return symbol in quote

    @staticmethod
    def _build_prev_sentence_map(doc: Document) -> dict[tuple[int, str], str]:
        mapping: dict[tuple[int, str], str] = {}
        for idx in range(1, len(doc.sentences)):
            prev = doc.sentences[idx - 1]
            cur = doc.sentences[idx]
            if prev.section_id == cur.section_id:
                mapping[(cur.page, cur.text)] = prev.text
        return mapping

    @staticmethod
    def _add_edge(claim: Claim, eq_obj: MathObject, via: str, matched_token: str, edges: list[CrossRefEdge], seen_edges: set[tuple[str, str, str, str]]) -> None:
        key = (claim.claim_id, eq_obj.math_id, via, matched_token)
        if key in seen_edges:
            return
        seen_edges.add(key)
        edges.append(CrossRefEdge(claim_id=claim.claim_id, math_id=eq_obj.math_id, via=via, matched_token=matched_token))  # type: ignore[arg-type]
        if eq_obj.math_id not in claim.linked_equation_ids:
            claim.linked_equation_ids.append(eq_obj.math_id)
        if claim.claim_id not in eq_obj.linked_claim_ids:
            eq_obj.linked_claim_ids.append(claim.claim_id)
