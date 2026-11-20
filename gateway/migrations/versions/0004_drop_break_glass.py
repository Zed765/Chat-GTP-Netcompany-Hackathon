"""drop break-glass requests: an admin looks identities up directly"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("break_glass_requests")


def downgrade() -> None:
    raise NotImplementedError("The requests are gone; restore from a backup instead.")
