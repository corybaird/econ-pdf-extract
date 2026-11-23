from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from econ_pdf_extract.core.models import (
    Attribution,
    Claim,
    ExtractionResult,
    MathObject,
)


def _md_escape(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().replace("|", r"\|")


def _page_label(page: int, page_end: int) -> str:
    return str(page) if page_end == page else f"{page}-{page_end}"


class MarkdownReportWriter:
    """Renders an auditable Markdown report with headline claims, literature appendix, math catalog, and symbols."""

    def __init__(self, include_duplicates: bool = False):
        self._include_duplicates = include_duplicates

    def render(self, result: ExtractionResult) -> str:
        paper = result.paper
        headline_claims = self._filter_claims(result.claims, literature=False)
        lit_claims = self._filter_claims(result.claims, literature=True)
        dup_pages = result.diagnostics.get("duplicate_front_matter_pages", [])

        triples_summary = f", {len(result.causal_triples)} causal triples" if result.causal_triples else ""
        lines: list[str] = [
            f"# Extraction Report — {paper.authors or paper.paper_id}",
            "",
            f"**Paper:** *{paper.title or paper.paper_id}*  ",
            f"**Venue:** {paper.journal or 'Unspecified'}  ",
            f"**Source PDF:** `{paper.source_path}`  ",
            f"**Pages:** {result.page_count}  ",
            f"**Extracted At:** `{result.extracted_at}`  ",
            f"**OCR:** backend=`{result.ocr_backend}`, policy=`{result.ocr_policy}`, calls={result.diagnostics.get('ocr_calls', 0)}  ",
            f"**Summary:** {len(headline_claims)} headline claims ({len(lit_claims)} literature), {len(result.math_objects)} math/logic objects, {len(result.symbols)} symbols, {len(result.links)} links{triples_summary}  ",
        ]
        if dup_pages:
            lines.append(f"**Skipped Duplicate Front-Matter Pages:** {', '.join(str(p) for p in dup_pages)}  ")
        lines.append("")

        # Section 1: Headline Claims
        lines += [
            "## Headline Claims",
            "",
            "| Claim ID | Page | Section | Type | Attribution | Linked Eqs | Claim |",
            "|:---------|:----:|:--------|:-----|:------------|:-----------|:------|",
        ]
        for claim in headline_claims:
            types = ", ".join(t.value for t in claim.claim_types)
            eqs = ", ".join(claim.linked_equation_ids) if claim.linked_equation_ids else "-"
            quote_str = _md_escape(claim.quote)
            if claim.also_seen_on:
                refs = "; ".join(f"p.{r.page} ({_md_escape(r.section)})" for r in claim.also_seen_on)
                quote_str = f"{quote_str} *(also seen on: {refs})*"
            lines.append(
                f"| `{claim.claim_id}` | {_page_label(claim.page, claim.page_end)} | {_md_escape(claim.section)} | {types} | {claim.attribution.value} | {eqs} | {quote_str} |"
            )
        lines.append("")

        # Section 2: Literature Claims Appendix
        if lit_claims:
            lines += [
                "## Literature Claims Appendix",
                "",
                "| Claim ID | Page | Section | Type | Claim |",
                "|:---------|:----:|:--------|:-----|:------|",
            ]
            for claim in lit_claims:
                types = ", ".join(t.value for t in claim.claim_types)
                lines.append(
                    f"| `{claim.claim_id}` | {_page_label(claim.page, claim.page_end)} | {_md_escape(claim.section)} | {types} | {_md_escape(claim.quote)} |"
                )
            lines.append("")

        # Section 3: Math & Logic Catalog
        lines += [
            "## Math & Logic Catalog",
            "",
            "| ID | Kind | Tag | Page | Section | Channel | Content | Linked Claims |",
            "|:---|:-----|:---:|:----:|:--------|:--------|:--------|:--------------|",
        ]
        for obj in result.math_objects:
            content = self._math_content(obj)
            linked = ", ".join(obj.linked_claim_ids) if obj.linked_claim_ids else "-"
            tag = obj.tag or "-"
            lines.append(
                f"| `{obj.math_id}` | {obj.kind.value} | {tag} | {_page_label(obj.page, obj.page_end)} | {_md_escape(obj.section)} | {obj.source_channel.value} | {_md_escape(content)} | {linked} |"
            )
        lines.append("")

        # Section 4: Symbol Glossary
        lines += [
            "## Symbol Glossary",
            "",
            "| Symbol | Definition | Defined In | Page | Section |",
            "|:-------|:-----------|:-----------|:----:|:--------|",
        ]
        for sym in result.symbols:
            eq_id = sym.equation_id or "-"
            lines.append(
                f"| `{_md_escape(sym.symbol)}` | {_md_escape(sym.description)} | {eq_id} | {sym.page} | {_md_escape(sym.section)} |"
            )

        # Section 5: Causal Triples (optional NLP stage)
        if result.causal_triples:
            lines += [
                "",
                "## Causal Triples",
                "",
                "| Triple ID | Page | Section | Cause | Direction | Outcome | Sentence |",
                "|:----------|:----:|:--------|:------|:----------|:--------|:---------|",
            ]
            for trp in result.causal_triples:
                lines.append(
                    f"| `{trp.triple_id}` | {_page_label(trp.page, trp.page_end)} | {_md_escape(trp.section)} | {_md_escape(trp.cause)} | {trp.direction} | {_md_escape(trp.outcome)} | {_md_escape(trp.sentence)} |"
                )

        lines += ["", "---", "*Report generated automatically by `econ-pdf-extract`.*", ""]
        return "\n".join(lines)

    def write(self, result: ExtractionResult, output_dir: Path, timestamp: str | None = None) -> Path:
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = timestamp or datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        dest = out_dir / f"extracted_report_{result.paper.paper_id}_{ts}.md"
        dest.write_text(self.render(result), encoding="utf-8")
        return dest

    def _filter_claims(self, claims: list[Claim], literature: bool) -> list[Claim]:
        selected: list[Claim] = []
        for claim in claims:
            if not self._include_duplicates and claim.duplicate_of is not None:
                continue
            is_lit = claim.attribution == Attribution.LITERATURE
            if is_lit == literature:
                selected.append(claim)
        return selected

    @staticmethod
    def _math_content(obj: MathObject) -> str:
        body = obj.latex if obj.latex else obj.raw_text
        return body if len(body) <= 180 else body[:177].rstrip() + "..."


class BatchSummaryWriter:
    """Renders a multi-paper Markdown summary table across ExtractionResult objects."""

    def render(self, results: list[ExtractionResult]) -> str:
        total_claims = sum(
            sum(1 for c in r.claims if c.duplicate_of is None and c.attribution != Attribution.LITERATURE)
            for r in results
        )
        total_math = sum(len(r.math_objects) for r in results)
        lines: list[str] = [
            "# Extracted Papers Summary",
            "",
            f"**Papers Processed:** {len(results)}  ",
            f"**Canonical Headline Claims:** {total_claims}  ",
            f"**Math & Logic Objects:** {total_math}  ",
            "",
            "## Summary by Paper",
            "",
            "| Paper ID | Authors | Title | Headline Claims | Math Objects | Symbols | Links |",
            "|:---------|:--------|:------|:---------------:|:------------:|:-------:|:-----:|",
        ]
        for res in results:
            headline = sum(1 for c in res.claims if c.duplicate_of is None and c.attribution != Attribution.LITERATURE)
            lines.append(
                f"| `{res.paper.paper_id}` | {_md_escape(res.paper.authors)} | *{_md_escape(res.paper.title)}* | **{headline}** | {len(res.math_objects)} | {len(res.symbols)} | {len(res.links)} |"
            )
        lines += ["", "---", "*Summary generated automatically by `econ-pdf-extract`.*", ""]
        return "\n".join(lines)

    def write(self, results: list[ExtractionResult], output_dir: Path, timestamp: str | None = None) -> Path:
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = timestamp or datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        dest = out_dir / f"extracted_summary_all_{ts}.md"
        dest.write_text(self.render(results), encoding="utf-8")
        return dest
