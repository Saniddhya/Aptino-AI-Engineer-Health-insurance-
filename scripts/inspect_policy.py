"""Inspect policy content and test retrieval for actual policy concepts."""
import sys
sys.path.insert(0, '.')
import json
from app.retrieval import load_policy, HybridRetriever
"""Inspect policy content and test retrieval for actual policy concepts."""
import json
from app.retrieval import load_policy, HybridRetriever

# Load policy
chunks = load_policy('policy/USGIC-CSCIndividualHealthInsurance_2017-2018.pdf')
print(f"Total chunks: {len(chunks)}")

# Look for key policy concepts
concepts = ['waiting', '24 month', 'exclusion', 'cosmetic', 'experimental', 'domiciliary', 'hospital', 'definition', 'portability', 'room rent', 'sub-limit', 'pre-existing', 'post-hospitalization', 'pre-hospitalisation', 'day care', 'day-care']

print("\n=== CHUNKS MATCHING KEY CONCEPTS ===")
for c in chunks:
    text_lower = c['text'].lower()
    for concept in concepts:
        if concept.lower() in text_lower:
            print(f"\n[{c['chunk_id']}] Section: {c['section']}, Page: {c['page']}")
            print(f"  Concept: '{concept}'")
            print(f"  Text: {c['text'][:200]}...")
            break

# Test retrieval for specific concepts
print("\n\n=== RETRIEVAL TESTS FOR POLICY CONCEPTS ===")
retriever = HybridRetriever(chunks)

test_queries = [
    "waiting period",
    "pre-existing disease",
    "domiciliary treatment",
    "day care treatment",
    "hospital definition",
    "cosmetic treatment exclusion",
    "experimental treatment",
    "portability",
    "room rent limit",
    "sub-limit",
    "post-hospitalization expenses",
    "pre-hospitalization expenses"
]

for query in test_queries:
    print(f"\n--- Query: '{query}' ---")
    results = retriever.search(query, top_n=5, top_k=3)
    for r in results:
        print(f"  {r['chunk_id']} (p{r['page']}, {r['section']})")
        print(f"    dense={r['dense_score']:.4f}, bm25={r['bm25_score']:.4f}, rrf={r['fusion_score']:.5f}, rerank={r['rerank_score']:.4f}")
        print(f"    Text: {r['text'][:100]}...")