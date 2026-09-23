"""The engine: everything DPOLens knows how to do.

Organised by subject, with SQLAlchemy hidden behind a handful of functions per
subject. Only tests and the eval harness import it directly; user-facing
surfaces go through the HTTP API.
"""
