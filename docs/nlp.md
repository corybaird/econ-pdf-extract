# Optional NLP (spaCy)

Optional dependency-parsing features live in `src/econ_pdf_extract/nlp/` behind the `[nlp]` extra (`spacy>=3.8,<4`). The core library stays importable and deterministic without spaCy installed.

## Install

Install the optional extra, then install a spaCy English model separately (models are not package dependencies):

```bash
# uv (use --inexact in shared environments)
uv sync --extra nlp --inexact
uv run python -m spacy download en_core_web_sm

# pip
pip install "econ-pdf-extract[nlp]"
python -m spacy download en_core_web_sm
```

For ephemeral evaluation runs without modifying the environment, pass a model wheel directly with `uv run`:

```bash
uv run --extra nlp \
  --with "en_core_web_sm @ https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl" \
  econ-pdf extract examples/example_paper.pdf --spacy-filter --causal-triples --json
```

If spaCy or the configured model is missing, `SpacyModelLoader` raises `SpacyUnavailableError` with the exact install command.

## Configuration

- `references/configs/extraction.yaml` under `nlp:`:
  - `spacy_model`: default `en_core_web_sm`
  - `enable_causal_triples`: default `false`
- `references/configs/nlp_patterns.yaml`:
  - `claim_verbs` — allowed main-verb lemmas for `SpacyClaimFilter`
  - `roadmap_verbs` and `roadmap_patterns` — structural outline sentences dropped even if a regex cue matched
  - `direction_lemmas` and `intransitive_direction_lemmas` — directional verb/noun lemmas for `CausalTripleExtractor`

## `SpacyClaimFilter` (refiner hook)

`SpacyClaimFilter` subclasses `ClaimRefiner` (`claims/refiner.py`) and plugs into `ExtractionPipeline(..., refiner=...)` with no pipeline rewrite.

Rules applied to each regex-extracted claim candidate:

1. Require a finite main verb, with three dependency-parse fixes over a naive `ROOT`-tag check:
   - Accept `VB` under an auxiliary or negation (e.g., `"do not predict"`, `"can improve"`).
   - Accept `VBN` with a finite auxiliary or passive construction (e.g., `"is rejected"`, `"has shown"`, `"is preferred"`).
   - Fall back to the nearest finite verb when `ROOT` is parsed as a noun or bare participle (e.g., fronted prepositional phrases like `"In the second sample the larger specification has smaller errors"`), and inspect finite `ccomp`/`conj`/`parataxis` children.
2. Drop structural roadmap sentences (`section` + `roadmap_verbs`, or `"paper/study is organized"`).
3. Keep the claim when the resolved verb lemma is in `claim_verbs` (or the sentence contains a directional lemma from `direction_lemmas`).
4. Reconcile duplicates: if a canonical claim is dropped while a duplicate survives, promote the first surviving duplicate to canonical so no dangling `duplicate_of` pointers remain.

Python API:

```python
from econ_pdf_extract import ExtractionPipeline, SpacyClaimFilter

result = ExtractionPipeline(
    "examples/example_paper.pdf",
    refiner=SpacyClaimFilter(model_name="en_core_web_sm"),
).run()
```

CLI:

```bash
econ-pdf extract examples/example_paper.pdf --spacy-filter --spacy-model en_core_web_sm --markdown
```

## `CausalTripleExtractor` (all-sentences stage)

`CausalTripleExtractor` (`nlp/triples.py`) runs as a separate optional stage over all eligible sentences (not just regex-matched claim candidates) and emits `(cause, direction, outcome, sentence, page, section)` records into `ExtractionResult.causal_triples`, JSON output, and a `## Causal Triples` Markdown section. It never rewrites `Claim.claim_types`.

- Handles transitive active verbs (`"tightening reduces output"`), passive constructions (`"expectations are raised by debt surprises"`), intransitive directional verbs (`"commodity prices fall"`), and nominalized direction nouns (`"an increase in unemployment"`).
- When both `SpacyClaimFilter` and `extract_causal_triples=True` are enabled with the same model, `ExtractionPipeline` shares one loaded spaCy instance across both stages.

Python API and CLI:

```python
from econ_pdf_extract import ExtractionPipeline, SpacyClaimFilter

result = ExtractionPipeline(
    "examples/example_paper.pdf",
    refiner=SpacyClaimFilter(),
    extract_causal_triples=True,
).run()
for t in result.causal_triples:
    print(t.triple_id, t.page, t.section, t.cause, "->", t.direction, "->", t.outcome)
```

```bash
econ-pdf extract examples/example_paper.pdf --spacy-filter --causal-triples --json
```

## Model comparison (`sm` vs `lg` vs `trf`)

Measured on CPU across the public 4-paper benchmark (40 AI-labeled headline claims, 134 pages: BIS WP 1395, BIS WP 1141, NBER WP 30555, NBER WP 31603; BIS WP 1395 informed the claim cues, so it is not held out, and without it the regex-only recall is 22/30) and the 2 committed FRBSF working papers (16 refs, 90 pages), using the widened claim cues:

| Model | Wheel size | Load (s) | 4-paper recall | 4-paper prec | 4-paper vol | Filter (s/page) | Triples (count, s/page) | FRBSF recall / prec |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Regex only (no spaCy) | — | — | 0.775 (31/40) | 0.258 | 3.00x | — | — | 0.938 / 0.250 |
| `en_core_web_sm` | 15 MB | 0.40 | 0.725 (29/40) | 0.264 | 2.75x | 0.0018 | 184 (0.0120) | 0.875 / 0.259 |
| `en_core_web_lg` | 382 MB | 1.07 | 0.750 (30/40) | 0.268 | 2.80x | 0.0020 | 179 (0.0136) | 0.812 / 0.250 |
| `en_core_web_trf` | 436 MB + torch | 5.90 | 0.775 (31/40) | 0.274 | 2.83x | 0.0350 | 188 (0.2731) | 0.875 / 0.250 |

Trade-offs:

- **`en_core_web_sm` (default, recommended for most runs):** 15 MB download, sub-millisecond per-page filtering (`0.0007–0.0018 s/page`), and fast all-sentences triple extraction (`0.0033–0.0120 s/page`). Cuts noise while keeping recall high across both forecasting and macro papers.
- **`en_core_web_lg`:** ~25x larger wheel with static word vectors (unused by dependency rules). Marginally higher 4-paper recall/precision than `sm`, slightly lower recall on the FRBSF papers, and nearly identical CPU speed (`0.0008–0.0020 s/page` filter).
- **`en_core_web_trf`:** Best parse fidelity on unseen macro/econometrics prose — preserves full `0.775` 4-paper recall with the highest precision (`0.274`) — at the cost of PyTorch + `spacy[transformers]` dependencies and ~18–23x slower CPU throughput (`0.012–0.035 s/page` for claim filtering; `0.159–0.273 s/page` for all-sentences causal triples). Best suited for filtering claim candidates on small batches or GPU hosts rather than all-sentences CPU scans over large corpora.
