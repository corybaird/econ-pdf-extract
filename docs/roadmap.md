# Roadmap

This note documents the empirical motivation behind the NLP refiner, wider claim cues, and causal triple stage, and outlines next steps for `econ-pdf-extract`.

## Generalization gap and the BIS WP 1395 benchmark

Early rule development achieved high recall (`>0.93`) on forecasting-oriented empirical papers and two public FRBSF monetary-policy papers, where headline claims rely heavily on forecast-accuracy metrics (`RMSE`, `CRPS`, `R2_oos`, `outperforms`) and standard significance phrasing.

To test out-of-domain generalization without leakage, we evaluated the unmodified regex pipeline on a benchmark of four public working papers (40 AI-labeled headline claims, labeled from full-text PDFs before running any pipeline):

- **Lombardi, Park and Perez-Cruz (2026)**, *"MaRCo@BIS: AI-agentic econometric analysis for central bankers"*, BIS Working Paper No 1395 (10 claims)
- **Brandao-Marques, Casiraghi, Gelos, Harrison and Kamber (2023)**, *"Is high debt constraining monetary policy? Evidence from inflation expectations"*, BIS Working Paper No 1141 (10 claims)
- **Blanco, Ottonello and Ranosova (2022)**, *"The Dynamics of Large Inflation Surges"*, NBER Working Paper 30555 (10 claims)
- **Swanson (2023)**, *"The Macroeconomic Effects of the Federal Reserve's Conventional and Unconventional Monetary Policies"*, NBER Working Paper 31603 (10 claims)

On BIS WP 1395 alone, the forecasting-tuned baseline recalled only **1/10 (0.100)** headline claims, because empirical macro and replication papers express headline results through credible bands (`"90% band ... includes zero"`), instrument strength (`"first-stage F statistic of 24.2"`), replication verification (`"reproduction is exact"`), and general contribution phrasing (`"we document the design, benchmark ..."`). Across all four papers, baseline recall was **0.325 (13/40)** with precision **0.217**.

Widening `references/configs/claim_patterns.yaml` beyond forecasting vocabulary raised four-paper recall from **0.325 to 0.775 (31/40)** and precision from **0.217 to 0.258** — including **9/10 (0.900)** on BIS WP 1395, whose misses motivated the new cues. On the three papers that stayed held out, recall rose from **12/30 (0.400) to 22/30 (0.733)** — while preserving baseline recall on the forecasting development set.

## spaCy findings (what we adopted and what we rejected)

Controlled ablation experiments on dependency parsing (`en_core_web_sm`, `en_core_web_lg`, `en_core_web_trf`) established three clear engineering decisions:

1. **Adopted: `SpacyClaimFilter` with parse fixes (`ClaimRefiner` hook).** A naive finite-`ROOT` filter raises precision and drops equation fragments, table captions, and methodology background, but drops valid claims on negated/auxiliary verbs (`VB`), passives (`VBN` + finite aux), and fronted prepositional phrases (`ROOT` parsed as `NOUN`). Repairing those three parse patterns recovered nearly all lost recall while retaining precision gains (`0.258 → 0.274` on the four papers with `trf`, `0.264` with `sm`) and reducing candidate volume.
2. **Adopted: `CausalTripleExtractor` as a separate all-sentences stage.** Most directional cause→effect statements in macroeconomics papers carry no forecasting regex cue; parsing all eligible sentences with dependency rules extracts structured `(cause, direction, outcome)` triples that regex patterns miss, while leaving `Claim.claim_types` untouched (rewriting claim types from directional verbs was measured to be a no-op on claim-type accuracy).
3. **Rejected: spaCy dependency attribution as a replacement for regex attribution.** Replacing `AttributionClassifier` with dependency-subject rules regressed attribution accuracy on own-work sentences whose grammatical subject is a result noun or metric (`"the extended model's RMSE"`, `"relative MSE reductions"`) and misclassified uppercase mathematical symbols (`PROPN`) as cited authors. Regex attribution remains the default.

## Next steps

### 1. Optional LLM refiner via `ClaimRefiner`

The same `ClaimRefiner` abstract interface (`src/econ_pdf_extract/claims/refiner.py`) is designed to host an optional LLM-backed refiner (local OpenAI-compatible vLLM/Ollama endpoint or hosted API) without changing the extraction pipeline:

- **Attribution disambiguation:** resolve `unclear` and mixed own-vs-literature sentences where dependency subjects are ambiguous.
- **Precision filtering & deduplication:** distinguish true empirical findings from institutional background and merge cross-section paraphrases that share no lexical overlap.
- **Provenance invariant:** an LLM refiner may filter, re-attribute, or re-type existing `Claim` objects, but must never alter `page`, `page_end`, `section`, `bbox`, or verbatim `quote`.

### 2. Data-driven causal-claims vocabularies across economics fields

`references/dictionaries/macro_outcomes.py` seeds `MACRO_OUTCOME_NOUNS` from the most frequent empirical effect head nouns in macroeconomics working papers (`growth`, `rates`, `inflation`, `output`, `prices`, `consumption`, `employment`, `investment`, `unemployment`, `expectations`, `gdp`, `debt`, `yields`, ...). Extending this pattern to field-specific vocabularies — asset pricing / finance, labor, public economics, international trade, and industrial organization — offers a lightweight, auditable way to improve recall across JEL subfields without brittle hand-written regexes.

### 3. Section-heading generalization

On benchmark papers that use unnumbered thematic headings (e.g., `"Government debt level"`, `"Inflation level"` under a top-level `"Results"` heading), exact page accuracy remained **1.00** while strict section-heading accuracy dropped (`0.68`). Improving unnumbered subsection detection and hierarchical section attachment in `layout/sections.py` is the next highest-leverage layout improvement.
