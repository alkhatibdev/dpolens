"""The HTTP API: the only way into DPOLens.

Handlers authenticate, check permissions, call one engine function, record the
request and return. Building a query here means logic has leaked upward.
"""
