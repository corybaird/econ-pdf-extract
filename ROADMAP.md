# Roadmap

Status: `0.1.0` beta, rule-based extraction with full provenance. Research notes behind these items: [docs/roadmap.md](docs/roadmap.md)

## 0.1.x - hardening
- Publish to PyPI
- Unnumbered subsection detection and hierarchical section attachment
- Field vocabularies beyond macro (finance, labor, public, trade, IO)
- Larger public benchmark with human-checked labels

## 0.2 - causal knowledge graph (in development)
- Per-paper causal edge table: cause, effect, sign, effect size, significance, method, tentativeness
- Every edge keeps the claim's page, section and verbatim quote
- Optional local-model backend (Ollama) for edge fields, rules keep choosing sentences and provenance
- Edge evaluation (`econ-pdf eval --edges`) with recall, precision, sign and method accuracy
- Ships once edge scores clear a set bar on held-out papers

## 0.3 - linking evidence to replication
- Claim to table cell linking
- Claim checks drafted for [reproducible-econ](https://github.com/corybaird/reproducible-econ) (`claims:` entries with coef, tolerance, p-value)
- Edges marked verified when a replication claim check passes
- Draft-to-draft claim diff across paper versions

## Principles
- Provenance first: models may fill fields, never page, section, bbox or quote
- Deterministic by default, model backends opt-in and local-first
- Benchmarks reported with held-out splits
