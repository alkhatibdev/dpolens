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

**Languages.** A question is searched in the language of the letters it is written in:
Arabic letters, Arabic, and anything else, English. Keyword search keeps one index per
language, because an index fixes how it splits and folds words when it is built. Meaning
search needs no such split: the model places an Arabic question near the English clause that
answers it, which is how an Arabic question finds GDPR.

Arabic keyword search has three indexes, and the evals compare them. Postgres's own Snowball
stemmer cuts بيانات (data) to يانا but البيانات (the data) to بيان, so a question and the law
can miss each other on the commonest word in the law. A light normalisation folds the
spellings that change no word (the alef forms, ة and ه, the hamza seats, Arabic-Indic digits),
drops diacritics and the stretching stroke, and takes the article off the front of a word, so
both become بيانات, and stems nothing else. The one in use runs the light normalisation and
then the stemmer, so both forms reach the stemmer alike, and ضروري (necessary) in a question
still finds ضرورية in the law. It ranked first of the three, as measured further down.

A law with a translation has a text in each language, and both are embedded. A clause counts
once, at whichever text is closer to the question, and comes back in the question's language
where it has a text in it.

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

## The published score

**GDPR: recall@5 of 0.77, 95% confidence interval 0.60 to 0.90.** Thirty held-out
questions, multilingual-e5-small, context recipe v1, convex combination at 0.5 with text
that only explains excluded. Measured 26 September 2026.

`evals/results/gdpr.json` carries the same numbers in machine-readable form, with the
commit that produced them, and CI compares every change against it.

Read that sentence strictly. It says that on thirty questions drawn from regulator
guidance, the clause the guidance points at was in the top five answers 77% of the time.
It does not say that DPOLens answers 77% of privacy questions correctly.

### Every configuration, on the held-out set

| Configuration | recall@5 | 95% interval | recall@10 | MRR | s/query |
| --- | --- | --- | --- | --- | --- |
| Keyword only (BM25) | 0.30 | 0.13 to 0.47 | 0.57 | 0.26 | |
| Meaning only | 0.43 | 0.27 to 0.60 | 0.57 | 0.28 | |
| Meaning, explaining text excluded | 0.60 | 0.40 to 0.77 | 0.73 | 0.41 | |
| Reciprocal rank fusion, k=10 | 0.77 | 0.60 to 0.90 | 0.83 | 0.45 | |
| **Convex combination, 0.5** | **0.77** | 0.60 to 0.90 | 0.83 | **0.54** | 0.11 |
| Convex combination, e5-base | 0.80 | 0.63 to 0.93 | 0.83 | 0.57 | 0.12 |

Both fusion rules reach the same recall and convex combination ranks the right clause
higher, so it is the default. e5-base scores three points better, which on thirty
questions is one question. It costs three times the first-start indexing, 108 seconds against
33, and a 1.1 GB download against 470 MB. It is available as a setting rather than the default.

### Why the default is not quantised

The int8 build of multilingual-e5-small is a quarter of the size, 118 MB against 470 MB, and
indexes GDPR in half the time on an Apple M series CPU. It is not the default because its score
depends on the processor it runs on, and the published number has to be one you can reproduce.

The published configuration, on the held-out set, measured 4 October 2026:

| Model | CPU | recall@5 | 95% interval | MRR |
| --- | --- | --- | --- | --- |
| e5-small | Apple M series | 0.77 | 0.60 to 0.90 | 0.54 |
| e5-small | x86-64 with AVX2 | 0.77 | 0.60 to 0.90 | 0.54 |
| e5-small int8 | Apple M series | 0.77 | 0.60 to 0.90 | 0.49 |
| e5-small int8 | x86-64 with AVX2 | 0.70 | 0.53 to 0.87 | 0.50 |

Full precision gives the same answers on both processors. The int8 build runs different integer
arithmetic on each, and on x86-64 without AVX512 it misses two more questions. The x86-64 rows
were measured under emulation on the same machine; the full precision rows matching exactly is
the check that emulation did not change the results. The build targets AVX512-VNNI, which was
not available to measure. The command line still accepts it with `--model e5-small-int8`.

### Reranking made it worse

The standard next step is to rescore the top candidates with a cross-encoder. It was
measured rather than assumed, with `jina-reranker-v2-base-multilingual`:

| Rerank window | e5-small | e5-base | s/query |
| --- | --- | --- | --- |
| None | **0.77** | **0.80** | 0.11 |
| Top 10 | 0.57 | 0.67 | 0.7 |
| Top 25 | 0.47 | 0.57 | 1.9 |
| Top 50 | 0.43 | 0.53 | 4.4 |

Worse at every depth, on both models, and monotonically worse as the window widens, at up
to 40 times the latency. Three implementation faults were ruled out first: the output
index, the direction of the score, and the pair encoding, which produces the expected
`query </s></s> passage` form. The visible cause is that the model barely separates
relevant from irrelevant legal text: it scores the exact answer to a breach-notification
question at -2.11 and boilerplate about the regulation entering into force at -2.20.
Reordering by numbers that close destroys an ordering that fusion had already got right.

So DPOLens ships no reranker. `bge-reranker-v2-m3`, the other candidate, has no ONNX
build, and exporting one would require PyTorch, which this project avoids for image size.

### Reproduce it yourself

Nothing here rests on trusting the number. With Docker and `uv` installed:

