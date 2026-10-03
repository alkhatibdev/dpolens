"""Users, roles, the permission lookup table and the governance log

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The application never updates or deletes a governance entry, so the privileges
# say it cannot. The trigger refuses for everybody, including the owner, because
# a privilege can be granted back by whoever holds the table and a dropped
# trigger is a visible change rather than a quiet one.
APPEND_ONLY = """
CREATE OR REPLACE FUNCTION reject_governance_change() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION
        'the governance log is append-only: % is not allowed on %', TG_OP, TG_TABLE_NAME
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;
"""


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def upgrade() -> None:
    op.create_table(
        "instance",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        # One row, enforced by the database: unique over a column that can only
        # ever hold true.
        sa.Column("singleton", sa.Boolean(), nullable=False, server_default=sa.true(), unique=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("singleton", name="instance_is_one_row"),
    )
    # The id is what the governance chain's first link is built from, so it is
    # written here, once, rather than by whichever surface starts first.
    op.execute("INSERT INTO instance (id, singleton) VALUES (gen_random_uuid(), true)")

    op.create_table(
        "permissions",
        sa.Column("key", sa.String(50), primary_key=True),
        sa.Column("description", sa.Text(), nullable=False),
    )

    op.create_table(
        "roles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("is_seeded", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )

    op.create_table(
        "role_permissions",
        sa.Column(
            "role_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("roles.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "permission_key",
            sa.String(50),
            sa.ForeignKey("permissions.key"),
            primary_key=True,
        ),
    )

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("display_name", sa.Text(), nullable=False),
        # Null until the dashboard exists, and always null for a service
        # account.
        sa.Column("password_hash", sa.Text(), nullable=True),
        sa.Column(
            "kind",
            sa.Enum("person", "service_account", name="user_kind"),
            nullable=False,
            server_default="person",
        ),
        sa.Column(
            "status",
            sa.Enum("active", "deactivated", "erased", name="user_status"),
            nullable=False,
            server_default="active",
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "user_roles",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            primary_key=True,
        ),
        sa.Column(
            "role_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("roles.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )

    op.create_table(
        "governance_log",
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "actor_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        # The foreign key to personal_access_tokens is added by the migration
        # that creates that table. The column is here now because it is inside
        # the hash, and adding a hashed field later would mean a second recipe.
        sa.Column("actor_pat_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("target_type", sa.Text(), nullable=False),
        sa.Column("target_id", sa.Text(), nullable=False),
        # `json`, not `jsonb`: it stores the input text exactly, and the hash
        # covers that text.
        sa.Column("details", postgresql.JSON(), nullable=False),
        sa.Column("prev_hash", sa.LargeBinary(), nullable=False),
        sa.Column("entry_hash", sa.LargeBinary(), nullable=False, unique=True),
        sa.Column("hash_version", sa.SmallInteger(), nullable=False),
    )
    op.create_index("ix_governance_log_action", "governance_log", ["action", "seq"])
    op.create_index("ix_governance_log_actor", "governance_log", ["actor_user_id", "seq"])

    op.execute(APPEND_ONLY)
    op.execute(
        """
        CREATE TRIGGER governance_log_is_append_only
        BEFORE UPDATE OR DELETE ON governance_log
        FOR EACH ROW EXECUTE FUNCTION reject_governance_change();
        """
    )
    # A row trigger never sees TRUNCATE, which would take the whole table in one
    # statement, so the guard needs a statement trigger as well.
    op.execute(
        """
        CREATE TRIGGER governance_log_is_not_truncatable
        BEFORE TRUNCATE ON governance_log
        FOR EACH STATEMENT EXECUTE FUNCTION reject_governance_change();
        """
    )

    _grant_to_application_role()


def _grant_to_application_role() -> None:
    """Give the application role what it needs, and less on the governance log.

    The role is never created here: roles are cluster-wide, so creating one
    reaches every other database in the cluster and needs a password from
    somewhere. Compose's init script creates it, and this only grants.
    """
    app_role = context.config.attributes.get("app_role")
    if not app_role:
        print(
            "0004: no application role configured, so no grants were made. "
            "The API refuses to start against a database where it can update "
            "the governance log."
        )
        return

    current = op.get_bind().exec_driver_sql("SELECT current_user").scalar_one()
    if app_role == current:
        print(
            f"0004: the application role {app_role!r} owns these tables, so the "
            "append-only privileges cannot apply to it. Migrate as a separate role."
        )
        return

    role = _quote(app_role)
    op.execute(f"GRANT USAGE ON SCHEMA public TO {role}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {role}")
    op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {role}")
    # Later migrations add tables. Default privileges mean each one is reachable
    # without remembering to grant on it.
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {role}"
    )
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {role}"
    )
    op.execute(f"REVOKE UPDATE, DELETE, TRUNCATE ON governance_log FROM {role}")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS governance_log_is_not_truncatable ON governance_log")
    op.execute("DROP TRIGGER IF EXISTS governance_log_is_append_only ON governance_log")
    op.execute("DROP FUNCTION IF EXISTS reject_governance_change()")

    op.drop_table("governance_log")
    op.drop_table("user_roles")
    op.drop_table("users")
    op.drop_table("role_permissions")
    op.drop_table("roles")
    op.drop_table("permissions")
    op.drop_table("instance")

    for enum in ("user_status", "user_kind"):
        op.execute(f"DROP TYPE IF EXISTS {enum}")
