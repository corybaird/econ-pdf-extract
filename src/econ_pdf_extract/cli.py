from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from econ_pdf_extract.core import ConfigLoader, PaperMetadata
from econ_pdf_extract.nlp import SpacyClaimFilter
from econ_pdf_extract.pipeline import BatchPipeline, ExtractionPipeline
from econ_pdf_extract.reporting import JsonReportWriter, MarkdownReportWriter
from econ_pdf_extract.targets import TargetDrafter

logger = logging.getLogger(__name__)


class Cli:
    """Command-line interface exposing extract, report, targets, and eval subcommands."""

    def __init__(self, argv: list[str]):
        self._argv = argv

    def run(self) -> None:
        parser = self._parser()
        args = parser.parse_args(self._argv)
        self._configure_logging(args)
        if args.command == "extract":
            self._extract(args)
        elif args.command == "report":
            self._report(args)
        elif args.command == "targets":
            self._targets(args)
        elif args.command == "eval":
            self._eval(args)
        else:
            parser.print_help(sys.stderr)
            sys.exit(1)

    @staticmethod
    def _configure_logging(args: argparse.Namespace) -> None:
        level = logging.WARNING
        if getattr(args, "verbose", False):
            level = logging.INFO
        elif getattr(args, "quiet", False):
            level = logging.ERROR
        logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")

    def _extract(self, args: argparse.Namespace) -> None:
        paper = PaperMetadata(
            paper_id=args.pdf.stem,
            source_path=str(args.pdf),
            title=args.pdf.name,
        )
        refiner = SpacyClaimFilter(model_name=args.spacy_model) if args.spacy_filter else None
        result = ExtractionPipeline(
            pdf_path=args.pdf,
            paper=paper,
            ocr_backend=args.ocr,
            ocr_policy=args.ocr_policy,
            include_appendix=args.include_appendix,
            refiner=refiner,
            extract_causal_triples=args.causal_triples,
            spacy_model=args.spacy_model,
        ).run()

        include_lit = True if args.include_literature is None else args.include_literature
        include_dup = True if args.include_duplicates is None else args.include_duplicates
        json_writer = JsonReportWriter(include_literature=include_lit, include_duplicates=include_dup)
        md_writer = MarkdownReportWriter(include_duplicates=bool(args.include_duplicates))

        if args.output_dir is not None:
            if args.json or not args.markdown:
                j_dest = json_writer.write(result, args.output_dir)
                sys.stdout.write(f"Wrote JSON -> {j_dest}\n")
            if args.markdown:
                m_dest = md_writer.write(result, args.output_dir)
                sys.stdout.write(f"Wrote Markdown -> {m_dest}\n")
            return

        if args.json:
            sys.stdout.write(json_writer.to_json(result) + "\n")
            return
        if args.markdown:
            sys.stdout.write(md_writer.render(result) + "\n")
            return

        # Concise human-readable summary to stdout
        sys.stdout.write(f"File: {args.pdf}\n")
        sys.stdout.write(f"Pages: {result.page_count} | Sections: {len(result.sections)}\n")
        sys.stdout.write(f"Claims ({len(result.claims)}):\n")
        for c in result.claims[:5]:
            sys.stdout.write(f"  - [{c.claim_id} P{c.page}] ({c.section}) [{c.attribution.value}] {c.quote}\n")
        if len(result.claims) > 5:
            sys.stdout.write(f"  ... and {len(result.claims) - 5} more\n")
        sys.stdout.write(f"Math/Logic ({len(result.math_objects)}):\n")
        for m in result.math_objects[:5]:
            sys.stdout.write(f"  - [{m.math_id} P{m.page}] ({m.kind.value}) {m.tag or ''} {m.raw_text[:80]}\n")
        if len(result.math_objects) > 5:
            sys.stdout.write(f"  ... and {len(result.math_objects) - 5} more\n")

    def _report(self, args: argparse.Namespace) -> None:
        refiner = SpacyClaimFilter(model_name=args.spacy_model) if args.spacy_filter else None
        if args.pdf is not None:
            paper = PaperMetadata(paper_id=args.pdf.stem, source_path=str(args.pdf), title=args.pdf.name)
            pipeline = BatchPipeline(
                papers=[paper],
                reports_dir=args.reports_dir,
                ocr_backend=args.ocr,
                ocr_policy=args.ocr_policy,
                output_format=args.format,
                include_appendix=args.include_appendix,
                refiner=refiner,
                extract_causal_triples=args.causal_triples,
                spacy_model=args.spacy_model,
            )
            results = pipeline.run()
        else:
            pipeline = BatchPipeline.from_config(
                config_path=args.config,
                reports_dir=args.reports_dir,
                ocr_backend=args.ocr,
                ocr_policy=args.ocr_policy,
                output_format=args.format,
                include_appendix=args.include_appendix,
                refiner=refiner,
                extract_causal_triples=args.causal_triples,
                spacy_model=args.spacy_model,
            )
            ids = None if args.paper == "all" else [args.paper]
            results = pipeline.run(ids=ids)
        total_claims = sum(len(r.claims) for r in results)
        total_math = sum(len(r.math_objects) for r in results)
        sys.stdout.write(f"Done: {total_claims} claims, {total_math} math objects across {len(results)} paper(s).\n")

    def _targets(self, args: argparse.Namespace) -> None:
        if args.pdf is not None:
            if args.paper != "all":
                raise SystemExit("pass either a pdf path or --paper, not both")
            papers = [PaperMetadata(paper_id=args.pdf.stem, source_path=str(args.pdf), title=args.pdf.name)]
        else:
            all_papers = ConfigLoader().load_papers(args.config)
            papers = all_papers if args.paper == "all" else [p for p in all_papers if p.paper_id == args.paper]
            if not papers:
                raise SystemExit(f"paper id {args.paper!r} not found in papers config")

        for paper in papers:
            result = ExtractionPipeline(pdf_path=paper.pdf_path, paper=paper).run()
            dest = TargetDrafter(
                paper=paper,
                claims=result.claims,
                statistics=result.statistics,
                include_literature=args.include_literature,
                include_duplicates=args.include_duplicates,
            ).run(args.reports_dir)
            sys.stdout.write(f"[*] {paper.paper_id}: {len(result.claims)} claims, {len(result.statistics)} statistics -> {dest}\n")

    def _eval(self, args: argparse.Namespace) -> None:
        from econ_pdf_extract.eval.evaluator import ClaimEvaluator

        ids = None if args.paper == "all" else [args.paper]
        evaluator = ClaimEvaluator(
            refs_dir=args.refs_dir,
            config_path=args.config,
            output_dir=args.output_dir,
            paper_ids=ids,
        )
        summary = evaluator.run()
        agg = summary["aggregate"]
        sys.stdout.write(
            f"Eval complete: recall={agg['recall']:.3f} ({agg['tp']}/{agg['refs']}), "
            f"precision={agg['precision']:.3f} ({agg['matched_canonical']}/{agg['extracted']}), "
            f"exact_page={agg['exact_page_accuracy']:.3f}, "
            f"strict_section={agg['strict_section_accuracy']:.3f}, "
            f"role_section={agg['role_section_accuracy']:.3f}\n"
        )

    @staticmethod
    def _parser() -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(prog="econ-pdf", description="Extract claims, math/logic, symbols, and statistics from economics paper PDFs")
        parser.add_argument("--verbose", action="store_true", help="Enable info logging")
        parser.add_argument("--quiet", action="store_true", help="Suppress warnings")
        subparsers = parser.add_subparsers(dest="command")

        extract_parser = subparsers.add_parser("extract", help="Extract structured content from a single PDF")
        extract_parser.add_argument("pdf", type=Path, help="Path to PDF file")
        extract_parser.add_argument("--json", action="store_true", help="Emit full provenance JSON")
        extract_parser.add_argument("--markdown", action="store_true", help="Emit auditable Markdown report")
        extract_parser.add_argument("--output-dir", type=Path, default=None, help="Directory for timestamped output files")
        extract_parser.add_argument("--ocr", default="none", help="OCR backend: none (default) or glm_ocr")
        extract_parser.add_argument("--ocr-policy", default="fallback", choices=["none", "fallback", "all_displays"], help="Targeted OCR policy")
        extract_parser.add_argument("--include-appendix", action="store_true", help="Include Appendix sections in claim extraction")
        extract_parser.add_argument("--spacy-filter", action="store_true", help="Refine claims with optional spaCy dependency filter")
        extract_parser.add_argument("--causal-triples", action="store_true", help="Extract (cause, direction, outcome) triples with spaCy")
        extract_parser.add_argument("--spacy-model", default=None, help="spaCy model name (default from extraction.yaml)")
        extract_parser.add_argument("--include-literature", action=argparse.BooleanOptionalAction, default=None, help="Include literature claims in JSON output")
        extract_parser.add_argument("--include-duplicates", action=argparse.BooleanOptionalAction, default=None, help="Include near-duplicate claims in output")

        report_parser = subparsers.add_parser("report", help="Write JSON/Markdown reports for configured papers")
        report_parser.add_argument("--paper", default="all", help="Paper id from papers.yaml (default: all)")
        report_parser.add_argument("--pdf", type=Path, default=None, help="Ad-hoc PDF overriding --paper")
        report_parser.add_argument("--config", type=Path, default=None, help="papers.yaml path")
        report_parser.add_argument("--reports-dir", type=Path, default=Path("reports/tables"), help="Output directory")
        report_parser.add_argument("--format", default="both", choices=["json", "markdown", "both"], help="Output format")
        report_parser.add_argument("--ocr", default="none", help="OCR backend: none or glm_ocr")
        report_parser.add_argument("--ocr-policy", default="fallback", choices=["none", "fallback", "all_displays"], help="Targeted OCR policy")
        report_parser.add_argument("--include-appendix", action="store_true", help="Include Appendix sections")
        report_parser.add_argument("--spacy-filter", action="store_true", help="Refine claims with optional spaCy dependency filter")
        report_parser.add_argument("--causal-triples", action="store_true", help="Extract (cause, direction, outcome) triples with spaCy")
        report_parser.add_argument("--spacy-model", default=None, help="spaCy model name (default from extraction.yaml)")

        targets_parser = subparsers.add_parser("targets", help="Write draft MaRCo@BIS-style paper targets YAML")
        targets_parser.add_argument("pdf", type=Path, nargs="?", default=None, help="Path to PDF file (or omit and use --paper)")
        targets_parser.add_argument("--paper", default="all", help="Paper id from papers.yaml (default: all)")
        targets_parser.add_argument("--config", type=Path, default=None, help="papers.yaml path")
        targets_parser.add_argument("--reports-dir", type=Path, default=Path("reports/tables"), help="Output directory")
        targets_parser.add_argument("--include-literature", action="store_true", help="Include literature claims")
        targets_parser.add_argument("--include-duplicates", action="store_true", help="Include duplicate claims")

        eval_parser = subparsers.add_parser("eval", help="Evaluate claim extraction against local reference YAMLs")
        eval_parser.add_argument("--refs-dir", type=Path, required=True, help="Directory with ref_claims_<id>.yaml files")
        eval_parser.add_argument("--config", type=Path, default=None, help="Local papers.yaml path")
        eval_parser.add_argument("--output-dir", type=Path, default=None, help="Directory for timestamped eval reports")
        eval_parser.add_argument("--paper", default="all", help="Paper id to evaluate (default: all)")

        return parser


def entry() -> None:
    Cli(sys.argv[1:]).run()


if __name__ == "__main__":
    Cli(sys.argv[1:]).run()
