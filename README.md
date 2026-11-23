# econ-pdf-extract

Deterministic, modular Python library for extracting auditable **empirical claims**, **math and logic objects**, **symbol definitions**, **cross-reference links**, and **quantitative statistics** from economics working-paper and journal-article PDFs.

Every extracted claim and math/logic object preserves exact PDF provenance (`page`, `page_end`, `section`, `bbox`, `source_channel`). The library establishes **section and page**, never truth.

## Status

- Version `0.1.0`, first public release (beta): APIs and configs may change before 1.0
- Release notes: [CHANGELOG.md](CHANGELOG.md), plans: [ROADMAP.md](ROADMAP.md)
- Part of the [Econ Agent Harness workshop](https://github.com/corybaird/econ-agent-workshop)

## Install

Not yet on PyPI, install from GitHub:

```bash
uv add "econ-pdf-extract @ git+https://github.com/corybaird/econ-pdf-extract"
# or: pip install "git+https://github.com/corybaird/econ-pdf-extract"
```

## Quickstart

```python
from econ_pdf_extract import ExtractionPipeline, JsonReportWriter, MarkdownReportWriter

result = ExtractionPipeline("examples/example_paper.pdf").run()

for claim in result.claims:
    print(claim.claim_id, claim.page, claim.section, claim.attribution.value, claim.quote)

for eq in result.math_objects:
    print(eq.math_id, eq.kind.value, eq.tag, eq.page, eq.raw_text)

json_text = JsonReportWriter().to_json(result)
md_text = MarkdownReportWriter().render(result)
```

See also the CLI walkthrough in [`docs/quickstart.md`](docs/quickstart.md).

## CLI

```bash
# Single PDF extraction (full-provenance JSON or auditable Markdown)
econ-pdf extract examples/example_paper.pdf --json
econ-pdf extract examples/example_paper.pdf --markdown --output-dir out/
econ-pdf extract paper.pdf --json --ocr glm_ocr --ocr-policy fallback

# Batch report across local papers.yaml (or ad-hoc --pdf)
econ-pdf report --paper all --reports-dir reports/tables --format both
econ-pdf report --pdf examples/example_paper.pdf --reports-dir reports/tables

# Draft MaRCo@BIS-style paper targets YAML
econ-pdf targets examples/example_paper.pdf --reports-dir reports/tables

# Offline local evaluation against reference claim YAMLs
econ-pdf eval --refs-dir /path/to/refs --config references/configs/papers.yaml --output-dir /path/to/eval
```

### Pluggable OCR Fallback

Embedded-text PDFs are processed directly via PyMuPDF (`--ocr none`, default). For degraded multi-line display equations (big operators, radicals, private-use case braces, stacked fractions), targeted display-region cropping can be routed to an OpenAI-compatible vLLM **GLM-OCR** endpoint (`--ocr glm_ocr --ocr-policy fallback`) using Python's stdlib HTTP client with zero extra dependencies:

```bash
export VLLM_BASE_URL="http://your-vllm-host:8000"
export VLLM_API_KEY="optional-token"
econ-pdf extract paper.pdf --json --ocr glm_ocr --ocr-policy fallback
```

## Quickstart (CLI)

Install from source (`uv sync`), then run on a committed sample PDF:

```console
$ uv run econ-pdf extract examples/example_paper.pdf
File: examples/example_paper.pdf
Pages: 2 | Sections: 3
Claims (5):
  - [CLM-001 P1] (1 Introduction) [own] We find that monetary policy surprises reduce industrial production by 3.2 percent on impact.
  ...
```

Shortest Python path and where files land: [`docs/quickstart.md`](docs/quickstart.md). An executed Python API demo lives in [`notebooks/quickstart.ipynb`](notebooks/quickstart.ipynb).

## Docs

Short guides describing the code in this repo (bullets and code blocks, no fluff):

- [`docs/quickstart.md`](docs/quickstart.md) — shortest working run (CLI and Python) and what lands where
- [`docs/architecture.md`](docs/architecture.md) — package tree, pipeline diagram, data model
- [`docs/usage.md`](docs/usage.md) — install, CLI commands, Python API, output files, config files
- [`docs/claims.md`](docs/claims.md) — claim types, cue patterns, attribution, section-role filtering, dedup, refiner hook
- [`docs/nlp.md`](docs/nlp.md) — optional `[nlp]` spaCy extra, `SpacyClaimFilter`, causal triples, `sm`/`lg`/`trf` trade-offs
- [`docs/math.md`](docs/math.md) — display equations, `needs_ocr` scoring, logic kinds, symbol definitions, linking
- [`docs/ocr.md`](docs/ocr.md) — OCR backends, `VLLM_BASE_URL`, policies, how to add a backend
- [`docs/evaluation.md`](docs/evaluation.md) — offline eval against local reference claim YAMLs
- [`docs/benchmark.md`](docs/benchmark.md) — public benchmark (4 working papers, 40 AI-labeled claims, 3 papers held out): download PDFs, run `econ-pdf eval`, current results
- [`docs/citations.md`](docs/citations.md) — citations and PDF URLs for the benchmark papers
- [`docs/roadmap.md`](docs/roadmap.md) — generalization findings, spaCy trade-offs, planned LLM refiner and vocabulary directions

Also see [`notebooks/quickstart.ipynb`](notebooks/quickstart.ipynb) for an end-to-end Python API demo on the committed sample PDFs.

## Architecture

| Subpackage | Key Classes | Responsibility |
|---|---|---|
| `core/` | `ConfigLoader`, `Document`, `Claim`, `MathObject`, `SymbolDef`, `ExtractionResult` | Core paths, YAML config loading, full-provenance dataclasses & enums |
| `layout/` | `PdfReader`, `LayoutCleaner`, `SectionBuilder`, `SentenceSegmenter` | PyMuPDF ingestion, margin/footnote/table/caption filtering, front-matter dedup, true-page sentence segmentation |
| `claims/` | `ClaimClassifier`, `AttributionClassifier`, `ClaimDeduplicator`, `ClaimRefiner`, `ClaimExtractor` | 8-category taxonomy, significance guards, own/literature/comparison attribution, paraphrase dedup |
| `nlp/` | `SpacyModelLoader`, `SpacyClaimFilter`, `CausalTripleExtractor` | Optional `[nlp]` spaCy dependency filter refiner and all-sentences `(cause, direction, outcome)` triple extraction |
| `math_extract/` | `DisplayEquationDetector`, `LogicExtractor`, `SymbolDefinitionExtractor`, `MathExtractor` | Right-margin tags, baseline sub/sup clustering, `needs_ocr` scoring, assumptions/algorithms/eval formulas, symbol epilogues |
| `linking/` | `CrossReferenceLinker` | Bidirectional `Claim` <-> `MathObject` <-> `SymbolDef` edges (explicit refs, named metrics, symbols) |
| `ocr/` | `OcrBackend`, `NullOcrBackend`, `GlmOcrBackend`, `RegionCropper`, `OcrBackendFactory` | Display-bbox cropping (tag-excluded) and stdlib vLLM GLM-OCR client |
| `targets/` | `StatisticExtractor`, `TargetDrafter` | Clean-sentence statistic extraction and MaRCo@BIS-style draft target YAML |
| `reporting/` | `JsonReportWriter`, `MarkdownReportWriter`, `BatchSummaryWriter` | Full-provenance JSON and human-auditable Markdown reports |
| `pipeline/` | `ExtractionPipeline`, `BatchPipeline` | Single-PDF and multi-paper orchestration |
| `eval/` | `ClaimEvaluator` | Offline local benchmark against reference claim YAMLs |

## Configuration & Paper Registry

Configuration files live under `references/`:

- `references/configs/extraction.yaml` — layout thresholds, section role patterns, dedup parameters, math and OCR crop settings
- `references/configs/claim_patterns.yaml` — 8-category claim regexes, significance context guards, and attribution rules
- `references/configs/nlp_patterns.yaml` — spaCy claim-verb whitelist, roadmap filter verbs, and directional causal lemmas
- `references/configs/math_patterns.yaml` — display tag regex, math-kind cues, prose logic patterns, degradation signals, named metrics
- `references/configs/target_patterns.yaml` — statistic regexes and unit mappings
- `references/configs/papers.example.yaml` — committed public/synthetic paper registry example (copy to gitignored `references/configs/papers.yaml` for local manuscripts)
- `references/dictionaries/` — `greek_to_latex.py`, `math_fonts.py`, `abbreviations.py`, `macro_outcomes.py`

Public sample PDFs include `examples/example_paper.pdf` (regenerated via `uv run python examples/make_example_paper.py`) and public FRBSF working papers under `examples/papers/`.

## Development

```bash
uv sync
uv run ruff check
uv run pytest -q
```

## License

MIT
