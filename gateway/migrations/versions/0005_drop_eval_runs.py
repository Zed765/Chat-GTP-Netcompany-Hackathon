"""drop evaluation runs: the evaluation is a command-line tool and writes a file"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("eval_runs")


def downgrade() -> None:
    raise NotImplementedError("The runs are gone; the results files are in eval/results.")
