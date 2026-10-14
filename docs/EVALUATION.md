# Evaluation results

## Pinecone run — 14 Oct 2026
- Embedding: Pinecone multilingual-e5-large (1024 dims, cosine), serverless aws/us-east-1, namespace tenant-demo
- Eval set: 36 labelled questions (27 answerable, 4 unanswerable, 3 access-control, 5 safety; some overlap)
- Calibration (threshold off): answerable min 0.834 / avg 0.881; unanswerable max 0.775 / avg 0.748
- MIN_SCORE chosen: 0.80 (midpoint of the gap, margin on both sides)
- Results: hit@1 27/27 (100%), hit@3 27/27, abstention 4/4, access leakage 0, safety 5/5

## Offline baseline (hash embedder, word counting)
- hit@1 26/27 (q19 "first day as a new joiner" matched "per day" in the travel policy)
- "How many casual leaves do I get?" -> wrong section (Applying for leave)
- With e5: q19 fixed; casual-leave question -> correct section (Annual leave entitlement, "8 days")

## Limitations / next steps
- Only 4 unanswerable questions, all clearly off-topic; add near-miss questions (e.g. "leave policy for interns") to stress-test the threshold
- Evaluation scores the correct document, not the correct section; section-level scoring is the next improvement
- 9 synthetic documents; real corpora will need re-calibration