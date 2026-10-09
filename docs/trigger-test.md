# Does an assistant actually use it

[retrieval.md](retrieval.md) measures whether search finds the right clause once an assistant
asks. This page measures whether it asks. An assistant that writes the code for storing a phone
number without ever calling DPOLens gets nothing from a good search, so this is the number the
rest depends on.

## The published result

**Claude Code with the DPOLens plugin searched before writing code in 36 of 36 runs of tasks
that touch personal data, and in 3 of 45 runs of tasks that do not.** Asked questions about the
rules, it searched in 9 of 9. Thirty held-out tasks, three runs each, Claude Code 2.1.288 with
`claude-sonnet-5-5`, measured 8 and 9 October 2026.

| Group | Tasks | Searched | Share | 95% interval |
| --- | --- | --- | --- | --- |
| Coding tasks that touch personal data | 12 | 36 of 36 runs, all before the first edit | 1.00 | 1.00 to 1.00 |
| Coding tasks that do not | 15 | 3 of 45 runs | 0.07 | 0.00 to 0.20 |
| Questions about the rules | 3 | 9 of 9 runs | 1.00 | 1.00 to 1.00 |

Every task behaved the same way in all three of its runs: no task searched in some runs and not
others.

Read the first line strictly. A bootstrap interval cannot show spread when every task succeeds
every time, so "1.00 to 1.00" is not certainty. With twelve tasks and no misses, the honest
bound is the rule of three: the share of tasks like these that would miss is likely below one in
four. It says that on these tasks, in this app, Claude Code with the plugin searched every time
it should have, and before it touched the code. It does not say that every assistant, or every
codebase, behaves the same way.

`evals/results/trigger.json` carries the same numbers, with the record of how each batch ran.

## The task that searched without needing to

All three searches that should not have happened are one task, `product-viewed-event`, in each of
its runs. It asks for a `product_viewed` event to be sent to Segment when a product page opens,
with the product slug. The label says no search is needed, because the event carries nothing
about the person viewing the page. The assistant asked about "sending product page view
analytics events to a third-party service such as Segment", which is a fair question, and the
number counts it against DPOLens anyway, because that is what the label says.

## Without the plugin

The plugin brings three things: the MCP server, two commands, and a skill whose description
tells Claude Code when to reach for DPOLens. The same thirty tasks were run with the MCP server
added on its own, so that only the instructions the server sends when it connects were there.

| Group | With the plugin | MCP server on its own |
| --- | --- | --- |
| Coding tasks that touch personal data | 36 of 36 | 36 of 36 |
| Coding tasks that do not | 3 of 45 | 0 of 45 |
| Questions about the rules | 9 of 9 | 9 of 9 |

The server's instructions did the work: without the skill, every task that should search still
did, before editing. The one difference is `product-viewed-event`, and the skill's description
is the likely reason. It says to use DPOLens "when sending data to another service", which that
task does with data about no one, where the server's instructions say "personal data". Without
the plugin, the task never searched. The plugin is still what the README installs, for its
commands and for keeping the token in the system's credential store.

## How it is measured

**The setup.** Each run is a new container: Claude Code at a pinned version, run as an ordinary
user, with an empty profile into which DPOLens is installed the way the
[README](../README.md) installs it, from the plugin marketplace, configured with
`claude plugin configure`. Nothing else is in the profile: no `CLAUDE.md`, no memory, no other
plugins. Claude Code's defaults stay as they are, including tool search, which shows the model
only the names of MCP tools until it decides to look one up. The assistant works in a fresh
checkout of [Larder](../evals/trigger/app/), a small shop backend with accounts, orders,
logging, a Segment call and a Postmark email, and a catalogue and front page that hold no data
about people. It talks to a throwaway DPOLens instance with GDPR loaded.

**The tasks.** [held_out.yaml](../evals/trigger/held_out.yaml) holds thirty: twelve coding
tasks that collect, store, log, share or delete data about a person, three questions about the
rules, and fifteen tasks that do not touch personal data, six of them near misses, such as
renaming the column a name is kept in. Each label says why it is what it is. No coding task
names the subject: none says "privacy", "GDPR", "consent" or "compliant", because a task that
did would trigger any assistant and the number would mean nothing. A separate set of twenty,
[tuning.yaml](../evals/trigger/tuning.yaml), is the one to improve the guidance against, and the
held-out set is never used for that.

**What counts.** A run searched if it called `search_policies` or `get_clause`, the two tools
that return clause text. It searched before editing if that came before its first `Edit`,
`Write`, `MultiEdit` or `NotebookEdit`. A run stops once its first search comes back, since the
outcome is known by then. Otherwise it runs until the assistant finishes, 25 turns or ten
minutes. Every run's searches are also counted in the instance's query log, and the two counts
agreed for every run but one. Without the plugin, one run called `search_policies` with no
question at all, before loading the tool's description, and the server refused the call, so it
never reached the log. It counts as a search, because what is measured is whether the assistant
decides to look the rules up, and the run stopped there.

**Runs that could not be scored.** Two runs of one task, `dark-theme`, spent their ten minutes
retrying requests to the model that the network never answered. A run that could not have
reached DPOLens is not a run that chose not to, so both were run again and are reported as
attempts not scored.

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
[evals/trigger/README.md](../evals/trigger/README.md) covers resuming a batch, scoring one again,
and reading the full record each run leaves behind.

## What it does not show

- **Other assistants.** Only Claude Code was measured, on one model, on one date. Cursor and VS
  Code read the same guidance, but how often they act on it has not been measured.
- **Messier work.** The tasks are short, plainly phrased requests in a small app. In a large
  codebase, the code that handles people's data is harder to spot, and requests are rarely this
  clear.
- **Whether the answer changed the code.** A run stops at its first search, so this measures
  whether the assistant looks the rules up, not what it does with what it finds.
- **The labels.** Whether a task should trigger a search is the author's judgment, not a
  regulator's. Each one says why, so a reader who disagrees can see exactly what with.
