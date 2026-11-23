# Usage

## Install from source

```bash
git clone https://github.com/corybaird/econ-pdf-extract.git
cd econ-pdf-extract
uv sync
```

Requires Python and PyMuPDF as declared in `pyproject.toml`. The `econ-pdf` console script is registered in `pyproject.toml` (`econ-pdf = "econ_pdf_extract.cli:entry"`).

## CLI

Global flags: `--verbose` (info logging), `--quiet` (suppress warnings).

### `econ-pdf extract`

Extract structured content from a single PDF.

```
econ-pdf extract PDF
  --json                      emit full-provenance JSON
  --markdown                  auditable Markdown report
  --output-dir DIR            timestamped files (default: print to stdout)
  --ocr {none,glm_ocr}        OCR backend (default: none)
  --ocr-policy {none,fallback,all_displays}
                              targeted OCR policy (default: fallback)
  --include-appendix          include Appendix sections in claim extraction
  --include-literature/--no-include-literature
                              literature claims in JSON output (default: include)
  --include-duplicates/--no-include-duplicates
                              near-duplicate claims in output (default: include)
```

With no flags it prints a concise human summary instead:

```console
$ uv run econ-pdf extract examples/example_paper.pdf
File: examples/example_paper.pdf
Pages: 2 | Sections: 3
Claims (5):
  - [CLM-001 P1] (1 Introduction) [own] We find that monetary policy surprises reduce industrial production by 3.2 percent on impact.
  ...
Math/Logic (0):
```

With `--output-dir` both writers run unless `--json`/`--markdown` narrows it. With `--json`/`--markdown` alone, output goes to stdout.

### `econ-pdf report`

Write JSON/Markdown reports for configured papers.

```
econ-pdf report
  --paper ID|all              paper id from papers.yaml (default: all)
  --pdf PATH                  ad-hoc PDF overriding --paper
  --config PATH               papers.yaml path
  --reports-dir DIR           output directory (default: reports/tables)
  --format {json,markdown,both}  (default: both)
  --ocr / --ocr-policy / --include-appendix   as in extract
```

```console
$ uv run econ-pdf report --pdf examples/example_paper.pdf --reports-dir reports/tables
Done: 5 claims, 0 math objects across 1 paper(s).
```

### `econ-pdf targets`

Draft MaRCo@BIS-style target YAML linking claims to extracted statistics.

```
econ-pdf targets [PDF]
  --paper ID|all              (default: all; omit the PDF argument)
  --config PATH               papers.yaml path
  --reports-dir DIR           (default: reports/tables)
  --include-literature        include literature claims
  --include-duplicates        include duplicate claims
```

```console
$ uv run econ-pdf targets examples/example_paper.pdf --reports-dir reports/tables
[*] example_paper: 5 claims, 8 statistics -> reports/tables/draft_paper_targets_example_paper_<ts>.yaml
```

### `econ-pdf eval`

Offline evaluation against local reference claim YAMLs. See [evaluation.md](evaluation.md).

```
econ-pdf eval
  --refs-dir DIR              required, holds ref_claims_<paper_id>.yaml files
  --config PATH               local papers.yaml path
  --output-dir DIR            timestamped eval reports
  --paper ID|all              (default: all)
```

## Python API

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

`ExtractionPipeline` accepts `pdf_path`, `paper` (`PaperMetadata`, optional), `ocr_backend`, `ocr_policy`, `include_appendix`, `refiner`, `config_dir`.

## Output files

All writers create the output directory and stamp timestamps (`%Y%m%d_%H%M%S`):

| Writer | File |
|---|---|
| `JsonReportWriter` | `extracted_<paper_id>_<ts>.json` |
| `MarkdownReportWriter` | `extracted_report_<paper_id>_<ts>.md` |
| `BatchSummaryWriter` (multi-paper `report`) | `extracted_summary_all_<ts>.md` |
| `TargetDrafter` | `draft_paper_targets_<paper_id>_<ts>.yaml` |
| `ClaimEvaluator` | `eval_claims_<ts>.json` + `eval_claims_<ts>.md` |

## Configuration

YAML configs live under `references/configs/` in a checkout and ship inside the package as `econ_pdf_extract/_references/configs/`. `ConfigLoader` uses the checkout when there is one. In an installed package, relative paper paths resolve from the current directory and the paper registry is passed with `--config`:

| File | Contents |
|---|---|
| `extraction.yaml` | layout thresholds (header/footer margins, footnotes, tables), section role patterns, claim eligibility, dedup parameters, math display thresholds, OCR settings |
| `claim_patterns.yaml` | 8-category claim regexes, `general_finding_patterns`, `significance_context_patterns`, `exclude_patterns`, `attribution_patterns` |
| `math_patterns.yaml` | `equation_tag_regex`, `cross_ref_patterns`, `math_kind_cues`, `prose_logic_patterns`, `symbol_definition_patterns`, `degradation_patterns`, `named_metrics` |
| `target_patterns.yaml` | `statistic_patterns` (estimate, r_squared, p_value, t_stat, sample_size, percent, confidence_interval) and `units` |

### Paper registry: `papers.yaml` vs `papers.example.yaml`

`references/configs/papers.yaml` is **gitignored** and holds local paper paths; `papers.example.yaml` is the committed example. Commands that take `--config`/`--paper` load `papers.yaml`; if missing, `ConfigLoader.load_papers()` raises with a pointer to copy the example:

```console
FileNotFoundError: Paper registry not found at .../papers.yaml.
Copy .../papers.example.yaml to .../papers.yaml or pass --config.
```

```yaml
# papers.example.yaml (excerpt)
papers:
  - id: example
    title: "The Output Response to Monetary Policy Shocks: A Direct Projection Approach"
    draft_pdf: examples/example_paper.pdf
```

Each entry needs `id` and `draft_pdf` (or `pdf_path`); `authors`, `title`, `journal` are optional. Relative paths resolve against `PROJECT_ROOT`.

See [ocr.md](ocr.md) for backend setup and [evaluation.md](evaluation.md) for eval inputs.
