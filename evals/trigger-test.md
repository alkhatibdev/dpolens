# Does an AI assistant actually use it

[retrieval.md](retrieval.md) measures whether search finds the right clause once an AI assistant
asks. This page measures whether it asks. An AI assistant that writes the code for storing a phone
number without ever calling DPOLens gets nothing from a good search, so this is the number the
rest depends on.

## The published result

**Claude Code with the DPOLens plugin searched before writing code in 36 of 36 runs of tasks
that touch personal data, and in none of the 45 runs of tasks that do not.** Asked questions
about the rules, it searched in 9 of 9. Thirty held-out tasks, three runs each, Claude Code
2.1.288 with `claude-sonnet-5-5`, measured 22 November 2026.

| Group | Tasks | Searched | Share | 95% interval |
| --- | --- | --- | --- | --- |
| Coding tasks that touch personal data | 12 | 36 of 36 runs, all before the first edit | 1.00 | 1.00 to 1.00 |
| Coding tasks that do not | 15 | 0 of 45 runs | 0.00 | 0.00 to 0.00 |
| Questions about the rules | 3 | 9 of 9 runs | 1.00 | 1.00 to 1.00 |

Every task behaved the same way in all three of its runs: no task searched in some runs and not
others.

Read the first line strictly. A bootstrap interval cannot show spread when every task succeeds
every time, so "1.00 to 1.00" is not certainty. With twelve tasks and no misses, the honest
bound is the rule of three: the share of tasks like these that would miss is likely below one in
four. The same goes for none of 45: with fifteen tasks and no search they did not need, the
share of tasks like these that would search without need is likely below one in five. It says
that on these tasks, in this app, Claude Code with the plugin searched every time it should
have, before it touched the code, and never when it did not need to. It does not say that every
AI assistant, or every codebase, behaves the same way.

`evals/results/trigger.json` carries the same numbers, with the record of how each batch ran.

## What changed since October

The first published result, measured 8 and 9 October 2026, had the plugin searching in 3 of 45
runs of tasks that do not touch personal data. All three were one task, `product-viewed-event`,
which asks for a `product_viewed` event to be sent to Segment when a product page opens, with the
product slug. The event carries nothing about the person viewing the page, so the label says no
search is needed, and the number counts the search against DPOLens.

