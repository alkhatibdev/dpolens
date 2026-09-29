"""The two logs, which are product features rather than application output.

The governance log is append-only and hash-chained; the query log is redacted
and expires. Neither is telemetry, which is `dpolens.telemetry` and never
carries the text of a question.
"""