```bash
git clone https://github.com/alkhatibdev/dpolens && cd dpolens
uv sync --all-packages

docker build -t dpolens-postgres deploy/postgres/
docker run -d --name dpolens-db -p 5432:5432 \
  -e POSTGRES_USER=dpolens -e POSTGRES_PASSWORD=dpolens -e POSTGRES_DB=dpolens \
  dpolens-postgres

export DPOLENS_DATABASE_URL=postgresql+psycopg://dpolens:dpolens@localhost:5432/dpolens
uv run alembic upgrade head
uv run dpolens pack load packs/gdpr
uv run dpolens index build

uv run dpolens evals run --pack gdpr --set held_out \
  --config "convex:0.5+normative" --baselines
```

The first `index build` downloads the model, roughly 470 MB, and takes about half a minute
on a laptop CPU after that. The eval run takes a few seconds. You should see the numbers
above; the bootstrap interval is seeded, so it is identical run to run, while timings
depend on your machine.

To check the question labels rather than the scores:

```bash
uv run python scripts/check_eval_sources.py
```

That fetches every source and reports which labels a regulator page names outright and
which rest on a recorded justification.

### On the tuning set, for comparison

Everything below was measured on the **tuning** set of 20 questions. It is not a published
result and is not written to `evals/results`. It is here because the comparisons it settles
are worth showing, and because it demonstrates a trap worth knowing about.

### Which embedding model

Recall@5 on the tuning set, with the index built from scratch each time on an Apple M
series CPU, measured 4 October 2026.

| Model | Meaning search | Recitals excluded | Index time | Note |
| --- | --- | --- | --- | --- |
| multilingual-e5-small | 0.50 | 0.60 | 33s | |
| multilingual-e5-small int8 | 0.40 | 0.50 | 17s | Built for AVX512-VNNI |
| granite-embedding-97m-r2 int8 | 0.50 | 0.55 | 20s | Built for AVX2 |
| multilingual-e5-base | 0.55 | **0.65** | 108s | 768 dimensions |

Every interval spans roughly 0.20, so all four overlap: this ranks the candidates, it does
not separate them. Two things it does show clearly:

- **Quantised is faster here, and less accurate.** The e5-small int8 build indexes in half
  the time and loses ten points. Both int8 builds target x86 instruction sets this machine
  does not have, and int8 arithmetic differs from one processor to the next, which is why the
  comparison records the architecture it ran on. The held-out comparison above shows how much
  that matters.
- **e5-base leads, and costs three times the indexing time** for it. Whether five points of
  recall is worth that is a held-out question, not a tuning one.

### What BM25 bought over ts_rank

| Keyword ranker | recall@5 | recall@10 | MRR |
| --- | --- | --- | --- |
| `ts_rank`, terms combined with OR | 0.15 | 0.20 | 0.08 |
| BM25 through `pg_textsearch` | 0.25 | 0.30 | 0.12 |

A fairer comparison than it first appeared. With `plainto_tsquery`, which requires every
term to match, `ts_rank` scored 0.00 on all 20 questions, because a question phrased as a
sentence shares no full term set with any clause. Combining the terms with OR is the honest
baseline, and against that BM25 is worth about ten points of recall@5.

### What keyword search is for

Keyword search alone reaches 0.25, and meaning search reaches 0.60. That is not an argument
for dropping it: it earns its place on quoted phrases, defined terms and article numbers,
which is how a lawyer searches and how an assistant follows a citation. On the
conversational questions in these sets, meaning search does the work.

**A warning about small question sets.** On these 20 tuning questions, fusion scored
*below* meaning search alone (0.45 against 0.60), and the opposite is true on the 30
held-out questions (0.77 against 0.60). Same code, same corpus, different questions. Two
sets of this size are not equally hard, so configurations can only be compared within a
set, never across them. Had the tuning set alone been trusted, the conclusion would have
been to drop fusion, which the held-out set shows would have cost 17 points of recall.

### Which Arabic keyword index

The three Arabic indexes, measured on the UAE law's tuning set in Arabic: 20 questions, ten
topics each asked formally and the way people type in chat, with multilingual-e5-small,
measured 13 October 2026. How to choose was settled before these numbers existed: the highest
recall@5 under the published configuration wins, then the higher MRR, then the light
normalisation, the most predictable of the three.

| Arabic keyword index | recall@5, keyword only | recall@5, convex 0.5 | 95% interval | MRR |
| --- | --- | --- | --- | --- |
| Light normalisation | 0.30 | 0.60 | 0.40 to 0.80 | 0.39 |
| Snowball stemmer | 0.40 | 0.70 | 0.50 to 0.90 | 0.43 |
| **Light normalisation, then the stemmer** | 0.40 | **0.70** | 0.50 to 0.90 | **0.45** |

The interval and MRR are for convex combination, the published configuration, and every
column excludes text that only explains. The two stemmers tie on recall and the folded one
ranks the right clause higher, so it is the default. Read the margin strictly: two questions in
twenty separate it from the light normalisation, and the intervals overlap almost entirely, so
this ranks the three rather than proving one better. Settling the rule first is what keeps the
choice from being fitted to these questions. The scores are identical with the UAE law loaded
alone and beside GDPR.

The other two indexes stay, so the comparison can be run again as the set grows:

```bash
uv run dpolens pack load packs/uae-pdpl
uv run dpolens index build
uv run dpolens evals run --pack uae-pdpl --set tuning --config "convex:0.5+normative"
uv run dpolens evals run --pack uae-pdpl --set tuning --config "convex:0.5+normative+light"
uv run dpolens evals run --pack uae-pdpl --set tuning --config "convex:0.5+normative+snowball"
```

## What is not solved

Some questions fail for reasons no ranking change will fix. "Do we need a DPO?" misses
because the corpus never writes "DPO", only "data protection officer". That question stays
in the set, and the score carries the cost, because it is exactly what a developer types.
