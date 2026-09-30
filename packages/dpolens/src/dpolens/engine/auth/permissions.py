"""The permission catalog: eleven strings, defined here and nowhere else.

Permissions live in code and roles live in data. The lookup table in
the database exists so `role_permissions` can point at a foreign key rather than
at free text, and it is synced from this file.

Adding a permission here is a release. Removing one that a role still holds
stops the instance, because the alternative is somebody silently losing access.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from types import MappingProxyType

DOCUMENTS_READ = "documents.read"
DOCUMENTS_UPLOAD = "documents.upload"
DOCUMENTS_PUBLISH = "documents.publish"
QUERIES_READ_OWN = "queries.read_own"
QUERIES_READ_ALL = "queries.read_all"
QUERIES_READ_IDENTITIES = "queries.read_identities"
GOVERNANCE_READ = "governance.read"
ROLES_MANAGE = "roles.manage"
USERS_MANAGE = "users.manage"
TOKENS_CREATE = "tokens.create"
SETTINGS_MANAGE = "settings.manage"

PERMISSIONS: Mapping[str, str] = MappingProxyType(
    {
        DOCUMENTS_READ: "Search the corpus and read any clause of it",
        DOCUMENTS_UPLOAD: "Upload an organisation policy and review how it was parsed",
        DOCUMENTS_PUBLISH: "Publish a reviewed draft, which fixes its text for citation",
        QUERIES_READ_OWN: "Read one's own entries in the query log",
        QUERIES_READ_ALL: "Read every query log entry, with the asker's identity hidden",
        QUERIES_READ_IDENTITIES: "See who asked a logged question, which is itself logged",
        GOVERNANCE_READ: "Read and export the governance log",
        ROLES_MANAGE: "Create roles and change which permissions they carry",
        USERS_MANAGE: "Create users, assign roles, deactivate accounts",
        TOKENS_CREATE: "Create personal access tokens for oneself",
        SETTINGS_MANAGE: "Change instance settings, including which laws apply",
    }
)

ADMIN = "Admin"
DPO = "DPO"
DEVELOPER = "Developer"

SEEDED_ROLES: Mapping[str, frozenset[str]] = MappingProxyType(
    {
        ADMIN: frozenset(PERMISSIONS),
        # Everything the second user needs, without the two that belong to an
        # administrator, and without `queries.read_identities`: seeing who asked
        # what starts off, so its first use is a decision somebody made.
        DPO: frozenset(
            {
                DOCUMENTS_READ,
                DOCUMENTS_UPLOAD,
                DOCUMENTS_PUBLISH,
                QUERIES_READ_ALL,
                GOVERNANCE_READ,
                SETTINGS_MANAGE,
                TOKENS_CREATE,
            }
        ),
        # The hero user reads the corpus and mints the token their editor uses.
        DEVELOPER: frozenset({DOCUMENTS_READ, QUERIES_READ_OWN, TOKENS_CREATE}),
    }
)

SEEDED_ROLE_DESCRIPTIONS: Mapping[str, str] = MappingProxyType(
    {
        ADMIN: "Runs the instance: users, roles, settings and both logs",
        DPO: "Owns the policies and reads the logs",
        DEVELOPER: "Reads the corpus through an editor, and their own questions",
    }
)


def unknown(keys: Iterable[str]) -> tuple[str, ...]:
    """Which of these are not in the catalog, sorted, for a message that names them."""
    return tuple(sorted(set(keys) - set(PERMISSIONS)))
