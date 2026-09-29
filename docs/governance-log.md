# The governance log

Every governance action on a DPOLens instance is recorded in one append-only table:
who did it, what they did, what it was done to, and what changed. Each entry
carries a hash of the entry before it, so an entry cannot be edited, removed or
reordered without the chain saying so.

This page is the specification. It describes the hash exactly enough to be
reimplemented in another language, because an export that only DPOLens can check
is not evidence of anything.

## What is recorded

Creating a user, assigning or removing a role, deactivating an account, creating
or changing a role's permissions, publishing a document version, creating or
revoking a token, viewing who asked a question in the query log, and exporting
this log.

The governance log is not the query log, and neither is telemetry. The query log
holds redacted questions and expires on a retention schedule. Telemetry is the
application's own output on stdout and never carries the text of a question, a
clause or a document.

## What an entry holds

| Field | What it is |
| --- | --- |
| `seq` | Sequence number, assigned by the database. It orders the table |
| `occurred_at` | When the action happened, UTC, microsecond precision |
| `actor_user_id` | Who acted, or null for an action taken with shell access |
| `actor_pat_id` | Which personal access token was used, when one was |
| `action` | What happened, for example `user.role_granted` |
| `target_type`, `target_id` | What it happened to |
| `details` | Before and after values, as JSON |
| `prev_hash` | The hash of the entry before this one |
| `entry_hash` | This entry's hash |
| `hash_version` | Which recipe produced `entry_hash`. Currently 1 |

A user is named by id, never by email address. Identities live in one file of an
export, so the part that gets verified carries no personal data and an erasure
request cannot break the chain.

An action taken from the command line has no `actor_user_id`. Whoever holds the
database URL is outside the identity system, so an entry naming a person there
would be a claim nothing supports. The `details` of such an entry record
`"via": "cli"` with the operating system user and hostname, which is what can
honestly be known.

## Hash recipe, version 1

For each entry, take SHA-256 over these nine fields, concatenated in this order.
Each field is prefixed by its length in bytes, as eight bytes big-endian.

1. the hash version, as decimal digits (`1`)
2. `prev_hash`, raw bytes
3. `occurred_at`, as `YYYY-MM-DDTHH:MM:SS.ffffffZ` in UTC, always six fractional
   digits
4. `actor_user_id`, canonical uuid text, or a zero-length field when there is none
5. `actor_pat_id`, the same
6. `action`
7. `target_type`
8. `target_id`
9. `details`, the exact JSON text that was stored

Text fields are UTF-8. The length prefixes are what make the concatenation
unambiguous: without them, moving a character from one field into the next would
leave the hash unchanged.

`details` is stored in a PostgreSQL `json` column rather than `jsonb`, because
`json` keeps the input text exactly as it was written. The text is compact JSON:
keys in the order the code wrote them, no whitespace, no escaping of non-ASCII
characters. A verifier reading from the database should ask for `details::text`
and hash that, rather than parsing and re-serialising.

The first entry's `prev_hash` is SHA-256 of this instance's id, as canonical uuid
text. That is why a chain from one instance cannot be presented as another's.

## Verifying

```bash
dpolens governance verify
```

This recomputes every entry's hash, checks that the links form one chain starting
at the instance's first link, and reports the first entry that does not match.

Two findings are reported separately, because they mean different things. An entry
whose fields do not match its own hash has been edited. Entries whose links do not
line up with their sequence numbers were written in an order the numbers disagree
with.

The command also says when the connection it used could change the log at all.
Verification proves the rows have not been edited; whether they could be depends
on the privileges of the role in use. On a deployed instance the application
connects as a role holding `INSERT` and `SELECT` on this table and nothing else.

## Exporting for an auditor

```bash
dpolens governance export ./export-2026-09
dpolens governance verify --export ./export-2026-09
```

The directory holds three files:

- `entries.jsonl`, one entry per line, in sequence order. This is the part that
  gets verified, and it holds ids rather than names
- `manifest.json`, the range, the count, the instance id, the recipe version, the
  first link, the final hash, and whether the range reaches the first entry ever
  written
- `actors.json`, mapping user ids to the names, addresses, kinds and statuses they
  had when the export was written

A range can be exported with `--from-seq` and `--to-seq`. The manifest then says
`anchored_to_genesis: false`, and verification repeats that in its output rather
than implying it checked more than it did.

`verify --export` reads only these files. It also checks the manifest against the
entries, because a manifest is evidence too.

The export itself is recorded in the log, after the rows were read, so an export
never contains its own entry.

## What the chain does and does not prove

It proves that the entries in front of you have not been edited, removed or
reordered since they were written, and that they come from this instance.

It does not prove that what was written was true, and it does not stop somebody
who owns the database from dropping the table. The privileges make that a
deliberate act by a specific role rather than something the application can do by
accident, and an export held elsewhere is what makes the loss visible.
