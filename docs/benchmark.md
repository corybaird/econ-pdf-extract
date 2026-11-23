# Public benchmark

This repo ships a public benchmark: 4 working papers with 40 AI-labeled headline claims (10 per paper), not reviewed by a person. The reference claim YAMLs are committed in [`references/benchmarks/`](../references/benchmarks/); the papers are public but redistribution-restricted PDFs, so they are **not** committed — you download them once.

## Papers

| id | paper | year |
|---|---|---|
| `bis1395` | Lombardi, Park & Perez-Cruz, BIS WP 1395 (MaRCo@BIS) | 2026 |
| `bis1141` | Brandao-Marques, Casiraghi, Gelos, Harrison & Kamber, BIS WP 1141 | 2023 |
| `w30555` | Blanco, Ottonello & Ranosova, NBER WP 30555 | 2022 |
| `w31603` | Swanson, NBER WP 31603 | 2023 |

Full citations and PDF URLs: [`docs/citations.md`](citations.md).

## One-time setup: download the PDFs

From the repo root (PDFs land in `examples/papers/`, which is gitignore):

```bash
mkdir -p examples/papers
curl -sL -o examples/papers/bis1395.pdf "https://www.bis.org/publications/working-paper-1395-marcobis-ai-agentic-econometric-analysis-central-bankers.pdf"
curl -sL -o examples/papers/bis1141.pdf "https://www.bis.org/publications/working-paper-1141-high-debt-constraining-monetary-policy-evidence-inflation-expectations.pdf"
curl -sL -o examples/papers/w30555.pdf "https://www.nber.org/system/files/working_papers/w30555/w30555.pdf"
curl -sL -o examples/papers/w31603.pdf "https://www.nber.org/system/files/working_papers/w31603/w31603.pdf"
```

Expect a warning that `examples/papers/` is gitignored — that is intended. Verify SHA-256 against [`references/benchmarks/papers.yaml`](../references/benchmarks/papers.yaml):

```bash
sha256sum examples/papers/bis1395.pdf examples/papers/bis1141.pdf examples/papers/w30555.pdf examples/papers/w31603.pdf
```

## Run the eval

One command (takes a few minutes; it re-runs the full extraction pipeline per paper):

```bash
uv run --inexact econ-pdf eval \
  --refs-dir references/benchmarks \
  --config references/benchmarks/papers.yaml \
  --output-dir data/eval
```

JSON and Markdown reports with per-paper metrics, matched quotes and missed references are written to the timestamped files under `data/eval/`.

## Current results (2026-11-21, reference config as committed)

| paper | recall | precision | exact page | strict section |
|---|---|---|---|---|
| bis1395 | 0.900 (9/10) | 0.391 | 1.000 | 0.889 |
| bis1141 | 0.800 (8/10) | 0.190 | 1.000 | 0.250 |
| w30555 | 0.800 (8/10) | 0.333 | 1.000 | 1.000 |
| w31603 | 0.600 (6/10) | 0.194 | 1.000 | 0.500 |
| **total, all 4** | **0.775 (31/40)** | **0.258** | **1.000** | **0.677** |
| **total, held out (without bis1395)** | **0.733 (22/30)** | **0.227** | | |

The claim cues were widened after seeing misses on `bis1395`, so only the other three papers are held out. Quote 22/30, not 31/40, as the held-out recall.

Metric definitions: [`docs/evaluation.md`](evaluation.md).

**About 1 in 4 extracted claims matches a reference claim. Unmatched claims are not necessarily wrong, since only 10 per paper are labeled. The extracted claim lists are draft over-extraction and require human review before any use — never treat them as a reliable summary of a paper.** A held-out recall of 0.733 means roughly 1 in 4 reference claims still gets missed by regex cue matching; the pipeline is not model-driven and has no reasoning over candidate claims.

Rerunning with the exact commands above reproduces these numbers modulo claim-id ordering in the JSON reports.
