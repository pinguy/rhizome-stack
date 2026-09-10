# Rhizome memory ranker

FAISS first retrieves a broad semantic candidate set. The server then blends
vector similarity with exact lexical overlap before applying Pingu's usefulness
model:

```text
blended_semantic = (0.75 * vector_similarity) + (0.25 * lexical_overlap)

usefulness = (alpha * retrieval_frequency)
           + (beta  * recency)
           + (gamma * blended_semantic)
           + (delta * manual_adjustment)
```

The defaults are `alpha=0.05`, `beta=0.05`, `gamma=0.85`, and `delta=0.05`.
Lexical overlap protects exact names, dates, numbers, and paths that compact
sentence embeddings can blur. Frequency and recency are deliberately
tie-breakers rather than independent substitutes for relevance.
Retrieval frequency counts explicit full-memory `get` operations, uses `log1p`,
and saturates at 20 retrievals. Merely appearing in search is recorded as an
`impression` for diagnostics and does not feed back into ranking. Search results
also collapse candidates whose first 96 normalized word tokens overlap by at
least 85 percent before truncation to the requested result count. This catches
duplicated exports and book title pages whose citation prefixes or later text
differ. Recency has a 120-day half-life. Relevance remains dominant because use
and freshness are evidence of usefulness, not proof.

State is written atomically to `RhizomeML/memory_usefulness.json`. Optional
manual corrections live in `RhizomeML/memory_manual_adjustments.json`:

```json
{
  "123": 1.0,
  "456": -1.0
}
```

Keys are FAISS row IDs. Values are clamped to `-1..1`; zero is neutral,
positive values boost, and negative values suppress. The paths, weights,
half-life, lexical share, and saturation point can be overridden with the
`RHIZOME_*` environment variables declared in `rhizome_memory_server.py`.

This is a practical weighted ranking heuristic inspired by the Bayesian
intuition `P(useful | frequency) ∝ P(frequency | useful) P(useful)`. It is not
a calibrated probability model and does not claim retrieval frequency alone
proves usefulness.
