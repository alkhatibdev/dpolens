# Eval sets

These files are how DPOLens proves that search finds the right clause. They are the
evidence behind any number in the README, so they are held to the same standard as the
packs themselves.

## Layout

```
evals/<pack>/tuning.yaml      used while improving retrieval
evals/<pack>/held_out.yaml    produces the published score, and nothing else
evals/results/<pack>.json     the published held-out score, committed
```

`evals/results` is committed, because CI compares every change against it and because it
is the evidence behind any number in the README. It holds **held-out runs only**:
`--write` refuses a tuning run, since a score measured on the set used for tuning does not
belong in a file people will read as the published result. Tuning numbers print to the
terminal and stay there.

A pack needs at least 20 tuning and 30 held-out questions before any score of it is
published. Fifty is not arbitrary: on thirty questions one question is more than three
points of recall, and a smaller set produces a number too wide to defend.

## A question

```yaml
questions:
  - id: breach-deadline
    question: We had a data breach. How quickly must we tell the regulator?
    lang: en
    expected_keys: [gdpr:art-33:para-1]
    source: https://ico.org.uk/for-organisations/report-a-breach/personal-data-breach/personal-data-breaches-a-guide/
    note: Optional. Where a phrasing came from, or why a question is hard.
```

| Field | Required | Meaning |
| --- | --- | --- |
| `id` | yes | Stable and unique within the file. Reported when the question fails |
| `question` | yes | As someone would actually type it |
| `lang` | yes | BCP 47 code |
| `expected_keys` | yes | The clauses that answer it. Any one of them counts as a hit |
| `source` | yes | Guidance that ties this question to that clause |
| `note` | no | Anything a reader of the file would wonder about |

## Where questions come from

**The expected clause comes from the source, never from the search author.** Regulator
guidance that already names the article, such as ICO guides and EDPB guidelines, is the
best kind: it settles what the answer is before anyone looks at what DPOLens returns. A
question written by reading the search results is a test of memory, not of retrieval.

**Phrasings are learned, never copied.** Real developer questions on Stack Overflow and
similar sites are the best guide to how people actually ask, and Stack Overflow content is
CC BY-SA 4.0, which does not fit the CC BY 4.0 that covers this directory. Read the thread,
learn the vocabulary, write the question yourself, and put the thread URL in `note`.

Keep the hard ones. "Do we need a DPO?" fails today because the corpus never writes "DPO",
only "data protection officer". That is exactly the question a developer types, so it stays
in the set and the number carries the cost.

## Scoring

A hit is the expected key, or any clause inside it: a point of Article 13(1) is part of
Article 13(1). A sibling paragraph is not, because Article 13(2) is a different rule.

`recall@5` is the reported number, with a bootstrap confidence interval, and CI fails on a
regression beyond that interval. `recall@10` and MRR are reported and never gated.

## Running them

```bash
uv run dpolens evals run --pack gdpr --set tuning
uv run dpolens evals run --pack gdpr --set held_out --baselines --write
```

`--config` picks what to score: a fusion rule (`rrf:10`, `rrf:60`, `convex:0.5`), a single
retriever (`keyword`, `meaning`), and a `+normative` suffix on any of them to exclude text
that explains without obliging. `--baselines` adds the two single retrievers to the run, so
a fusion rule can never be adopted while being worse than half the system.

To score every model against every configuration, which is how the default model and the
fusion rule are chosen:

```bash
uv run python scripts/run_matrix.py --set tuning
uv run python scripts/run_matrix.py --set tuning --models e5-small,granite-97m-int8
```

It re-indexes the corpus once per model, so a full run takes a while and a first run also
downloads the models. Rows are printed as they are measured.

To check where each label comes from:

```bash
uv run python scripts/check_eval_sources.py
```
