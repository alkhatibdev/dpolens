# The trigger test

The retrieval evals measure whether search finds the right clause once an AI assistant asks. This
measures whether it asks: how often Claude Code calls DPOLens on its own when the work in front
of it touches personal data, and how often it calls when the work does not. It also runs Qwen Code,
with any model served through an OpenAI-compatible API, such as a small model on your own machine.

## What is here

| Path | What it is |
| --- | --- |
| `tuning.yaml` | 20 tasks used while improving the guidance DPOLens gives an AI assistant |
| `held_out.yaml` | 30 tasks that produce the published number and are never used to change anything |
| `app/` | Larder, the small TypeScript shop every task runs against |
| `container/` | The container one run happens in, one for each AI assistant |
| `../../scripts/run_trigger_test.py` | The runner |

## A task

```yaml
- id: log-failed-logins
  kind: coding
  should_search: true
  verb: log
  prompt: >-
    Log failed logins with the email that was tried and the client IP, so we can spot
    credential stuffing.
  reason: Writes email addresses and IP addresses into logs that are kept and read by other people.
  note: https://github.com/dani-garcia/vaultwarden/issues/119
```

| Field | Meaning |
| --- | --- |
| `id` | Unique across both sets |
| `kind` | `coding` for a change to the app, `question` for a question about the rules |
| `should_search` | Whether a careful developer would look the rules up first. This is the author's judgment, not a regulator's |
| `verb` | For a task that should search: what it does with data about a person, one of collect, store, log, share, delete or access |
| `near_miss` | For a task that should not search: work in code that handles people, which changes nothing about their data |
| `prompt` | What the developer types, phrased the way they would |
| `reason` | Why the label is what it is, so a reader who disagrees can see what with |
| `note` | A real thread a phrasing was learned from, when there is one. Phrasings are rewritten, never copied |

A set is half tasks that should search and half that should not. The ones that should search
cover every verb, the ones that should not include near misses, and a few questions about the
rules sit in their own group. A coding task never names the subject: no "personal data",
"privacy", "GDPR", "policy", "consent", "law", "legal" or "compliant". A task that says "make
this compliant" would trigger any AI assistant and the number would mean nothing.
`tests/unit/test_trigger_tasks.py` checks all of this.

## What a run is

Every run is a new container: the AI assistant at a pinned version (Claude Code 2.1.288 or
Qwen Code 0.27.4), a fresh checkout of Larder with its dependencies installed, and an empty
profile with DPOLens installed. Claude Code gets it the way
[Get started](https://dpolens.com/docs/get-started) installs it, from the plugin marketplace,
with `claude plugin configure`. Qwen Code gets the MCP server on its own, as the entry
`qwen mcp add` writes, beside settings that name the model and its server. Nothing else is in the
profile: no `CLAUDE.md` or `QWEN.md`, no memory, no other plugins. The runs talk to a throwaway
DPOLens instance built from your checkout, with every pack in it loaded, which is removed
afterwards.

A run counts as a call when the AI assistant calls `search_policies` or `get_clause`, the two
tools that return clause text. It counts as a call before editing when that happens before its
first edit: `Edit`, `Write`, `MultiEdit` or `NotebookEdit` in Claude Code, and `edit`,
`write_file` or `notebook_edit` in Qwen Code. Qwen Code keeps MCP tools out of the prompt until
the model looks one up, so a search can also come through its `tool_call` tool, and counts the
same. A run stops as soon as the first call comes back, since the outcome is known by then.
Otherwise it goes until the AI assistant finishes, 25 turns or 10 minutes. With
`--stop-at-edit`, a run also stops at its first edit, when whether it searched before editing is
known: runs stay short on a slow model, and the batch cannot say what a run would have done after.

A run that could not have called DPOLens is retried rather than scored: the plugin not loading,
the MCP server not connecting, or the request to the model failing. Each run's calls are also
counted in the instance's query log, and the report names any run where the two counts differ.
It also names a run whose deciding search came back as an error, which means the instance could
not answer and keeps the batch from being published, and apart from it, a run whose search asked
no question at all. The server refuses that one whatever the instance holds, and it still counts
as the decision to search.

## Running it

For Claude Code you need Docker and either a Claude subscription or an API key.

```bash
claude setup-token        # prints a one-year token for your subscription
```

Save the token to `evals/trigger/.oauth-token`, which git ignores, readable only by you
(`chmod 600`). Without that file, the runner uses `ANTHROPIC_API_KEY` if it is set.

```bash
uv run python scripts/run_trigger_test.py --set tuning
uv run python scripts/run_trigger_test.py --set held_out --runs 3 --max-runs 90 --model <id>
uv run python scripts/run_trigger_test.py --set held_out --runs 3 --max-runs 90 --model <id> \
  --setup mcp-only
```

The first command runs each tuning task once. A held-out batch has to name its model, because
the number it produces is published with it. `--setup mcp-only` adds the MCP server on its own
with no plugin, which shows how much the plugin's skill adds. `--max-runs` is a guard against
starting a larger batch than you meant to: a full held-out batch is 90 runs.

Everything a batch produces is kept in `evals/trigger/runs/<batch>/`, also ignored: the outcome
of every run, and the full stream of events from each one, which is where to look when a task
did something unexpected. A batch stopped by a usage limit resumes with
`--batch <batch>`, and `--report <batch>` scores one again without running anything.

`--write held_out-plugin,held_out-mcp-only` writes `evals/results/trigger.json`, Claude Code's
number, from held-out batches, and refuses one that is incomplete, ran on an unpinned model,
stopped its runs at their first edit, or disagrees with the others about the model or the version
of Claude Code.

Building the instance asks the image registries about base images, so a network that cannot
reach them stops a batch before it starts. `--reuse-images` starts from the images already
built instead, after checking that every file they copy from the repository is the same as in
your checkout, and refuses otherwise. The instance's images are built as `trigger-test`, never
as a release's number, so a batch leaves the images of every release on your machine as they
were. The instance chooses GDPR as the law that applies when it starts, since an instance
searches nothing until its laws are chosen. A search that comes back as an error is named in the
report, and `--write` refuses a batch that has one.

When a rule turns out to have been applied wrongly to recorded runs, `--reread <batch>` applies
the rule as it now stands to each run's saved stream of events. What was recorded first is kept
in `outcomes.recorded.jsonl`, and any run that should not have been scored is run again by the
next resume.

### With Qwen Code

Qwen Code talks to any server with an OpenAI-compatible API whose model can call tools, such as
llama.cpp, LM Studio, Ollama, oMLX or vLLM. Name the model as the server lists it, and the server
as the container reaches it: your own machine is `host.docker.internal`.

```bash
export OPENAI_API_KEY=<the server's key>    # any value when it needs none
uv run python scripts/run_trigger_test.py --client qwen-code --set held_out --max-runs 30 \
  --model <id> --base-url http://host.docker.internal:<port>/v1 \
  --sampling temperature=0.6,top_p=0.95,top_k=20 --context-window 262144 --stop-at-edit
```

`--sampling` is sent with every request in place of the server's own choice, so give the values
the model's card recommends. `--context-window` tells Qwen Code how much context the server gives
the model. Both are kept with the batch, and resuming it takes the same.

## Reading the number

The report gives two rates: the share of runs that searched on tasks that should, and on tasks
that should not. Each comes with a 95% interval that resamples tasks with all of their runs
together, since three runs of one task are not three tasks. It also gives how many of the
tasks that should search did so before editing, and how consistent each task was: searched in
every run, in none, or in some.

The second rate is the cost of the first. An AI assistant that searched before every task would
score perfectly on the first and be a nuisance, which is why both are published.
