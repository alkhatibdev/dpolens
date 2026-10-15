"""Alembic environment.

The database URL comes from the instance settings unless one is passed in, so
migrations and the running application can never disagree about which database
they mean. When a separate migration URL is configured, that one is used and the
application's own role is passed to the migrations, which grant to it by name.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from alembic.util import CommandError
from sqlalchemy import engine_from_config, pool

# The model modules are imported for their side effect: every one of them has to
# be loaded for `Base.metadata` to describe the whole schema.
from dpolens.engine import instance as instance_models  # noqa: F401
from dpolens.engine.auth import models as auth_models  # noqa: F401
from dpolens.engine.base import Base
from dpolens.engine.documents import models as document_models  # noqa: F401
from dpolens.engine.logs import models as log_models  # noqa: F401
from dpolens.engine.session import DatabaseUnavailable, connect
from dpolens.settings import load_settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

if not config.get_main_option("sqlalchemy.url", None):
    settings = load_settings()
    if settings.migration_database_url is not None:
        config.set_main_option("sqlalchemy.url", str(settings.migration_database_url))
        # Granting to the role the application connects as, read from its own
        # URL so the name is spelled in one place only.
        config.attributes.setdefault("app_role", settings.app_role)
    else:
        config.set_main_option("sqlalchemy.url", str(settings.database_url))

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    # Alembic prints a CommandError as one line, where anything else is a
    # traceback, and this is the first thing an instance does when it starts.
    try:
        connection = connect(connectable)
    except DatabaseUnavailable as unavailable:
        raise CommandError(str(unavailable)) from unavailable
    with connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            try:
                context.run_migrations()
            except CommandError as failed:
                ahead = ahead_of_the_code()
                if ahead is None:
                    raise
                raise ahead from failed


def ahead_of_the_code() -> CommandError | None:
    """Say so when a later version of DPOLens has migrated this database.

    Alembic's own words for it are that it cannot locate a revision, which reads
    like a broken install rather than a database that is ahead of the code. Only
    asked once a command has failed, so `alembic stamp --purge` still works.
    """
    known = {script.revision for script in context.script.walk_revisions()}
    ahead = sorted(set(context.get_context().get_current_heads()) - known)
    if not ahead:
        return None
    return CommandError(
        f"this database's schema is at revision {', '.join(ahead)}, which this version "
        "of DPOLens does not have, so a later version set it up. Run that version or a "
        "newer one: an older one cannot use this database."
    )


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
