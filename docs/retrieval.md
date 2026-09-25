# How retrieval works, and how well

DPOLens has to find the clause that answers a question phrased in a developer's words
rather than the law's. GDPR Article 17(1)(b) never says "delete"; it says "the data subject
withdraws consent on which the processing is based". Closing that gap is what this page
describes, along with how the result is measured and what has been measured so far.

## The pipeline

**1. Two retrievers, over the same clauses.**

Keyword search is BM25, through the `pg_textsearch` extension. Postgres `ts_rank` is not a
competitive ranker: it has no inverse document frequency, no term frequency saturation and
no length normalisation, so it cannot tell a rare term from a common one. That matters more
in law than in most corpora, because article numbers and defined terms are exactly what
people type. The index covers a clause's heading and its text together, since Article 17
holds no text of its own and "right to erasure" is its heading.

Meaning search is a multilingual embedding model running on the CPU inside the container,
through ONNX Runtime. No API key, no network call after the first start, nothing to
configure. An embedding model is not an LLM: it turns text into numbers and writes nothing.

**2. What gets embedded matters more than which model.**

A clause is embedded with its ancestry in front of it: the document's short name, then the
chain of headings above it, capped at 64 tokens by dropping the middle. Embedded alone, a
sub-point is often unfindable; embedded with "GDPR, Right to erasure, 1." in front of it, it
is. The bare text is what gets stored and quoted, so citations are unaffected.

The string the model saw is stored next to the vector, which means "why did this match" can
be answered by reading rather than guessing. The recipe is versioned, and changing it is an
explicit re-index rather than a quiet drift.

**3. Fusion.**

Each retriever returns up to 100 candidates, and the two ranked lists are combined. Two
rules are implemented and the evals choose between them: reciprocal rank fusion, which uses
only positions, and convex combination, which normalises each list and blends them at equal
weight. A fitted weight is deliberately not offered, because 30 held-out questions cannot
support one honestly: it would fit noise and the published number would be dishonest.

**4. Results.**

Each result carries the clause, its breadcrumb, whether it is normative, the document
version and the date that version came into force. A clause that obliges someone outranks
one that only explains where the retrievers cannot separate them.

## How it is measured

Two question sets per pack, kept apart: a tuning set used while improving retrieval, and a
held-out set that produces the published score and nothing else.

A question's label, the clause that counts as correct, does not come from the search
author. It comes from regulator guidance, and `scripts/check_eval_sources.py` reports where
each label stands:

- **cited**: the guidance page names the article, which a machine confirms
- **justified**: the guidance answers the question without printing the number, and the
  note records why that clause is the answer

Phrasings are learned from real developer questions and rewritten, never copied, because
Stack Overflow content is CC BY-SA 4.0 and would not fit the licence on this directory.

A hit is the expected clause or anything inside it: a point of Article 13(1) is part of
Article 13(1). A sibling paragraph is not, because Article 13(2) is a different rule.

Recall@5 is reported with a bootstrap confidence interval, because a set this size moves by
a few points on its own and a bare number invites more confidence than it has earned. CI
fails a change that drops below the published interval. The pack, the questions and the
model are all fixed, so a drop has exactly one possible cause.

## What the numbers say

`evals/results/gdpr.json` carries the machine-readable version, including the model, the
context recipe, the fusion rule and the commit that produced it.

**No score is published yet.** The four-model comparison has not been run to completion, so
this section stays empty rather than quoting a number measured on one model and one
configuration. What exists today is a tuning-set reading, which is not a published result
and is not written to `evals/results`.

## What is not solved

Some questions fail for reasons no ranking change will fix. "Do we need a DPO?" misses
because the corpus never writes "DPO", only "data protection officer". That question stays
in the set, and the score carries the cost, because it is exactly what a developer types.
