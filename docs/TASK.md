# Research Candidate Expansion Notes

The app currently keeps the research expansion direct:

- Futu translation may emit `mentioned_stocks` and `theme_candidates`.
- Research candidate generation accepts those candidate codes without StockDB validation gates.
- Research action collection does not enforce candidate-universe membership, evidence thresholds, confidence thresholds, TTL expiry, or max add/remove caps.
- `RESEARCH_*` environment values no longer fall back to legacy `VIEW_*` names.
