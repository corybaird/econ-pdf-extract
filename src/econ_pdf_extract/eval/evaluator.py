from __future__ import annotations

import argparse
import difflib
import json
import logging
import re
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from econ_pdf_extract.core import (
    Attribution,
    Claim,
    ConfigLoader,
    ExtractionResult,
    PaperMetadata,
    SectionRole,
)
from econ_pdf_extract.pipeline import ExtractionPipeline

logger = logging.getLogger(__name__)

_LIGATURE_MAP = str.maketrans(
    {
        "\ufb00": "ff",
        "\ufb01": "fi",
        "\ufb02": "fl",
        "\ufb03": "ffi",
        "\ufb04": "ffl",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "-",
    }
)
_WORD_RE = re.compile(r"[a-z0-9]+")


def normalize_claim_text(text: str) -> str:
    cleaned = text.translate(_LIGATURE_MAP)
    cleaned = re.sub(r"-\s+", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.lower().strip()


def token_f1(ref_norm: str, cand_norm: str) -> float:
    ref_toks = Counter(_WORD_RE.findall(ref_norm))
    cand_toks = Counter(_WORD_RE.findall(cand_norm))
    if not ref_toks or not cand_toks:
        return 0.0
    overlap = sum((ref_toks & cand_toks).values())
    if overlap == 0:
        return 0.0
    prec = overlap / sum(cand_toks.values())
    rec = overlap / sum(ref_toks.values())
    return 2.0 * prec * rec / (prec + rec)


def claim_similarity(ref_quote: str, cand_quote: str) -> tuple[float, float]:
    n_ref = normalize_claim_text(ref_quote)
    n_cand = normalize_claim_text(cand_quote)
    seq_ratio = difflib.SequenceMatcher(None, n_ref, n_cand).ratio()
    f1 = token_f1(n_ref, n_cand)
    return seq_ratio, f1


_LEADING_SEC_NUM_RE = re.compile(r"^(?:[1-9]\d*(?:\.\d+)*|[a-z])\.?\s+", re.IGNORECASE)
_PAREN_GROUP_RE = re.compile(r"\(([^)]+)\)")


def _norm_heading(text: str) -> str:
    cleaned = text.strip().lower()
    cleaned = _LEADING_SEC_NUM_RE.sub("", cleaned)
    cleaned = re.sub(r"[^a-z0-9\s]+", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def strict_section_matches(ref_section: str, extracted_heading: str) -> bool:
    """True only when normalized extracted heading exactly matches the normalized reference heading (or parenthetical sub-heading)."""
    cand = _norm_heading(extracted_heading)
    if not cand:
        return False
    parts = {_norm_heading(ref_section)}
    base = re.sub(r"\([^)]*\)", " ", ref_section)
    base_norm = _norm_heading(base)
    if base_norm:
        parts.add(base_norm)
    for m in _PAREN_GROUP_RE.finditer(ref_section):
        inner = _norm_heading(m.group(1))
        if inner:
            parts.add(inner)
    return cand in parts


def role_section_matches(ref_section: str, claim: Claim) -> bool:
    """True when strict heading matches or the extracted SectionRole aligns with the reference section role."""
    if strict_section_matches(ref_section, claim.section):
        return True
    role_hints = {
        SectionRole.ABSTRACT: ("abstract",),
        SectionRole.INTRODUCTION: ("introduction", "intro"),
        SectionRole.RESULTS: ("result", "empirical", "forecast", "out-of-sample", "economic", "evaluation", "analysis"),
        SectionRole.ROBUSTNESS: ("robust", "sensitivity"),
        SectionRole.CONCLUSION: ("conclusion", "concluding", "summary"),
        SectionRole.METHODOLOGY: ("model", "method", "estimation", "algorithm", "factor"),
        SectionRole.DATA: ("data", "sample"),
        SectionRole.APPENDIX: ("appendix",),
    }
    hints = role_hints.get(claim.section_role, ())
    ref_low = ref_section.lower()
    return any(h in ref_low for h in hints)


class ClaimEvaluator:
    """Offline local benchmark comparing ExtractionPipeline claims against reference YAML files."""

    def __init__(self, refs_dir: Path, config_path: Path | None = None, output_dir: Path | None = None, paper_ids: list[str] | None = None, papers: list[PaperMetadata] | None = None, seq_threshold: float = 0.72, f1_threshold: float = 0.75):
        self._refs_dir = Path(refs_dir)
        self._config_path = Path(config_path) if config_path is not None else None
        self._output_dir = Path(output_dir) if output_dir is not None else None
        self._paper_ids = paper_ids
        self._papers = papers
        self._seq_threshold = seq_threshold
        self._f1_threshold = f1_threshold

    @classmethod
    def from_cli(cls, argv: list[str] | None = None) -> ClaimEvaluator:
        parser = argparse.ArgumentParser(description="Evaluate econ-pdf-extract against local reference claim YAMLs")
        parser.add_argument("--refs-dir", type=Path, required=True)
        parser.add_argument("--config", type=Path, default=None)
        parser.add_argument("--output-dir", type=Path, default=None)
        parser.add_argument("--paper", default="all")
        args = parser.parse_args(argv if argv is not None else sys.argv[1:])
        ids = None if args.paper == "all" else [args.paper]
        return cls(refs_dir=args.refs_dir, config_path=args.config, output_dir=args.output_dir, paper_ids=ids)

    def run(self) -> dict[str, Any]:
        papers = self._papers if self._papers is not None else ConfigLoader().load_papers(self._config_path)
        selected = [p for p in papers if self._paper_ids is None or p.paper_id in self._paper_ids]

        per_paper: list[dict[str, Any]] = []
        tot_refs = 0
        tot_tp = 0
        tot_canonical = 0
        tot_matched_canonical = 0
        tot_exact_page = 0
        tot_strict_section = 0
        tot_role_section = 0

        for paper in selected:
            ref_path = self._refs_dir / f"ref_claims_{paper.paper_id}.yaml"
            if not ref_path.exists():
                logger.warning("Reference YAML missing for %s at %s; skipping", paper.paper_id, ref_path)
                continue
            refs = yaml.safe_load(ref_path.read_text(encoding="utf-8")) or []
            result = ExtractionPipeline(pdf_path=paper.pdf_path, paper=paper).run()
            metrics = self.evaluate_result(paper.paper_id, refs, result)
            per_paper.append(metrics)

            tot_refs += metrics["refs"]
            tot_tp += metrics["tp"]
            tot_canonical += metrics["canonical_extracted"]
            tot_matched_canonical += metrics["matched_canonical"]
            tot_exact_page += metrics["exact_page_matches"]
            tot_strict_section += metrics["strict_section_matches"]
            tot_role_section += metrics["role_section_matches"]

        min_recall = min((m["recall"] for m in per_paper), default=0.0)
        summary = {
            "evaluated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "papers": per_paper,
            "aggregate": {
                "paper_count": len(per_paper),
                "refs": tot_refs,
                "tp": tot_tp,
                "extracted": tot_canonical,
                "matched_canonical": tot_matched_canonical,
                "recall": (tot_tp / tot_refs) if tot_refs else 0.0,
                "min_paper_recall": min_recall,
                "precision": (tot_matched_canonical / tot_canonical) if tot_canonical else 0.0,
                "volume_ratio": (tot_canonical / tot_refs) if tot_refs else 0.0,
                "exact_page_matches": tot_exact_page,
                "exact_page_accuracy": (tot_exact_page / tot_tp) if tot_tp else 0.0,
                "strict_section_matches": tot_strict_section,
                "strict_section_accuracy": (tot_strict_section / tot_tp) if tot_tp else 0.0,
                "role_section_matches": tot_role_section,
                "role_section_accuracy": (tot_role_section / tot_tp) if tot_tp else 0.0,
            },
        }

        if self._output_dir is not None:
            self._write_outputs(summary)
        return summary

    def evaluate_result(self, paper_id: str, refs: list[dict[str, Any]], result: ExtractionResult) -> dict[str, Any]:
        own_claims = [c for c in result.claims if c.attribution != Attribution.LITERATURE]
        canonical_claims = [c for c in own_claims if c.duplicate_of is None]
        by_id = {c.claim_id: c for c in result.claims}

        tp = 0
        exact_page_matches = 0
        strict_section_matches_count = 0
        role_section_matches_count = 0
        matched_canonical_ids: set[str] = set()
        missed_refs: list[dict[str, Any]] = []
        matched_details: list[dict[str, Any]] = []

        for ref in refs:
            ref_quote = str(ref["quote"])
            ref_page = int(ref["page"])
            ref_section = str(ref.get("section", ""))

            best_claim: Claim | None = None
            best_score = 0.0
            best_seq = 0.0
            best_f1 = 0.0

            for cand in own_claims:
                seq_r, f1_r = claim_similarity(ref_quote, cand.quote)
                passes = seq_r >= self._seq_threshold or f1_r >= self._f1_threshold
                score = max(seq_r, f1_r)
                if passes:
                    # Prefer match on the exact reference page when near-duplicates exist
                    page_bonus = 0.05 if cand.page <= ref_page <= cand.page_end else 0.0
                    if score + page_bonus > best_score:
                        best_claim = cand
                        best_score = score + page_bonus
                        best_seq = seq_r
                        best_f1 = f1_r
                elif best_claim is None and score > best_score:
                    best_score = score
                    best_seq = seq_r
                    best_f1 = f1_r

            if best_claim is not None:
                tp += 1
                canon_id = best_claim.duplicate_of or best_claim.claim_id
                if canon_id in by_id:
                    matched_canonical_ids.add(canon_id)
                page_ok = best_claim.page <= ref_page <= best_claim.page_end
                if not page_ok and best_claim.also_seen_on:
                    page_ok = any(r.page == ref_page for r in best_claim.also_seen_on)
                if page_ok:
                    exact_page_matches += 1
                strict_ok = strict_section_matches(ref_section, best_claim.section)
                role_ok = role_section_matches(ref_section, best_claim)
                if strict_ok:
                    strict_section_matches_count += 1
                if role_ok:
                    role_section_matches_count += 1
                matched_details.append(
                    {
                        "ref_page": ref_page,
                        "extracted_page": best_claim.page,
                        "page_ok": page_ok,
                        "ref_section": ref_section,
                        "extracted_section": best_claim.section,
                        "strict_section_ok": strict_ok,
                        "role_section_ok": role_ok,
                        "claim_id": best_claim.claim_id,
                        "seq_ratio": round(best_seq, 3),
                        "token_f1": round(best_f1, 3),
                    }
                )
            else:
                missed_refs.append(
                    {
                        "page": ref_page,
                        "section": ref_section,
                        "type": ref.get("type", ""),
                        "quote": ref_quote,
                        "best_seq": round(best_seq, 3),
                        "best_f1": round(best_f1, 3),
                    }
                )

        attr_counts = Counter(c.attribution.value for c in result.claims)
        n_refs = len(refs)
        n_canon = len(canonical_claims)
        return {
            "paper_id": paper_id,
            "refs": n_refs,
            "tp": tp,
            "canonical_extracted": n_canon,
            "total_extracted": len(result.claims),
            "duplicates_clustered": sum(1 for c in result.claims if c.duplicate_of is not None),
            "matched_canonical": len(matched_canonical_ids),
            "recall": (tp / n_refs) if n_refs else 0.0,
            "precision": (len(matched_canonical_ids) / n_canon) if n_canon else 0.0,
            "volume_ratio": (n_canon / n_refs) if n_refs else 0.0,
            "exact_page_matches": exact_page_matches,
            "exact_page_accuracy": (exact_page_matches / tp) if tp else 0.0,
            "strict_section_matches": strict_section_matches_count,
            "strict_section_accuracy": (strict_section_matches_count / tp) if tp else 0.0,
            "role_section_matches": role_section_matches_count,
            "role_section_accuracy": (role_section_matches_count / tp) if tp else 0.0,
            "attribution_counts": dict(attr_counts),
            "math_objects": len(result.math_objects),
            "numbered_equations": sum(1 for m in result.math_objects if m.tag is not None and m.tag.startswith("(")),
            "symbols": len(result.symbols),
            "links": len(result.links),
            "duplicate_front_matter_pages": result.diagnostics.get("duplicate_front_matter_pages", []),
            "missed_refs": missed_refs,
            "matched_details": matched_details,
        }

    def _write_outputs(self, summary: dict[str, Any]) -> tuple[Path, Path]:
        assert self._output_dir is not None
        self._output_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        json_path = self._output_dir / f"eval_claims_{ts}.json"
        md_path = self._output_dir / f"eval_claims_{ts}.md"
        json_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        md_path.write_text(self._render_markdown(summary), encoding="utf-8")
        return json_path, md_path

    @staticmethod
    def _render_markdown(summary: dict[str, Any]) -> str:
        agg = summary["aggregate"]
        lines = [
            "# Claim Extraction Evaluation Report",
            "",
            f"**Evaluated At:** `{summary['evaluated_at']}`  ",
            "",
            "## Per-Paper Metrics",
            "",
            "| Paper | Refs | TP | Recall | Canonical Ext | Vol Ratio | Precision | Exact Page | Strict Sec | Role Sec | Math Objs | Numbered Eqs | Symbols | Links |",
            "|:------|-----:|---:|-------:|--------------:|----------:|----------:|-----------:|-----------:|---------:|----------:|-------------:|--------:|------:|",
        ]
        for p in summary["papers"]:
            lines.append(
                f"| `{p['paper_id']}` | {p['refs']} | {p['tp']} | {p['recall']:.2f} | {p['canonical_extracted']} | {p['volume_ratio']:.2f}x | {p['precision']:.2f} | {p['exact_page_accuracy']:.2f} | {p['strict_section_accuracy']:.2f} | {p['role_section_accuracy']:.2f} | {p['math_objects']} | {p['numbered_equations']} | {p['symbols']} | {p['links']} |"
            )
        lines.append(
            f"| **Total / Aggregate** | **{agg['refs']}** | **{agg['tp']}** | **{agg['recall']:.2f}** | **{agg['extracted']}** | **{agg['volume_ratio']:.2f}x** | **{agg['precision']:.2f}** | **{agg['exact_page_accuracy']:.2f}** | **{agg['strict_section_accuracy']:.2f}** | **{agg['role_section_accuracy']:.2f}** | - | - | - | - |"
        )
        lines.append("")
        return "\n".join(lines)


if __name__ == "__main__":
    ClaimEvaluator.from_cli().run()
