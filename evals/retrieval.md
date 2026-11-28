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
people type. The index covers a clause's heading and its text together. A heading with no
text of its own, such as Article 17's "Right to erasure", is never a result, since there is
nothing under it to quote: the paragraphs under it are found by their own words, and in
meaning search with the heading in front of them.

Meaning search is a multilingual embedding model running on the CPU inside the container,
through ONNX Runtime. No API key, no network call after the first start, nothing to
configure. An embedding model is not an LLM: it turns text into numbers and writes nothing.

A question is compared with the vector of every clause, with no approximate index in between.
The laws and an organisation's policies come to thousands of vectors, which takes
milliseconds. With an approximate index, the database decides from its own statistics whether
to use it, and other clauses come back when it does, so a search, and a score measured on it,
would not be the same twice.

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

A clause is embedded with its ancestry in front of it: the law's short name in the language of
the clause's text, then the chain of headings above it, capped at 64 tokens by dropping the
middle. Embedded alone, a sub-point is often unfindable. With "GDPR > Right to erasure (‘right
to be forgotten’) > 1." in front of it, it is found. The UAE law's Arabic clauses open with its
Arabic short name, «قانون حماية البيانات الشخصية الإماراتي», and its English ones with UAE PDPL.
A policy has no short name, so its title opens its clauses. The bare text is what gets stored
and quoted, so citations are unaffected.

The string the model saw is stored next to the vector, which means "why did this match" can
be answered by reading rather than guessing. The recipe is versioned, and changing it is an
explicit re-index rather than a quiet drift.

**3. Search questions.**

Questions people might ask are written beside each clause of a law, and checked against it.
They are never shown, quoted or cited: [search-questions/README.md](../search-questions/README.md)
says how they are made and kept in check. They give search the everyday words the law does not
use. The law never writes "DPO" or "delete"; the questions beside its articles on the data
protection officer and on erasure do.

They work in two places. Each clause's nearest question is a list of its own beside meaning
search, and a clause takes the better of its own words' score and its nearest question's. A
question resembles a question more than it resembles legal text, so questions score on a higher
scale than any clause's words, and each list is standardised within the question first: a
clause counts for how far it stands above the rest of its list, and the questions' scale wins
nothing by itself. And keyword search reads a clause's questions after its own words, which is
how an Arabic question finds GDPR, written in English, by keyword too.

**4. Fusion.**