The task had two ways in. The skill's description said to use DPOLens "when sending data to
another service", which that task does with data about no one, where the server's instructions
say "personal data". And in one of its three runs, Claude Code reached DPOLens through the
plugin's `/policy-check` command, which it chose to run on its own. The skill now says "when
sending personal data to another service", and the result above was measured with it:
`product-viewed-event` searched in none of its runs, and `/policy-check` never ran on its own. A
first rerun of the same change, on 17 and 18 November with an instance that refused every search
because no law was chosen, had one search it did not need in 45: `session-length` ("Make sessions
last 7 days instead of 30"), in one of its three runs. So read none of 45 as rarely, not never.

One task was reworded between the two measurements, `id-check-on-wine` to
`id-check-on-delivery`, so both setups were measured again on the tasks as they stand.

The search box now asks for one question. Its description, which the AI assistant reads before
it writes a search, says "One question, in words: what the code does, with which data". Search
ranks clauses against the whole question, so a question that asks two things at once is a weaker
match for the clause that answers either. Both setups were measured again with it, and the
result above is that measurement. The searches changed: with the plugin, 14 of the 45 first
searches in the runs of 18 and 19 November asked two things, such as "can we log client IP
addresses and user agent in request logs, and how long can we keep them", and 8 of 45 did with
the new description. Without the plugin, 12 of 47 became 7 of 46. A search counts as asking two
things by a rule written before these runs: a second question or subject after a comma, a
semicolon, a colon, or an "and" that starts a question.

## Without the plugin

The plugin brings three things: the MCP server, two commands, and a skill whose description
tells Claude Code when to reach for DPOLens. The same thirty tasks were run with the MCP server
added on its own, so that only the instructions the server sends when it connects were there.

| Group | With the plugin | MCP server on its own |
| --- | --- | --- |
| Coding tasks that touch personal data | 36 of 36 | 36 of 36 |
| Coding tasks that do not | 0 of 45 | 1 of 45 |
| Questions about the rules | 9 of 9 | 9 of 9 |

The server's instructions do the work: without the skill, every task that should search still
did, before editing. This time the one difference runs the other way. Without the plugin,
`product-viewed-event` searched in 1 of its 3 runs, asking about "sending product page view
analytics events to Segment with a user or anonymous identifier". That is a fair question, since
a visitor identifier can be personal data, and the label counts it against DPOLens all the same. In
October, without the plugin, the task never searched, and the instructions the server sends are
the same text as then.

The plugin is still what [Get started](https://dpolens.com/docs/get-started) installs, for its
commands and for keeping the token in the system's credential store.

## How it is measured

**The setup.** Each run is a new container: Claude Code at a pinned version, run as an ordinary
user, with an empty profile into which DPOLens is installed the way the
[README](../README.md) installs it, from the plugin marketplace, configured with
`claude plugin configure`. Nothing else is in the profile: no `CLAUDE.md`, no memory, no other
plugins. Claude Code's defaults stay as they are, including tool search, which shows the model
only the names of MCP tools until it decides to look one up. The AI assistant works in a fresh
checkout of [Larder](trigger/app/), a small shop backend with accounts, orders,
logging, a Segment call and a Postmark email, and a catalogue and front page that hold no data
about people. It talks to a throwaway DPOLens instance built from the DPOLens checkout under
test, which for the published runs held GDPR alone.

**The tasks.** [held_out.yaml](trigger/held_out.yaml) holds thirty: twelve coding
tasks that collect, store, log, share or delete data about a person, three questions about the
rules, and fifteen tasks that do not touch personal data, six of them near misses, such as
renaming the column a name is kept in. Each label says why it is what it is. No coding task
names the subject: none says "privacy", "GDPR", "consent" or "compliant", because a task that
did would trigger any AI assistant and the number would mean nothing. A separate set of twenty,
[tuning.yaml](trigger/tuning.yaml), is the one to improve the guidance against, and the
held-out set is never used for that.

**What counts.** A run searched if it called `search_policies` or `get_clause`, the two tools
that return clause text. It searched before editing if that came before its first `Edit`,
`Write`, `MultiEdit` or `NotebookEdit`. A run stops once its first search comes back, since the
outcome is known by then. Otherwise it runs until the AI assistant finishes, 25 turns or ten
minutes. Every run's searches are also counted in the instance's query log, and the two counts
agreed for every run but one. Without the plugin, one run's log holds a second question that the
run's record never shows. That run had also started a subagent to read the code, and a
subagent's calls are not in the record. A search the server refuses, such as one with no
question at all, never reaches the log, and still counts as a search, because what is measured
is whether the AI assistant decides to look the rules up.

**Runs that could not be scored.** None in these batches. A run that could not have reached
DPOLens, because the plugin did not load, the server did not connect or the request to the model
failed, is not a run that chose not to search, so it is made again and reported as an attempt
not scored.

**The interval.** Tasks are resampled with their three runs kept together, because three runs of
one task are not three tasks.

## Reproduce it yourself

You need Docker and a Claude subscription or an API key. `claude setup-token` prints a token for
a subscription; save it to `evals/trigger/.oauth-token`, which git ignores. Without that file,
the runner uses `ANTHROPIC_API_KEY`.

```bash
uv run python scripts/run_trigger_test.py --set held_out --runs 3 --max-runs 90 \
  --model claude-sonnet-5-5
uv run python scripts/run_trigger_test.py --set held_out --runs 3 --max-runs 90 \
  --model claude-sonnet-5-5 --setup mcp-only
```

Each batch of ninety runs takes about half an hour.
[evals/trigger/README.md](trigger/README.md) covers resuming a batch, scoring one again,
and reading the full record each run leaves behind.

## What it does not show

- **Other AI assistants.** Only Claude Code was measured, on one model and one version. Codex,
  Cursor and GitHub Copilot in VS Code read the same guidance, but how often they act on it has
  not been measured.
- **Messier work.** The tasks are short, plainly phrased requests in a small app. In a large
  codebase, the code that handles people's data is harder to spot, and requests are rarely this
  clear.
- **Whether the answer changed the code.** A run stops at its first search, so this measures
  whether the AI assistant looks the rules up, not what it does with what it finds.
- **The labels.** Whether a task should trigger a search is the author's judgment, not a
  regulator's. Each one says why, so a reader who disagrees can see exactly what with.
