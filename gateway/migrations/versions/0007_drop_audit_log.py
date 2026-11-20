"""drop the audit log: nothing records who changed or looked up what any more"""

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The table takes its index and its two triggers with it; the function they called stays.
    op.drop_table("audit_log")
    op.execute("DROP FUNCTION audit_log_is_append_only")


def downgrade() -> None:
    raise NotImplementedError("The entries are gone; restore from a backup instead.")
