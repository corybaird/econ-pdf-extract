# Math extraction

`MathExtractor` (`src/econ_pdf_extract/math_extract/`) produces `MathObject`s (display equations and prose logic) plus `SymbolDef`s. Patterns in `references/configs/math_patterns.yaml`, thresholds in `extraction.yaml` under `math:`.

## Display equation detection

`DisplayEquationDetector` builds logical rows per page by clustering text spans on vertical baseline centers (tolerance `baseline_cluster_ratio` × body font size), then uses two anchors:

1. **Right-margin tag (Pass 1)** — a row whose last span ends right of `tag_min_x1_ratio` × page width and matches `equation_tag_regex` (`\(((?:[1-9]\d*|[A-Z])(?:\.\d+)*)\)\s*$`) anchors an equation, e.g. `(3)`. Year-like numbers (1950–2035) and prose with ≥5 English words and no math font/operators are rejected. The tag is trimmed from the body and stored in `MathObject.tag` / `tag_bbox`.
2. **Unnumbered centered display (Pass 2)** — math-font rows with an operator (`=≈∼≤≥∈∑∏∫→<>±×`), few English words (`max_english_words_in_display`), indented beyond the body left edge + `unnumbered_indent_pt`, with vertical gaps ≥ `unnumbered_gap_ratio` × body size.

Multiline equations expand bidirectionally while the vertical gap stays under `multiline_gap_ratio` × body size and neighbour rows look like math continuations (math/large-operator fonts, operators, or short indented lines; prose starters like "where ...", "The", "Table ..." stop the expansion).

Equations are sorted by page/y/x and renumbered `EQ-001`, `EQ-002`, ... Objects keep `raw_text` (extracted PDF text), `context_before` / `context_after` (2 rows above / 3 below), and full provenance.

Real output from the committed FRBSF PDF (from `econ-pdf extract examples/papers/shapiro_2017-01_sentiment.pdf --markdown`):

| ID | Kind | Tag | Content |
|---|---|---|---|
| `EQ-002` | `display_equation` | (2) | S(w) = PMI(w, positive) −PMI(w, negative), |
| `EQ-006` | `estimation_problem` | (6) | βˆ = arg min ... + λX\|bj\| (LASSO) |

## needs_ocr scoring

The detector scores text-layer degradation per equation into `ocr_reasons` (`math_patterns.yaml` → `degradation_patterns`, plus geometry checks); `needs_ocr` is true when any reason fires:

- `big_op_font` — large-operator font spans
- `private_use_glyph` — private-use-area or control characters in the raw text
- `radical_fragment` — flattened radical patterns (`radical_fragment`)
- `flattened_big_op` — big operators flattened to Z/X/P glyphs (`flattened_big_op`)
- `stacked_fraction` — short horizontal rule inside the bbox (fraction bar)
- `tall_multiline` — bbox taller than `tall_multiline_ratio` × body size
- `accent_garble` — garbled accents/exponents (`accent_garble`)

Rationale: degraded displays extract as garbled `raw_text`; OCR can recover `latex`. See [ocr.md](ocr.md) for the targeted OCR policy.

## Logic kinds

`MathKind` (`core/models.py`) has 8 values. `LogicExtractor` classifies in `math_extract/logic.py`:

- Display equations are promoted from `display_equation` by cues matched against `context_before + raw_text` (`math_patterns.yaml` → `math_kind_cues`):
  - `estimation_problem` — "arg min", "subject to" (checked first)
  - `evaluation_formula` — "R2_oos", "CRPS", "DM test" (equations defining a metric)
  - `model_specification` — "takes the form", "is given by"
- Prose logic is extracted from section prose blocks in non-skipped sections (`front_matter` and `references` are skipped):
  - `ALGORITHM` (`ALG-001` ...) — "Algorithm" headings, optionally absorbing numbered/bulleted step blocks; a whole section titled like "N.M Suggested Algorithm" also counts
  - `ASSUMPTION` (`ASM-...`), `PROPOSITION` (`PRP-...`, also Theorem/Lemma/Corollary), `DEFINITION` (`DEF-...`) — block-initial heading patterns from `prose_logic_patterns`

## Symbol definitions

`SymbolDefinitionExtractor` (`math_extract/symbols.py`) parses `SymbolDef`s from two sources:

1. **Equation epilogues** — `context_after` matched with the forward verb pattern ("X denotes/represents/indicates ...") and `context_before` with the reverse pattern ("we denote Y as X"); regexes in `symbol_definition_patterns`.
2. **Prose sentences** — sentences starting "In (3), ..." are attached to the equation with tag `(3)`; sentences containing "where" attach to the nearest display above on the same page (within 120pt).

Symbol tokens are validated against sentence math tokens or math-like syntax (subscripts `_`, superscripts `^`, backslashes, digits, Greek letters); bare common words (a curated `_NON_SYMBOL_WORDS` set) are rejected. `normalize_symbol()` maps Greek characters to LaTeX macro names (`references/dictionaries/greek_to_latex.py`) and produces a case/spacing-insensitive matching key. IDs are `SYM-001`, ... Definitions also land in the Markdown report's Symbol Glossary (e.g. from the committed FRBSF PDF: `x` — "variables of interest", defined in an appendix LASSO equation).

## Equation–symbol–claim linking

`CrossReferenceLinker` (`linking/linker.py`) builds `CrossRefEdge`s between claims, equations, and symbols, updating `claim.linked_equation_ids`, `claim.linked_symbols`, and `math_object.linked_claim_ids`:

1. **`explicit_ref`** — claim text citing equation tags via `cross_ref_patterns` ("Equation (3)", "using (2)", "see (1) and (4)"); anaphoric claim starts ("This", "These", "It", "Such") are also scanned against the preceding sentence.
2. **`named_metric`** — claim mentioning a metric named in `named_metrics` (R2_oos, CER, CRPS, Sharpe, ...) links to equations classified `evaluation_formula` for that metric.
3. **`symbol`** — claim text sharing a normalized math token or a linkable symbol (subscripted/Greek/multi-char-uppercase; bare single ASCII letters are excluded) links to the symbol's defining equation.

Edges are deduplicated by `(claim_id, math_id, via, matched_token)`.
