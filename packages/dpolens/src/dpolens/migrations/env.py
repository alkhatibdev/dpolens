"""Alembic environment.

The database URL comes from the instance settings unless one is passed in, so
migrations and the running application can never disagree about which database
they mean. When a separate migration URL is configured, that one is used and the
application's own role is passed to the migrations, which grant to it by name.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# The model modules are imported for their side effect: every one of them has to
# be loaded for `Base.metadata` to describe the whole schema.
from dpolens.engine import instance as instance_models  # noqa: F401
from dpolens.engine.auth import models as auth_models  # noqa: F401
from dpolens.engine.base import Base
from dpolens.engine.documents import models as document_models  # noqa: F401
from dpolens.engine.logs import models as log_models  # noqa: F401
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
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
