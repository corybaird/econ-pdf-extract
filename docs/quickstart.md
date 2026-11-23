# Quickstart

Shortest working path from clone to extraction results. All commands run from the repo root.

## Install from source

```bash
git clone https://github.com/corybaird/econ-pdf-extract.git
cd econ-pdf-extract
uv sync
```

## CLI: one command, one PDF

```console
$ uv run econ-pdf extract examples/example_paper.pdf
File: examples/example_paper.pdf
Pages: 2 | Sections: 3
Claims (5):
  - [CLM-001 P1] (1 Introduction) [own] We find that monetary policy surprises reduce industrial production by 3.2 percent on impact.
  - [CLM-002 P1] (1 Introduction) [own] The estimate on the policy surprise is -0.42 and is significant at the one percent level (p < 0.01).
  ...
Math/Logic (0):
```

Write files instead (timestamped names in the directory you choose):

```console
$ uv run econ-pdf extract examples/example_paper.pdf --markdown --output-dir out/
Wrote Markdown -> out/extracted_report_example_paper_<ts>.md
$ uv run econ-pdf extract examples/example_paper.pdf --json --output-dir out/
Wrote JSON -> out/extracted_example_paper_<ts>.json
```

## Python: three lines

```python
from econ_pdf_extract import ExtractionPipeline

result = ExtractionPipeline("examples/example_paper.pdf").run()
for claim in result.claims:
    print(claim.claim_id, claim.page, claim.section, claim.attribution.value, claim.quote)
```

`result` is a single `ExtractionResult` holding `claims`, `math_objects`, `symbols`, `links`, `statistics`, and `diagnostics` — see [architecture.md](architecture.md#data-model).

## What to expect

Each claim carries page/section/bbox provenance, claim types, attribution (`own` / `literature` / `comparison` / `unclear`), and the regex cues that matched. Sample PDFs in `examples/`: a synthetic 2-page paper and two committed FRBSF working papers (those contain display equations, symbols, and links). Try:

```console
uv run econ-pdf extract examples/papers/shapiro_2017-01_sentiment.pdf --markdown --output-dir out/
```

## Where files land

| Command | Default location | File |
|---|---|---|
| `extract --output-dir DIR` | `DIR` | `extracted_<paper_id>_<ts>.json`, `extracted_report_<paper_id>_<ts>.md` |
| `report` | `reports/tables/` (`--reports-dir`) | per-paper reports + `extracted_summary_all_<ts>.md` |
| `targets` | `reports/tables/` | `draft_paper_targets_<paper_id>_<ts>.yaml` |
| `eval` | stdout (`--output-dir` for files) | `eval_claims_<ts>.json` / `.md` |

## Next

- [usage.md](usage.md) — full CLI flags, `papers.yaml` registry, config files
- [claims.md](claims.md) / [math.md](math.md) — how extraction decides what is a claim or an equation
- [ocr.md](ocr.md) — OCR fallback for degraded equations
- [evaluation.md](evaluation.md) — benchmark extraction against hand-built reference claims
- [architecture.md](architecture.md) — module map and data model
