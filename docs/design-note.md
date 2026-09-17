# Technical design note

## Problem and boundary

Health-claim decisions are high-impact and policy-specific. This MVP treats the policy as authoritative and does not use external insurance or medical knowledge. It returns an abstention instead of filling gaps with plausible language.

## Design

Five purpose-specific components pass structured state: case analysis finds missing facts and questions; policy evidence retrieves traceable clauses; coverage/exclusion specializes in evidence interpretation; decision selects a contract status; validation independently checks citation support. This is intentionally not five versions of one prompt. The current MVP is deterministic so it can be run and audited without credentials; an LLM can be introduced only behind schema validation at the case-analysis/evidence-synthesis boundaries.

The indexer chunks semantic policy units by page/heading/paragraph. It stores source, page, heading, and deterministic chunk ID. Hybrid retrieval combines a dense hashed-vector fallback and custom BM25. RRF reduces a single retriever’s bias, then the post-fusion reranker uses query-token overlap. Scores remain on citations so a reviewer can see how evidence was found. The interfaces make sentence-transformer + FAISS and a BGE cross-encoder drop-in production upgrades.

## Reliability, limits, and deployment

The decision agent cannot decide when required fields are absent. The validation agent downgrades unsupported material conclusions to `NEEDS_REVIEW`, with an explicit reviewer action. API schemas reject malformed numeric values; policy parsing failures surface as unavailable analysis rather than invented decisions. Trace events expose only agent names, timing, status, and concise summaries.

Known limitations: the offline dense fallback is not equivalent to a trained embedding model and demo policy/cases are placeholders because no source package was present. Actual rule interpretation must be reviewed against the supplied PDF; the example decision logic is deliberately narrow. Production should add a real embedding/reranker model, persistent vector store, protected logging, human approval workflow, and environment-specific deployment configuration.

## Failure analysis

1. **Exact waiting-period wording under semantic search.** Initial dense hash ranking can dilute numerical terms. BM25 plus RRF makes `24`, `month`, and `waiting` queryable; retrieval tests verify the clause is surfaced.
2. **Decision without policy support.** A decision layer could output a status on empty retrieval. Validation requires citation IDs and forces `NEEDS_REVIEW` when support is absent.
3. **Missing claim dates.** Applying a waiting-period clause without dates risks a false denial. Case analysis marks dates missing and the final contract instructs the reviewer to obtain them.
