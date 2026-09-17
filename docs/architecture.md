# Architecture

```mermaid
flowchart LR
  C[Claim JSON] --> A[Case Analysis]
  A --> Q[Structured questions]
  Q --> D[Dense retrieval]
  Q --> B[BM25]
  D --> F[RRF fusion]
  B --> F
  F --> R[Post-fusion reranker]
  R --> E[Policy Evidence]
  E --> X[Coverage & Exclusion]
  X --> Z[Decision]
  Z --> V[Validation]
  V --> O[Cited decision or NEEDS_REVIEW]
```

The evidence layer is independent of policy reasoning. The only durable decision inputs are claim facts, specialist findings, and retrieved citations. The validator requires every material finding to cite retrieved chunks; it downgrades failed outputs to `NEEDS_REVIEW`.
