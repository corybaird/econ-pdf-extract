from __future__ import annotations

import re
from typing import Any

from econ_pdf_extract.core.config import ConfigLoader
from econ_pdf_extract.core.models import (
    BBox,
    Document,
    MathObject,
    SourceChannel,
    SymbolDef,
)
from econ_pdf_extract.core.paths import load_dictionary

_NON_SYMBOL_WORDS = frozenset(
    {
        "the",
        "this",
        "that",
        "these",
        "those",
        "which",
        "where",
        "when",
        "while",
        "with",
        "from",
        "into",
        "each",
        "both",
        "such",
        "also",
        "here",
        "there",
        "model",
        "table",
        "figure",
        "paper",
        "study",
        "result",
        "results",
        "section",
        "equation",
        "forecast",
        "return",
        "returns",
        "value",
        "values",
        "vector",
        "matrix",
        "parameter",
        "variable",
        "index",
        "error",
        "series",
        "sample",
        "period",
        "horizon",
        "method",
        "approach",
        "data",
        "note",
        "we",
        "it",
        "they",
        "in",
        "of",
        "and",
        "or",
        "for",
        "by",
        "as",
        "at",
        "to",
        "on",
    }
)


def normalize_symbol(raw: str, greek_map: dict[str, str] | None = None) -> str:
    """Normalize a math symbol to a canonical subscript/superscript-insensitive matching key."""
    text = raw.strip()
    if greek_map:
        for ch, macro in greek_map.items():
            if ch in text:
                text = text.replace(ch, macro.lstrip("\\"))
    text = text.replace("\\", "")
    text = re.sub(r"[\s{}_^()\[\]'`]+", "", text)
    return text.lower()


