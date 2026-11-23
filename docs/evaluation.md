# Evaluation

`econ-pdf eval` runs an offline local benchmark (`ClaimEvaluator`, `src/econ_pdf_extract/eval/evaluator.py`): it re-runs the full extraction pipeline for each referenced paper and matches reference claims against extracted ones.

## Reference YAML format

One file per paper in `--refs-dir`, named `ref_claims_<paper_id>.yaml` (`<paper_id>` must equal the registry `id`, e.g. `ref_claims_example_paper.yaml`). It is a YAML list; each row needs `quote`, `page`, and optionally `section` and `type`:

```yaml
# ref_claims_example_paper.yaml — hand-written for examples/example_paper.pdf
- page: 1
  section: "1 Introduction"
  type: magnitude
  quote: We find that monetary policy surprises reduce industrial production by 3.2 percent on impact.
- page: 1
  section: "1 Introduction"
  type: significance
  quote: The estimate on the policy surprise is -0.42 and is significant at the one percent level (p < 0.01).
```

The paper registry comes from `--config` (your gitignored local `papers.yaml`); papers without a reference file are skipped with a warning.

## Matching

Text similarity between each reference quote and extracted claims uses `SequenceMatcher` ratio (threshold `0.72`) or token F1 on lowercased, ligature-normalized text (threshold `0.75`); best candidate wins with a small page match tie-breaker. Only non-literature claims (`attribution != literature`) count.

## Metrics

Reported per paper and in aggregate (`summary["aggregate"]`), both on console and in the outputs:

| Metric | Definition |
|---|---|
| `recall` | matched references / total references (`tp`) |
| `precision` | distinct canonical claims matched / canonical claims extracted |
| `volume_ratio` | canonical claims extracted / references (over- vs under-extraction) |
| `exact_page_accuracy` | matches where `claim.page <= ref.page <= claim.page_end` (or via `also_seen_on`) / TP |
| `strict_section_accuracy` | matches where the normalized extracted heading equals the reference heading (or its parenthetical sub-heading) / TP |
| `role_section_accuracy` | strict match or `SectionRole` hint alignment with the reference section / TP |

Real run on the two-row example above:

```console
$ uv run econ-pdf eval --refs-dir /tmp/eval-demo --config /tmp/eval-demo/papers.yaml
Eval complete: recall=1.000 (2/2), precision=0.400 (2/5), exact_page=1.000, strict_section=1.000, role_section=1.000
```

## Outputs and scope

With `--output-dir`, two timestamped files are written: `eval_claims_<ts>.json` (per-paper metrics, aggregate, matched details, missed references) and `eval_claims_<ts>.md` (single table). Diagnostics include math objects, symbols, links, and attribution counts.

Reference YAMLs and the evaluation corpus are deliberately **local**: reference files live in `--refs-dir`, paper paths in your gitignored `papers.yaml`. Nothing under `docs/` or `tests/` references private manuscripts.
