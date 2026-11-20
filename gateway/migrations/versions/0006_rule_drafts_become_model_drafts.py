"""tools once drafted by rules count as model drafts: only the model drafts ratings now"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Both are unreviewed drafts, and the review note still says how the tool was flagged.
    op.execute(
        "UPDATE tools SET rating_source = 'model_drafted' WHERE rating_source = 'heuristic_draft'"
    )


def downgrade() -> None:
    raise NotImplementedError("Which drafts were made by rules is no longer recorded.")
