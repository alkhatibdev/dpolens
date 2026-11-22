# Search questions

Questions people might ask, written beside each clause of a law, so search can find the clause
when somebody asks in their own words. A model writes them and another checks them, and
DPOLens never shows, quotes or cites them: an answer is always the law's own words.

| File | What it holds |
| --- | --- |
| `<pack>.yaml` | A law's questions, each clause's beside the fingerprint of the words they were written for |
| `write-prompt.md` | The prompt that writes them |
| `check-prompt.md` | The prompt that checks them |

## The rules they follow

- **Kept apart.** A law's own files, in `packs/`, hold the law and nothing a model wrote. These
  files sit here, and each names the models, the day and the prompts that made it.
- **Checked before use.** A second model reads each clause in its place, with the words above
  it and the points under it, and keeps only the questions the clause answers. A person then
  reads 50 of a law's questions, drawn at random. More than 2 that would send a question to
  the wrong clause, and every question of that law is written again.
- **Ranked apart.** A question can bring in a clause the law's own words did not reach: the
  clauses' nearest questions are a list of their own in their law's ranking, and keyword search
  reads a clause's questions after its words. Each list is standardised within the question
  first, so a question's higher scale wins nothing by itself. Each law, and the organisation's
  own policies, which have none, are ranked by themselves and take turns in the results, so a
  question never competes with a policy, or with a law whose questions are not written yet.
- **Proven, not assumed.** Search uses them because, on the practice questions, they found the
  right clause more often, by a rule set before anything was measured. A published score names
  whether it used them: `+questions` in its configuration.
- **Rewritten when the law changes.** Where a clause's words in force no longer match the
  fingerprint its questions carry, those questions are not used until they are written again.
  A search of another day goes without them, and an organisation can turn them off with
  `dpolens search-questions off`.
- **Complete.** A law's file names every clause that states a rule, at the words its questions
  were written for, even a clause whose check kept none of them. CI fails when a clause is
  missing or its words have changed since. `dpolens search-questions status` lists any such
  clause on an instance, such as one still holding an older version of the law.

## Writing them

```bash
uv run dpolens pack load packs/uae-pdpl
uv run python scripts/write_search_questions.py --pack uae-pdpl
```

Each article goes to `claude -p` cut off from this project, with no tools, no MCP servers and no
settings, so the writer reads its prompt and the article and nothing else: never an eval
question. It needs Claude Code, signed in. Each article is saved as it finishes, so a run that
stops carries on where it left off, a plan's usage limit is waited out, and a clause an answer
leaves out is asked for again on its own.

An instance loads a law's file with `dpolens search-questions load search-questions/gdpr.yaml`,
and `dpolens index build` embeds the questions. An instance started from the image does both.