Each retriever returns up to 100 candidates, and the keyword and meaning lists are combined.
Three rules are implemented and the evals choose between them: reciprocal rank fusion, which
uses only positions; convex combination, which rescales each list to 0 to 1 and blends them at
a fixed weight; and standardised fusion, which standardises each list within the question and
adds them, keyword search at 0.3 of the weight and meaning search at 0.7. Rescaling gives the
best of a list full marks however weak it is, where standardising counts a clause for how far it
stands above the rest of its list. Search uses standardised fusion, the rule the published scores
measure. It was chosen on the practice questions, as
[Every configuration](#every-configuration-on-the-held-out-sets) explains. A weight is fitted only
where the practice questions can carry it: one number, chosen by cross-validation, on a curve
that is flat around it.

A question that repeats a clause's own words is asking for that clause, wherever the sum put
it. When a clause among the ten best keyword candidates holds at least nine in ten of the
question's content words, and the question has at least five, that clause comes first in its
law's ranking. Its own words count, never its search questions'.

**5. Results.**

Each law a search covers is ranked by itself, and so are the organisation's own policies,
which have no search questions. The results then take turns, the source whose best match is
closest first. In one list, a policy, or a law whose questions are not written yet, would sink
below a law with them; ranked apart, each keeps its share of the results.

Each result is a whole rule: the clause whose words introduce the match, such as the paragraph
a point belongs to, and the clauses beneath it, each with its own key to cite it by. A rule of
2,500 characters or fewer comes whole; a longer one, such as a list of definitions, comes with
the two clauses beneath it the search ranked highest. A result carries its breadcrumb, whether
it is normative, the document version and the date that version came into force. Within a
source, a clause that obliges someone outranks one that only explains where their scores cannot
separate them. A heading with no text of its own is never a result.

## How it is measured

Each law has two kinds of question set, kept apart. The practice sets are used while improving
retrieval: `tuning`, questions as a person types them, and for GDPR `assistant`, [the queries
an AI assistant sent](README.md#what-ai-assistants-send) while working on code. The held-out
sets produce the published scores and nothing else, and nobody working on search saw them before
they were scored:

- **`held_out`**: questions a person wrote in their own words, the way they would ask while
  building a product, without reading any eval set or search result and without searching
  anything: 30 about each law, 6 of GDPR's and 15 of the UAE law's in Arabic. A question that
  asks two things answered by different rules is an entry for each, and one the law does not
  answer is set aside, so GDPR has 31 entries, 25 in English and 6 in Arabic, and the UAE law
  30, 15 in each language, after setting aside a guardian's consent for a child, on which it
  has no rule.
- **`held_out_assistant`**: the searches Claude Code wrote while working through
  [40 coding tasks](trigger/queries.yaml) in Larder, the trigger test's sample shop, 20 for each
  law and 15 of them written in Arabic. Each task ran once, with the plugin, against an instance
  holding the task's law alone, and each run ended when its first search came back, so every
  query was written before any result was read. A query often asks two things at once, and
  each thing it asks is a part with an entry of its own: 46 parts from 39 queries.
- **`held_out_community`**: the same 40 tasks, with DPOLens added as
  [the community page](https://dpolens.com/community) adds it, the MCP server alone, on an
  instance set up as the community version: 44 parts from 38 queries.

A question's label, the clause that counts as correct, does not come from the search
author. It comes from regulator guidance, or for the UAE law, which no regulator guidance
numbers, from law firms' published guides, and `scripts/check_eval_sources.py` reports where
each label stands:

- **cited**: the guidance page names the article, which a machine confirms
- **justified**: the guidance answers the question without printing the number, and the
  note records why that clause is the answer

Every held-out label was fixed, and the files' hashes recorded, before any of their questions
was searched. A label found wrong after scoring is corrected beside its figure, never in its
place.

Phrasings in the tuning sets are learned from real developer questions and rewritten, never
copied, because Stack Overflow content is CC BY-SA 4.0 and would not fit the licence on this
directory.

A hit is the expected clause or anything inside it: a point of Article 13(1) is part of
Article 13(1). A sibling paragraph is not, because Article 13(2) is a different rule. Search
answers with whole rules, and a whole rule counts by the clauses it shows: Article 13(1) shown
with its points is a hit for a question about 13(1)(c).

Recall@5 is reported with a bootstrap confidence interval, because a set this size moves by
a few points on its own and a bare number invites more confidence than it has earned. Where a
set asks one thing in two entries, the interval resamples the things asked, not the entries.
CI fails a change that drops below the published interval. The pack, the questions and the
model are all fixed, so a drop has exactly one possible cause.

## The published scores

Measured 28 November 2026, with multilingual-e5-small, context recipe v3, and the configuration
search runs: standardised fusion with keyword search at 0.3, text that only explains excluded,
the search questions, and whole rules. Both laws were loaded and each run kept to its own law,
which is what an organisation that has selected that law searches.

### Questions people ask

| Law | Questions | recall@5 | 95% interval | recall@10 | MRR |
| --- | --- | --- | --- | --- | --- |
| **GDPR** | 31: 25 in English, 6 in Arabic | **0.90** | 0.81 to 1.00 | 0.90 | 0.69 |
| **The UAE law** | 30: 15 in Arabic, 15 in English | **0.87** | 0.73 to 0.97 | 0.97 | 0.77 |

By language, GDPR finds 23 of its 25 English questions in the top five and 5 of its 6 Arabic
ones, and the UAE law 13 of 15 in each language. Six questions say little on their own: GDPR
asked in Arabic has an interval of 0.50 to 1.00. GDPR has no Arabic text, so an Arabic question
about it has to cross languages to find its clause.

### Queries an AI assistant writes

| Law | Where it searched | Parts | recall@5 | 95% interval | recall@10 | Queries with every part in the top five |
| --- | --- | --- | --- | --- | --- | --- |
| **GDPR** | An instance of your own | 20 | **0.40** | 0.20 to 0.60 | 0.55 | 7 of 19 |
| **The UAE law** | An instance of your own | 26 | **0.62** | 0.42 to 0.81 | 0.81 | 10 of 20 |
| GDPR | The community version | 20 | 0.55 | 0.35 to 0.75 | 0.80 | 10 of 19 |
| The UAE law | The community version | 24 | 0.79 | 0.62 to 0.92 | 0.79 | 14 of 19 |

Both rows of a law come from the same 40 tasks, with the same AI assistant and model, Claude
Code 2.1.288 with `claude-sonnet-5-5`, one run each. In both, 37 of the 40 tasks searched, all
before editing anything: the other three asked for something Larder does not have, a storage
bucket twice and a password reset flow, and the AI assistant stopped to ask for it. All 15 tasks
written in Arabic searched, but Claude Code wrote only one of their searches in Arabic, with the
plugin, and the rest in English. That is why the UAE law's Arabic assistant set holds two parts
and GDPR has none.

Task by task, the queries sent to the community version had every part answered in the top
five more often: for 9 of GDPR's 18 tasks against 6, and 14 of the UAE law's 19 against 9. Its
instructions ask for questions in general terms, what the code does with which kind of data,
and none of its queries named a product or a company, where 6 of the 39 sent with the plugin
did. The two runs differ in more than those words, since the community version holds both
laws, so this is the community version as it runs, not the sentence alone.

### With both laws selected

An organisation that selects both laws searches them together, and the two share the ten
results, so the figure to read is recall@10. Each law's questions, searched alone and beside the
other law:

| Set | GDPR, alone | GDPR, beside the UAE law | The UAE law, alone | The UAE law, beside GDPR |
| --- | --- | --- | --- | --- |
| Questions people ask | 0.90 | 0.90 | 0.97 | 0.87 |
| An AI assistant, an instance of your own | 0.55 | 0.40 | 0.81 | 0.62 |
| An AI assistant, the community version | 0.80 | 0.55 | 0.79 | 0.79 |

### Whole rules and single clauses

Search answers with whole rules: a match comes with the words that introduce its rule and the
clauses beneath them. The same configuration scored on single clauses, recall@5:

| Set | GDPR, clauses | GDPR, whole rules | The UAE law, clauses | The UAE law, whole rules |
| --- | --- | --- | --- | --- |
| Questions people ask | 0.87 | 0.90 | 0.83 | 0.87 |
| An AI assistant, an instance of your own | 0.35 | 0.40 | 0.54 | 0.62 |
| An AI assistant, the community version | 0.55 | 0.55 | 0.75 | 0.79 |

### Every configuration, on the held-out sets

Recall@5, with MRR in brackets, each law alone. Keyword only and meaning only are each retriever
on its own, over single clauses, without the search questions. The fusion rules use everything
search does.

| Configuration | GDPR, people | The UAE law, people | GDPR, an AI assistant | The UAE law, an AI assistant |
| --- | --- | --- | --- | --- |
| Keyword only (BM25) | 0.39 (0.27) | 0.50 (0.31) | 0.30 (0.12) | 0.23 (0.18) |
| Meaning only | 0.48 (0.34) | 0.67 (0.59) | 0.25 (0.15) | 0.31 (0.23) |
| Convex combination, 0.5 | 0.90 (0.70) | 0.90 (0.76) | 0.35 (0.20) | 0.69 (0.42) |
| **Standardised fusion, 0.3** | **0.90 (0.69)** | **0.87 (0.77)** | **0.40 (0.27)** | **0.62 (0.48)** |

The AI assistant columns are the instance of your own. The fusion rule was chosen on the practice
questions before these were scored, by the rule in [Judging a change](README.md#judging-a-change),
which scores how high the right rule sits among the ten: standardised fusion placed it higher
than convex combination by more than chance gives, with no set worse. On the held-out sets, the
same rule says the same: over every set, each law alone and beside the other, standardised
fusion places the right rule higher (a place score of 0.47 against 0.44, a gain chance gives
3.5% of the time), with no set worse, and finds 201 answers in the top five where convex
combination finds 203. The held-out sets confirm the choice; they did not make it.

### Read the numbers strictly

The first says that on 31 questions about GDPR, written by a person who had not seen what search
returns, the clause the guidance points at was in the top five answers 90% of the time. It does
not say that DPOLens answers 90% of privacy questions correctly. These are a person's questions,
asked one at a time; the searches an AI assistant writes in the middle of a task find the right
rule far less often.

### DPOLens 0.2.0 on the same questions

DPOLens 0.2.0, the release before, searched the same held-out questions once 0.3.0's scores on
them were fixed, with its own code, packs and configuration: convex combination at 0.5 over
single clauses, text that only explains excluded, and no search questions, which it did not
have. Both releases' results were counted by the same code.

Each law alone, recall@5:

| Set | GDPR, 0.2.0 | GDPR, 0.3.0 | The UAE law, 0.2.0 | The UAE law, 0.3.0 |
| --- | --- | --- | --- | --- |
| Questions people ask | 0.55 | 0.90 | 0.60 | 0.87 |
| An AI assistant, an instance of your own | 0.40 | 0.40 | 0.27 | 0.62 |
| An AI assistant, the community version | 0.35 | 0.55 | 0.33 | 0.79 |

Beside the other law, recall@10:

| Set | GDPR, 0.2.0 | GDPR, 0.3.0 | The UAE law, 0.2.0 | The UAE law, 0.3.0 |
| --- | --- | --- | --- | --- |
| Questions people ask | 0.48 | 0.90 | 0.63 | 0.87 |
| An AI assistant, an instance of your own | 0.50 | 0.40 | 0.23 | 0.62 |
| An AI assistant, the community version | 0.40 | 0.55 | 0.29 | 0.79 |

For GDPR's searches from an instance of your own, the two releases find as many in the top five,
8 of 20 parts, though not the same ones, and 0.3.0 places the right rule higher (MRR 0.27 against
0.18). Beside the UAE law, 0.3.0 finds fewer of them in the top ten: 8 against 10.

Over all eighteen runs, each law alone and beside the other, and counting single clauses for
both, 0.3.0 finds 191 answers in the top five where 0.2.0 finds 118: 42 topics it finds there
that 0.2.0 missed, and 5 the other way. By the rule in
[Judging a change](README.md#judging-a-change), the right rule sits higher among the ten (a place
score of 0.45 against 0.28), a gain chance gives 0.01% of the time, with no set worse. It counts
single clauses because that rule restates a change of what a result is rather than judging it.

0.2.0 searched a fresh database, loaded in its own order from the Postgres image the scores above
were measured on, and gave the same results when it searched again after Postgres had refreshed its
statistics. It holds the UAE law's twenty definitions in one clause, Article 1, so where a label
names a definition, in three of the questions people ask, Article 1 counts for 0.2.0. The AI
assistant wrote its queries reading 0.3.0's description of the search tool, and with 0.2.0's it
might have asked otherwise, so those rows compare the two searches on the same queries, not the
two releases end to end. 0.2.0 answers with single clauses and 0.3.0 with whole rules, each
counted by what it shows.

Each law alone can be measured again from the tag: check out `v0.2.0`, copy the held-out files,
`evals/<law>/held_out*.yaml`, into its `evals/` folder, change each `uae-pdpl:art-1:def-` label
to `uae-pdpl:art-1`, load the packs and build the index as
[Reproduce it yourself](#reproduce-it-yourself) does, leaving out the search questions, and run
`dpolens evals run --pack <law> --config convex:0.5+normative`, naming each language of a set
with `--set` and adding `--together` where there are two.

### Earlier scores

Until DPOLens 0.3.0 the published scores came from other held-out questions: 0.73 for GDPR, on
30 in English, 0.53 for the UAE law, on 19 topics asked in both languages, and 0.33 for GDPR asked
in Arabic, measured 6 November 2026 with convex combination over single clauses and without the
search questions. GDPR's was first published on 26 September 2026, at 0.77. Changes to search
have been judged on those questions since November 2026, so they are in the tuning sets now, and
the scores above replace them. Those scores and the ones above cannot be compared: other
questions, another configuration and another unit of result.
[DPOLens 0.2.0 on the same questions](#dpolens-020-on-the-same-questions) is the comparison that
can be made.

`evals/results/gdpr.json` and `evals/results/uae-pdpl.json` carry the published scores in
machine-readable form, with the commit that produced them, and CI compares every change against
each of them.

### Why the default is not quantised

The int8 build of multilingual-e5-small is a quarter of the size, 118 MB against 470 MB, and
indexes GDPR in half the time on an Apple M series CPU. It is not the default because its score
depends on the processor it runs on, and the published number has to be one you can reproduce.

The configuration published then, on the thirty questions that were GDPR's held-out set (now in
its tuning set), before two of them were reworded, with GDPR loaded alone, measured 4 October
2026:

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
measured rather than assumed, with `jina-reranker-v2-base-multilingual`, on the thirty
questions that were GDPR's held-out set on 26 September 2026 (now in its tuning set), with GDPR
loaded alone:

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
uv run dpolens pack load packs/uae-pdpl
uv run dpolens search-questions load search-questions/gdpr.yaml search-questions/uae-pdpl.yaml
uv run dpolens index build

uv run dpolens evals run --pack gdpr --baselines --together \
  --set held_out --set held_out_assistant --set held_out_community
uv run dpolens evals run --pack uae-pdpl --baselines --together \
  --set held_out --set held_out_assistant --set held_out_community
```

The first `index build` downloads the model, roughly 470 MB, then embeds every clause and every
search question, which takes a few minutes on a laptop CPU. Each eval run takes under a minute.
You should see the numbers above; the bootstrap interval is seeded, so it is identical run to
run, while timings depend on your machine. `--every-law` scores each law beside the other, and
`--config standardised:0.3+normative+questions` scores single clauses.

To check the question labels rather than the scores:

```bash
uv run python scripts/check_eval_sources.py
```

That fetches every source and reports which labels a regulator page names outright and
which rest on a recorded justification.

### On the tuning sets, for comparison

Everything below was measured on the tuning sets as they stood on the date each section gives,
when GDPR's held 20 questions. It is not a published result and is not written to
`evals/results`. It is here because the comparisons it settles
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
which is how a lawyer searches and how an AI assistant follows a citation. On the
conversational questions in these sets, meaning search does the work.

**A warning about small question sets.** When fusion was first measured, on 26 September
2026, it scored *below* meaning search alone on these 20 tuning questions (0.45 against
0.60), and the opposite was true on the 30 held-out questions of the time (0.77 against 0.60). Same
code, same corpus, different questions. Two sets of this size are not equally hard, so
configurations can only be compared within a set, never across them. Had the tuning set
alone been trusted, the conclusion would have been to drop fusion, which the held-out set
showed would have cost 17 points of recall.

### Which Arabic keyword index

The three Arabic indexes, measured on the UAE law's tuning set in Arabic as it stood then: 20
questions, ten topics each asked formally and the way people type in chat, with
multilingual-e5-small, measured 13 October 2026. How to choose was settled before these numbers
existed: the highest recall@5 under the configuration published then wins, then the higher MRR, then the light
normalisation, the most predictable of the three.

| Arabic keyword index | recall@5, keyword only | recall@5, convex 0.5 | 95% interval | MRR |
| --- | --- | --- | --- | --- |
| Light normalisation | 0.30 | 0.60 | 0.40 to 0.80 | 0.39 |
| Snowball stemmer | 0.40 | 0.70 | 0.50 to 0.90 | 0.43 |
| **Light normalisation, then the stemmer** | 0.40 | **0.70** | 0.50 to 0.90 | **0.45** |

The interval and MRR are for convex combination, the configuration published then, and every
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
uv run dpolens evals run --pack uae-pdpl --set tuning.ar --config "convex:0.5+normative"
uv run dpolens evals run --pack uae-pdpl --set tuning.ar --config "convex:0.5+normative+light"
uv run dpolens evals run --pack uae-pdpl --set tuning.ar --config "convex:0.5+normative+snowball"
```

### Which name opens a clause

What opens a clause's string was chosen on the tuning sets of both laws, in both languages, 70
questions in all. Two openings were built: the law's full title in the language of the clause,
such as "Regulation (EU) 2016/679 (General Data Protection Regulation)", and its short name in
that language, such as GDPR. The rule was settled before either was measured: the higher
recall@5 wins, and the short name on a tie, because it is how a question names a law. Measured 6
November 2026, with multilingual-e5-small and the configuration published then, both laws loaded.

| Tuning set | Questions | Full title | Short name |
| --- | --- | --- | --- |
| GDPR | 20 in English | 0.50 | 0.55 |
| GDPR | 20 in Arabic | 0.35 | 0.35 |
| The UAE law | 20 in Arabic | 0.70 | 0.70 |
| The UAE law | 10 in English | 0.60 | 0.70 |
| All four | 70 | 0.53 | 0.56 |

On every set each score is inside the other's interval, so by the rule this is a tie, and the
short name opens a clause. The full title finds two questions the short name misses, and the
short name finds four the full title misses. The full title finds three more in the top ten and
ranks the right clause a little higher, at an MRR of 0.37 against 0.35. No clause's opening and
headings pass the 64-token cap under either, so neither costs a heading. The full title is what
commit `046b514` embeds, so both columns can be measured again from this repository's history.

## What is not solved

The searches an AI assistant writes in the middle of a task are where search is weakest. They
often describe the code rather than ask, and ask two things at once, such as whether something
may be done and how long the data may be kept. For GDPR, the right rule is in the top five for
40% of the things such a search asks, where it is there for 90% of a person's questions. On an
instance of your own, that is no more than DPOLens 0.2.0 found.

Some questions fail on the law's own words. "Do we need a DPO?" misses them, because the corpus
never writes "DPO", only "data protection officer". The search questions are how such a question
is found: "DPO" is in the questions beside Article 37.
