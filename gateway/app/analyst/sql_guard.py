"""Makes model-written SQL safe to run: one SELECT, over the analyst views only, calling
only known functions, with a row limit. The database enforces the same from its side: the
query runs on a connection that logs in as a role that can read three views and nothing else."""

import string

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError
from sqlglot.optimizer.scope import build_scope

ALLOWED_VIEWS = frozenset({"v_events", "v_tools", "v_teams"})
MAX_ROWS = 500
# Functions the SQL parser does not model. Anything else it does not know is refused, which
# keeps out `set_config`, `query_to_xml`, `pg_read_file`, `dblink`, `pg_sleep` and the like.
ALLOWED_FUNCTIONS = frozenset(
    {
        "age",
        "array_length",
        "array_position",
        "cardinality",
        "date_part",
        "initcap",
        "justify_days",
        "percentile_cont",
        "percentile_disc",
        "to_char",
        "width_bucket",
    }
)
_FOLD = str.maketrans(string.ascii_uppercase, string.ascii_lowercase)


class UnsafeSqlError(ValueError):
    """The SQL is not a single read-only query over the analyst views."""


def _as_resolved(query: exp.Query) -> exp.Query:
    """A copy with every name spelled as the database resolves it: an unquoted name in lower
    case, a quoted one as written. `"PG_ROLES"` and `PG_ROLES` are then two names here too."""
    resolved = query.copy()
    for identifier in resolved.find_all(exp.Identifier):
        if not identifier.quoted:
            identifier.set("this", identifier.this.translate(_FOLD))
    return resolved


def _check_tables(query: exp.Query) -> None:
    """Every table must be a view, or a CTE that is in scope where the table is read."""
    query = _as_resolved(query)
    root = build_scope(query)
    ctes_in_scope = {
        id(table): scope.cte_sources.keys()
        for scope in (root.traverse() if root else ())
        for table in scope.tables
    }
    for table in query.find_all(exp.Table):
        qualified = bool(table.db or table.catalog)
        # A table the scope walk did not reach has no CTE in scope, so it has to be a view.
        local = not qualified and table.name in ctes_in_scope.get(id(table), ())
        if not local and (qualified or table.name not in ALLOWED_VIEWS):
            raise UnsafeSqlError(
                f"Only {', '.join(sorted(ALLOWED_VIEWS))} can be queried, not {table.sql()}"
            )


def guard(sql: str) -> str:
    """Return the query with a row limit, or raise `UnsafeSqlError`."""
    try:
        statements = sqlglot.parse(sql, read="postgres")
    except SqlglotError as exc:
        raise UnsafeSqlError(f"The SQL could not be parsed: {exc}") from exc
    if len(statements) != 1 or statements[0] is None:
        raise UnsafeSqlError("Exactly one statement is allowed")
    query = statements[0]
    if not isinstance(query, exp.Select | exp.Union):
        raise UnsafeSqlError("Only SELECT is allowed")
    if any(query.find_all(exp.Insert, exp.Update, exp.Delete, exp.Into, exp.Command, exp.Lock)):
        raise UnsafeSqlError("Only SELECT is allowed")

    for function in query.find_all(exp.Anonymous):
        if function.name.lower() not in ALLOWED_FUNCTIONS:
            raise UnsafeSqlError(f"The function {function.name} is not allowed")

    _check_tables(query)

    limit = query.args.get("limit")
    current = limit.expression if isinstance(limit, exp.Limit) else None
    too_many = not isinstance(current, exp.Literal) or int(current.this) > MAX_ROWS
    if too_many:
        query = query.limit(MAX_ROWS)
    return query.sql(dialect="postgres")
