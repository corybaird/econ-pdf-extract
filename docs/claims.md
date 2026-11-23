# Claims

`ClaimExtractor` turns cleaned sentences into typed, attributed, deduplicated claims. Source: `src/econ_pdf_extract/claims/`, patterns in `references/configs/claim_patterns.yaml`, thresholds in `extraction.yaml` under `claims:`.

## Claim types

YAML-driven taxonomy in `claim_patterns.yaml` under `claim_types:`. Eight empirical categories in fixed evaluation order (`_TYPE_ORDER` in `claims/classifier.py`), plus a fallback:

| `ClaimType` | Example cues (not the full regexes) |
|---|---|
| `forecast_accuracy` | "outperforms", "lower prediction errors", "most accurate forecasts" |
| `significance` | "statistically significant", "p < 0.01", "DM test", "first-stage F statistic of 24.2", "95% confidence interval excludes zero" |
| `magnitude` | "by 3.2 percent", "by 0.3 p.p.", "ranges from -1 to 2", "R2 of 0.21", "remained between 0.6 and 1.1" |
| `economic_value` | "translates into economic gains", "higher Sharpe ratio" |
| `negative_result` | "fails to outperform", "no significant predictive power", "90% band includes zero", "indistinguishable from zero" |
| `robustness` | "robust to alternative specifications", "qualitative results hold", "reproduction is exact", "matches the original" |
| `mechanism` | "stems from", "driven by", "attributes X to Y", directional verbs over macro outcomes (`references/dictionaries/macro_outcomes.py`) |
| `proposal` | "we propose a new benchmark", "this paper introduces", "we document the design", "we benchmark" |
| `general` (fallback) | "we find that", "our results show that", "this paper documents that" |

A sentence may carry several types; the first match order is `forecast_accuracy > significance > economic_value > negative_result > robustness > mechanism > magnitude > proposal`. Only the top two matched cue strings per type are stored in `Claim.matched_cues`.

Macro-effect mechanism patterns expand `{macro_outcomes}` from `MACRO_OUTCOME_NOUNS` in `references/dictionaries/macro_outcomes.py` (seeded from empirical macroeconomics effect head nouns).

Guards (`claims/classifier.py`):

- `exclude_patterns` — roadmap and section-outline sentences ("Section 3 presents ...", "the paper is organized as follows") produce no claim.
- Significance collision guard — "significant improvements/gains" without statistical context (`significance_context_patterns` like "p-value", "F-statistic", "confidence interval", "null hypothesis", "DM test") is not typed `significance`.
- Bare `magnitude` matches in `data` or `methodology` sections are dropped.

Do not copy regexes from the doc; the source of truth is `claim_patterns.yaml`. Edit that file to add cues.

## Attribution

`AttributionClassifier` (`claims/attribution.py`) labels each claim:

| `Attribution` | Trigger (regexes in `claim_patterns.yaml` → `attribution_patterns`) |
|---|---|
| `literature` | Author-year citation as sentence subject, or "Earlier studies ... show" |
| `comparison` | Citation + comparison cue ("outperforms", "compared to", "consistent with"), or own-marker with citation but no first person |
| `own` | "we find/show/propose", "our main contribution", "this paper" |
| `unclear` | None of the above |

## Section-role (roadmap) filtering

Scanning is restricted by `SectionRole`. Eligible roles come from `extraction.yaml`:

```yaml
claims:
  eligible_roles: [abstract, introduction, results, robustness, conclusion]
  include_appendix_by_default: false
```

- `--include-appendix` (CLI) or `include_appendix_by_default: true` adds `appendix`.
- Duplicate front-matter sections (cover letter / referee report repeated across pages) are always skipped.
- Numbered topical sections with `SectionRole.OTHER` between Introduction and References (e.g. "4 Treasury Yields") are scanned, but `general`-only matches there are dropped to avoid noise.

The full role list lives in `SectionRole` (`core/models.py`): `front_matter`, `abstract`, `introduction`, `methodology`, `data`, `results`, `robustness`, `conclusion`, `appendix`, `references`, `other` — classified by `SectionBuilder` from `extraction.yaml` → `sections.role_patterns`.

## Dedup

`ClaimDeduplicator` (`claims/dedup.py`) clusters near-duplicate paraphrases with Union-Find. Thresholds in `extraction.yaml` → `claims.dedup:`:

```yaml
dedup:
  token_jaccard_threshold: 0.55
  number_overlap_threshold: 0.50
  sequence_ratio_threshold: 0.72
  canonical_role_priority: [results, abstract, conclusion, introduction, robustness, other]
```

Two sentences are near-duplicates when the sequence ratio clears `sequence_ratio_threshold`, or token Jaccard (stopword-filtered) clears `token_jaccard_threshold` and the numeric tokens agree (`number_overlap_threshold`). The canonical representative wins by role priority, then most numbers, longest quote, earliest page. Duplicates get `duplicate_of = <canonical_id>`; the canonical accumulates `also_seen_on` provenance refs.

Filters on output: `--no-include-duplicates` (JSON/Markdown), `--no-include-literature` (JSON), and both flags on `targets`. Eval counts only canonical claims for precision and volume ratio.

## Post-extraction refiner hook

`ClaimExtractor` runs an optional `ClaimRefiner` (`claims/refiner.py`) after deduplication:

```python
class ClaimRefiner(ABC):
    @abstractmethod
    def refine(self, claims: list[Claim], document: Document) -> list[Claim]: ...
```

- Default: `NullClaimRefiner` (deterministic no-op).
- Optional NLP filter: `SpacyClaimFilter` (`nlp/refiner.py`, requires `[nlp]` extra + a spaCy model). Checks finite-verb dependency structure, drops structural roadmaps and non-claim roots against `references/configs/nlp_patterns.yaml`, and reconciles duplicates when a canonical parent is dropped.
- Pass via `ExtractionPipeline(..., refiner=SpacyClaimFilter())` or CLI `--spacy-filter`. See [nlp.md](nlp.md) for setup, parse rules, and model trade-offs, and [roadmap.md](roadmap.md) for planned LLM refiners using the same hook.
