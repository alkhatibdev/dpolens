# Configuring an instance

An instance reads the settings on this page from its environment when it starts, and nothing
changes them while it runs. How long questions are kept, and what is taken out of them, are
promises made to the people asking, so changing one takes somebody with access to the
machine, and a restart. The dashboard's Settings page shows the values the instance is
running with.

Which laws apply is not one of them. It is chosen in the dashboard, under Selected laws, and
every change is written to the governance log.

## Changing a setting

With Compose, add the setting to `.env`, next to `compose.yaml`, and start the instance again:

```bash
echo 'DPOLENS_QUERY_LOG_RETENTION_DAYS=180' >> .env
docker compose up -d
```

Compose recreates the services whose settings changed and leaves the others running. A
setting missing from `.env` keeps its default, and [.env.example](../.env.example) lists them
all. Running the API another way, set the same variables in its environment. A value out of
range stops the instance at startup, with a message naming the setting.

## The settings

| Setting | Default | What it does |
| --- | --- | --- |
| `DPOLENS_QUERY_LOG_RETENTION_DAYS` | none | How many days a question is kept before the instance deletes it, counted from the day it was asked. Left unset, questions are kept: they are the organisation's record of what its people needed to know. A new value applies to every question kept, so lowering it deletes the older ones at the next daily run |
| `DPOLENS_REDACTION_PATTERNS` | none | More to take out of a question before it is stored, as names and regular expressions. See below |
| `DPOLENS_SESSION_IDLE_MINUTES` | `30` | How long a dashboard session may go unused before it ends |
| `DPOLENS_SESSION_LIFETIME_HOURS` | `8` | How long a dashboard session lasts at most, however much it is used. At most 168 |
| `DPOLENS_RATE_LIMIT_PER_MINUTE` | `60` | Requests one token may make each minute. Each API worker counts on its own, so an instance running four workers allows four times as many |
| `DPOLENS_INTRA_OP_NUM_THREADS` | `2` | Processor threads one embedding call may use |
| `DPOLENS_PUBLIC_MCP_URL` | `http://localhost:8765/mcp` | The MCP server's address as assistants reach it, shown next to a new token. Set it when the server sits behind a proxy or on another host |
| `DPOLENS_COMMUNITY` | `false` | Run as a community version: the API makes the Community account the MCP server answers everyone as, and setup publishes no sample policy. [mcp.md](mcp.md#a-community-version) says how |
| `DPOLENS_PUBLIC_DASHBOARD_URL` | `http://localhost:8080` | The dashboard's address as people open it, which `dpolens init` names when it is done. Compose sets it from `DPOLENS_DASHBOARD_PORT` |
| `DPOLENS_PACKS_REPOSITORY` | `alkhatibdev/dpolens` | The GitHub repository, as owner and name, whose releases `dpolens pack update` reads. A fork that publishes its own packs is named here. [releases.md](releases.md#law-packs) says how an update works |

These are read by Compose itself:

| Setting | Default | What it does |
| --- | --- | --- |
| `DPOLENS_OWNER_PASSWORD`, `DPOLENS_APP_PASSWORD` | none | The two database passwords. The database keeps the ones it was created with |
| `DPOLENS_API_PORT`, `DPOLENS_DASHBOARD_PORT`, `DPOLENS_MCP_PORT` | `8000`, `8080`, `8765` | Where the API, the dashboard and the MCP server are published on the machine |
| `DPOLENS_MCP_ALLOWED_HOSTS` | `[]` | The host names the MCP server answers to, as a JSON list. Empty means this machine only, and a shared instance names itself here |
| `DPOLENS_VERSION` | the checkout's version | Which release's images Compose runs. A version with no images to download is built from source, which is how a branch built with `--build` gets images of its own. [releases.md](releases.md) says more |

Outside Compose, running the API, the worker or the command line from a source checkout, one
more setting matters:

| Setting | Default | What it does |
| --- | --- | --- |
| `DPOLENS_ORIGINALS_DIR` | `/var/lib/dpolens/originals` | Where uploaded policies' original files are kept. The API, the worker and the command line need the same folder, and need to be able to write to it. Compose mounts a volume there |

Three things are not settings. Five wrong passwords for one address within fifteen minutes
mean a wait before the next try. Each API worker runs at most 7 requests at once, as many as
its 15 database connections can serve at two each, and the others wait their turn rather than
being refused. And every instance takes email addresses, phone numbers,
card numbers, IBANs and Emirates ID numbers out of a question before storing it, which
nothing can switch off.

## The worker

The worker runs what does not belong in a request. When a policy is published, it embeds the
new version's clauses, so that searching by meaning finds them; searching by words finds them
from the start. A policy published while the worker was stopped is embedded when it starts.

When it starts, and then every day at 03:17 UTC, it deletes questions past their retention,
when one is set, sessions that have ended, sign-in links that were used or ran out, and original files no
version points at. An instance that only runs during the day, such as one on a laptop, still
deletes them each time it starts.

It is the same image as the API, started with `dpolens worker`, and Compose runs it as the
`worker` service. It connects as the application role, like the API, and reads the session
settings above, because ending sessions is part of its daily round.

## Taking more out of a question

`DPOLENS_REDACTION_PATTERNS` adds patterns of your own to the ones every instance has, such
as the format of a staff number:

```bash
DPOLENS_REDACTION_PATTERNS='{"staff_id": "EMP-\\d{6}"}'
```

Keep the single quotes in `.env`, so the backslashes, and any `$`, reach the instance as
written. The name is letters, digits and underscores, and it is what the questions log shows
where the pattern took something out, as in `[redacted:staff_id]`. Your patterns run before
the built-in ones, so a format of your own is named as itself rather than as a phone number.

A pattern that is longer than 200 characters, matches empty text or is not a regular
expression at all stops the instance at startup. Each pattern has a tenth of a second for
each question, and one that runs out of time leaves that question as the other patterns
left it, without its name on the row.