class SymbolDefinitionExtractor:
    """Extracts symbol definitions from post-display 'where ... denotes' and 'In (tag)...' epilogues."""

    def __init__(self, math_cfg: dict[str, Any] | None = None):
        cfg = math_cfg if math_cfg is not None else ConfigLoader().load("math_patterns.yaml")
        sym_cfg = cfg.get("symbol_definition_patterns", {})
        forward_verb = sym_cfg.get(
            "forward_verb",
            r"(?:denotes?|indicates?|represents?|measures?|identifies?|corresponds?\s+to|refers?\s+to|is\s+(?:the|a|an)|is\s+defined\s+as|equals?)",
        )
        reverse_verb = sym_cfg.get("reverse_verb", r"(?:we\s+)?(?:denote|define)")
        self._in_eq_re = re.compile(sym_cfg.get("in_eq_intro", r"\bIn\s+(?:Eq(?:uation)?\.?\s*)?\((?P<tag>(?:[1-9]\d*|[A-Z])(?:\.\d+)*)\)"), re.IGNORECASE)
        self._where_re = re.compile(sym_cfg.get("where_intro", r"\bwhere\b"), re.IGNORECASE)
        self._forward_re = re.compile(
            rf"(?:^|(?<=,\s)|(?<=;\s)|(?<=\band\s))(?P<sym>\\?[A-Za-zα-ωΑ-Ω∆ΣΩϕεµ][A-Za-z0-9α-ωΑ-Ω_^()\{{\}}\-']{{0,18}})\s+{forward_verb}\s+(?P<desc>[^.;]+)",
            re.IGNORECASE,
        )
        self._reverse_re = re.compile(
            rf"{reverse_verb}\s+(?P<desc>[^.;,]+?)\s+(?:as|by|with)\s+(?P<sym>\\?[A-Za-zα-ωΑ-Ω∆ΣΩϕεµ][A-Za-z0-9α-ωΑ-Ω_^()\{{\}}\-']{{0,18}})\b",
            re.IGNORECASE,
        )

        self._greek_map = load_dictionary("greek_to_latex").GREEK_TO_LATEX

    def extract(self, doc: Document, math_objects: list[MathObject]) -> list[SymbolDef]:
        by_tag = {m.tag: m for m in math_objects if m.tag is not None}
        symbols: list[SymbolDef] = []
        seen: set[tuple[str, str | None]] = set()
        seq = 0

        # 1. Extract from each display equation's epilogue (context_after) and preamble (context_before)
        for obj in math_objects:
            if obj.context_after:
                extracted = self._parse_text(obj.context_after, obj.math_id, obj.page, obj.section, obj.bbox, set())
                for sym_def in extracted:
                    key = (sym_def.normalized, sym_def.equation_id)
                    if key in seen:
                        continue
                    seen.add(key)
                    seq += 1
                    sym_def.symbol_id = f"SYM-{seq:03d}"
                    obj.symbols_defined.append(sym_def)
                    symbols.append(sym_def)

            if obj.context_before:
                extracted = self._parse_reverse_only(obj.context_before, obj.math_id, obj.page, obj.section, obj.bbox, set())
                for sym_def in extracted:
                    key = (sym_def.normalized, sym_def.equation_id)
                    if key in seen:
                        continue
                    seen.add(key)
                    seq += 1
                    sym_def.symbol_id = f"SYM-{seq:03d}"
                    obj.symbols_defined.append(sym_def)
                    symbols.append(sym_def)

        # 2. Extract from explicit "In (tag), ..." or "where ..." sentences in Document.sentences
        for sent in doc.sentences:
            eq_obj: MathObject | None = None
            in_match = self._in_eq_re.search(sent.text)
            if in_match:
                tag = f"({in_match.group('tag')})"
                eq_obj = by_tag.get(tag)
            elif self._where_re.search(sent.text):
                eq_obj = self._nearest_preceding_display(math_objects, sent.page, sent.bbox[1])

            if eq_obj is None and not in_match:
                continue

            eq_id = eq_obj.math_id if eq_obj is not None else None
            math_tok_set = {normalize_symbol(t, self._greek_map) for t in sent.math_tokens}
            extracted = self._parse_text(sent.text, eq_id, sent.page, sent.section_heading, sent.bbox, math_tok_set)
            for sym_def in extracted:
                key = (sym_def.normalized, sym_def.equation_id)
                if key in seen:
                    continue
                seen.add(key)
                seq += 1
                sym_def.symbol_id = f"SYM-{seq:03d}"
                if eq_obj is not None:
                    eq_obj.symbols_defined.append(sym_def)
                symbols.append(sym_def)

        return symbols

    def _parse_text(self, text: str, equation_id: str | None, page: int, section: str, bbox: BBox, math_tokens: set[str]) -> list[SymbolDef]:
        results: list[SymbolDef] = []
        # Focus on the defining clause after "where" or "In (tag)," if present
        segment = text
        where_m = self._where_re.search(text)
        in_m = self._in_eq_re.search(text)
        if where_m:
            segment = text[where_m.end() :].strip(" ,:")
        elif in_m:
            segment = text[in_m.end() :].strip(" ,:")
        else:
            return self._parse_reverse_only(text, equation_id, page, section, bbox, math_tokens)

        clauses = re.split(r";|\s+and\s+(?=[\\A-Za-zα-ωΑ-Ω∆ΣΩϕεµ][A-Za-z0-9α-ωΑ-Ω_^()\{{\}}\-']{0,18}\s+(?:denotes?|indicates?|represents?|measures?|identifies?|corresponds?|refers?|is\b|equals?))|,\s+(?=[\\A-Za-zα-ωΑ-Ω∆ΣΩϕεµ][A-Za-z0-9α-ωΑ-Ω_^()\{{\}}\-']{0,18}\s+(?:denotes?|indicates?|represents?|measures?|identifies?|corresponds?|refers?|is\b|equals?))", segment)
        for clause in clauses:
            clause = clause.strip(" ,.")
            if not clause:
                continue
            m = self._forward_re.search(clause)
            if not m:
                continue
            sym = m.group("sym").strip(" ,.;:()")
            desc = re.sub(r"\s+", " ", m.group("desc")).strip(" ,.;:")
            if not self._is_valid_symbol(sym, math_tokens) or len(desc) < 3:
                continue
            results.append(
                SymbolDef(
                    symbol_id="",
                    symbol=sym,
                    normalized=normalize_symbol(sym, self._greek_map),
                    description=desc,
                    equation_id=equation_id,
                    page=page,
                    section=section,
                    bbox=bbox,
                    source_channel=SourceChannel.TEXT,
                )
            )
        results.extend(self._parse_reverse_only(text, equation_id, page, section, bbox, math_tokens))
        return results

    def _parse_reverse_only(self, text: str, equation_id: str | None, page: int, section: str, bbox: BBox, math_tokens: set[str]) -> list[SymbolDef]:
        results: list[SymbolDef] = []
        for m in self._reverse_re.finditer(text):
            sym = m.group("sym").strip(" ,.;:()")
            desc = re.sub(r"\s+", " ", m.group("desc")).strip(" ,.;:")
            if not self._is_valid_symbol(sym, math_tokens) or len(desc) < 3:
                continue
            results.append(
                SymbolDef(
                    symbol_id="",
                    symbol=sym,
                    normalized=normalize_symbol(sym, self._greek_map),
                    description=desc,
                    equation_id=equation_id,
                    page=page,
                    section=section,
                    bbox=bbox,
                    source_channel=SourceChannel.TEXT,
                )
            )
        return results

    def _is_valid_symbol(self, sym: str, math_tokens: set[str]) -> bool:
        if not sym or len(sym) > 20:
            return False
        low = sym.lower()
        if low in _NON_SYMBOL_WORDS:
            return False
        norm = normalize_symbol(sym, self._greek_map)
        if not norm:
            return False
        if norm in math_tokens:
            return True
        if len(sym) == 1:
            return sym.isalpha() and low not in {"a", "i"}
        # Multi-character symbol: require math syntax (_, ^, \, digits, Greek) or short uppercase acronym (<= 6 chars)
        if any(ch in sym for ch in ("_", "^", "\\", "'")) or any(ch.isdigit() for ch in sym):
            return True
        if any(ch in self._greek_map for ch in sym):
            return True
        return bool(sym.isupper() and 2 <= len(sym) <= 6)

    @staticmethod
    def _nearest_preceding_display(math_objects: list[MathObject], page: int, y: float) -> MathObject | None:
        candidates = [
            m
            for m in math_objects
            if m.page == page and m.bbox[3] <= y + 10.0 and (y - m.bbox[3]) <= 120.0
        ]
        if candidates:
            candidates.sort(key=lambda m: m.bbox[3])
            return candidates[-1]
        return None
