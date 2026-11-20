import pytest

from gateway.app.analyst.ask import run_readonly
from gateway.app.analyst.questions import EXAMPLES
from gateway.app.analyst.sql_guard import MAX_ROWS, UnsafeSqlError, guard
from gateway.tests.conftest import Api

# Every query here reads a relation that is not one of the three views. The name is hidden
# behind a CTE of the same name that is not in scope where the relation is read, or sits in a
# clause of its own.
REFUSED = {
    "cte in a derived table, relation beside it": (
        "SELECT r.rolname FROM (WITH pg_roles AS (SELECT 1 AS x) SELECT x FROM pg_roles) s, "
        "pg_roles r"
    ),
    "cte defined after the cte that reads the table": (
        "WITH a AS (SELECT * FROM events), events AS (SELECT 1) SELECT * FROM a"
    ),
    "cte that reads the table it is named after": (
        "WITH events AS (SELECT * FROM events) SELECT * FROM events"
    ),
    "cte named like a view over a table": (
        "WITH v_events AS (SELECT * FROM events) SELECT * FROM v_events"
    ),
    "cte named like a view, relation beside it": (
        "SELECT * FROM (WITH v_teams AS (SELECT 1 AS x) SELECT x FROM v_teams) s, pg_class c"
    ),
    "cte named like a view, defined after its reader": (
        "WITH a AS (SELECT * FROM v_tools JOIN pg_settings ON true), "
        "pg_settings AS (SELECT 1) SELECT * FROM a"
    ),
    "nested cte reads a table": (
        "WITH a AS (WITH b AS (SELECT * FROM pg_proc) SELECT * FROM b) SELECT * FROM a"
    ),
    "nested cte, relation outside the nesting": (
        "WITH a AS (WITH events AS (SELECT 1 AS x) SELECT x FROM events) SELECT * FROM a, events"
    ),
    "nested cte, relation in a sibling cte": (
        "WITH a AS (WITH pg_views AS (SELECT 1 AS x) SELECT x FROM pg_views), "
        "b AS (SELECT viewname FROM pg_views) SELECT * FROM a, b"
    ),
    "cte of a subquery, relation in the outer query": (
        "SELECT team FROM v_teams WHERE EXISTS (WITH pg_roles AS (SELECT 1) SELECT 1 FROM pg_roles)"
        " AND team IN (SELECT rolname FROM pg_roles)"
    ),
    "cte of one subquery, relation in another": (
        "SELECT (WITH events AS (SELECT 1 AS x) SELECT x FROM events), "
        "(SELECT count(*) FROM events) FROM v_teams"
    ),
    "cte of one arm of a union, relation in the other": (
        "(WITH events AS (SELECT 1 AS x) SELECT x FROM events) UNION ALL SELECT 1 FROM events"
    ),
    "quoted cte name that an unquoted name does not match": (
        'WITH "PG_ROLES" AS (SELECT 1 AS x) SELECT * FROM PG_ROLES'
    ),
    "unquoted cte name that a quoted name does not match": (
        'WITH Events AS (SELECT 1 AS x) SELECT * FROM "Events"'
    ),
    "cte name with the relation schema-qualified": (
        "WITH events AS (SELECT 1 AS x) SELECT * FROM public.events"
    ),
    "subquery in the select list": "SELECT (SELECT count(*) FROM events) FROM v_teams",
    "subquery in from": "SELECT * FROM (SELECT * FROM directory_users) AS a",
    "subquery in a join condition": (
        "SELECT * FROM v_teams JOIN v_tools ON EXISTS (SELECT 1 FROM pg_roles)"
    ),
    "subquery in where": "SELECT * FROM v_teams WHERE team IN (SELECT rolname FROM pg_roles)",
    "subquery in an array constructor": (
        "SELECT * FROM v_teams WHERE team = ANY(ARRAY(SELECT rolname FROM pg_roles))"
    ),
    "subquery in group by": (
        "SELECT count(*) FROM v_teams GROUP BY (SELECT rolname FROM pg_roles LIMIT 1)"
    ),
    "subquery in having": (
        "SELECT team FROM v_teams GROUP BY team HAVING count(*) > (SELECT count(*) FROM pg_roles)"
    ),
    "subquery in order by": "SELECT * FROM v_teams ORDER BY (SELECT 1 FROM pg_roles LIMIT 1)",
    "subquery in limit": "SELECT * FROM v_teams LIMIT (SELECT count(*) FROM pg_roles)",
    "subquery in offset": "SELECT * FROM v_teams OFFSET (SELECT count(*) FROM pg_roles)",
    "subquery in an aggregate filter": (
        "SELECT count(*) FILTER (WHERE EXISTS (SELECT 1 FROM pg_roles)) FROM v_teams"
    ),
    "subquery in a window": (
        "SELECT sum(1) OVER (ORDER BY (SELECT 1 FROM pg_roles LIMIT 1)) FROM v_teams"
    ),
    "subquery in a case": (
        "SELECT CASE WHEN true THEN (SELECT rolname FROM pg_roles LIMIT 1) END FROM v_teams"
    ),
    "subquery in a function argument": (
        "SELECT coalesce((SELECT rolname FROM pg_roles LIMIT 1), team) FROM v_teams"
    ),
    "subquery in values": "SELECT * FROM (VALUES ((SELECT rolname FROM pg_roles LIMIT 1))) v",
    "subquery in unnest": "SELECT * FROM unnest(ARRAY(SELECT rolname FROM pg_roles)) u",
    "lateral subquery": "SELECT * FROM v_teams t, LATERAL (SELECT rolname FROM pg_roles) r",
    "lateral join": "SELECT * FROM v_teams t LEFT JOIN LATERAL (SELECT * FROM events) e ON true",
    "cte of a lateral subquery, relation beside it": (
        "SELECT * FROM v_teams t, "
        "LATERAL (WITH pg_roles AS (SELECT 1 AS x) SELECT x FROM pg_roles) l, pg_roles"
    ),
    "union": "SELECT team FROM v_teams UNION SELECT rolname FROM pg_roles",
    "union all in parentheses": "SELECT team FROM v_teams UNION ALL (SELECT rolname FROM pg_roles)",
    "union inside a cte": (
        "WITH a AS (SELECT team FROM v_teams UNION SELECT rolname FROM pg_roles) SELECT * FROM a"
    ),
    "intersect in a subquery": (
        "SELECT * FROM (SELECT team FROM v_teams INTERSECT SELECT rolname FROM pg_roles) s"
    ),
    "except in a subquery": (
        "SELECT * FROM (SELECT rolname FROM pg_roles EXCEPT SELECT team FROM v_teams) s"
    ),
    "limit of a union": (
        "SELECT team FROM v_teams UNION SELECT team FROM v_teams "
        "LIMIT (SELECT count(*) FROM pg_roles)"
    ),
    "cte of a union, relation shadowed in one arm only": (
        "SELECT team FROM v_teams UNION ALL "
        "SELECT x FROM (WITH events AS (SELECT 'a' AS x) SELECT x FROM events) s, events"
    ),
}

ALLOWED = {
    **{example.question: example.sql for example in EXAMPLES},
    "cte over a view": "WITH busy AS (SELECT team FROM v_events) SELECT count(*) FROM busy",
    "cte that reads an earlier cte": (
        "WITH per_team AS (SELECT team, count(*) AS n FROM v_events GROUP BY team), "
        "busy AS (SELECT team FROM per_team WHERE n > 1) "
        "SELECT t.team, t.events_14d FROM v_teams t JOIN busy ON busy.team = t.team"
    ),
    "cte read from a subquery": (
        "WITH busy AS (SELECT team FROM v_events) "
        "SELECT * FROM v_teams WHERE team IN (SELECT team FROM busy)"
    ),
    "cte read from a derived table": (
        "WITH used AS (SELECT tool FROM v_events) "
        "SELECT s.tool FROM (SELECT tool FROM used GROUP BY tool) s"
    ),
    "cte read from both arms of a union": (
        "WITH names AS (SELECT team AS name FROM v_teams) "
        "SELECT name FROM names UNION ALL SELECT name FROM names"
    ),
    "cte read from a lateral subquery": (
        "WITH recent AS (SELECT team FROM v_events WHERE ts >= now() - interval '7 days') "
        "SELECT t.team, l.n FROM v_teams t, "
        "LATERAL (SELECT count(*) AS n FROM recent WHERE recent.team = t.team) l"
    ),
    "nested cte": (
        "WITH outside AS (WITH inside AS (SELECT tool FROM v_tools) SELECT tool FROM inside) "
        "SELECT * FROM outside"
    ),
    "inner cte that reads an outer one": (
        "WITH per_tool AS (SELECT tool, count(*) AS n FROM v_events GROUP BY tool) "
        "SELECT * FROM (WITH top AS (SELECT tool FROM per_tool WHERE n > 0) SELECT * FROM top) s"
    ),
    "cte with the name of a view, over views": (
        "WITH v_teams AS (SELECT team FROM v_events GROUP BY team) SELECT team FROM v_teams"
    ),
    "names in another case": "SELECT Team FROM V_TEAMS",
    "quoted view name": 'SELECT team FROM "v_teams"',
    "all three views": (
        "SELECT e.team, t.name, m.events_14d FROM v_events e "
        "JOIN v_tools t ON t.tool = e.tool JOIN v_teams m ON m.team = e.team"
    ),
}


@pytest.mark.parametrize("sql", REFUSED.values(), ids=REFUSED.keys())
def test_a_relation_that_is_not_a_view_is_refused_wherever_it_hides(sql: str) -> None:
    with pytest.raises(UnsafeSqlError, match="can be queried"):
        guard(sql)


@pytest.mark.parametrize("sql", ALLOWED.values(), ids=[name[:40] for name in ALLOWED])
def test_queries_over_the_views_pass_the_guard(sql: str) -> None:
    assert f"LIMIT {MAX_ROWS}" in guard(sql)


@pytest.mark.integration
async def test_what_the_guard_passes_runs_on_the_read_only_login(api: Api) -> None:
    for sql in ALLOWED.values():
        await run_readonly(api.services.readonly_db, guard(sql))


def test_limit_is_added_and_capped() -> None:
    assert guard("SELECT team FROM v_teams").endswith(f"LIMIT {MAX_ROWS}")
    assert guard("SELECT team FROM v_teams LIMIT 5").endswith("LIMIT 5")
    assert guard("SELECT team FROM v_teams LIMIT 100000").endswith(f"LIMIT {MAX_ROWS}")


@pytest.mark.parametrize(
    "sql",
    [
        "DROP TABLE events",
        "DELETE FROM v_events",
        "UPDATE v_tools SET status = 'approved'",
        "SELECT * FROM events",
        "SELECT user_pseudonym FROM public.events",
        "SELECT * FROM v_events; DROP TABLE events",
        "SELECT * FROM v_events JOIN directory_users ON true",
        "WITH e AS (SELECT * FROM events) SELECT * FROM e",
        "SELECT * INTO copy FROM v_events",
        "COPY v_events TO '/tmp/out'",
        "SELECT set_config('role', 'none', true) FROM v_teams",
        "SELECT query_to_xml('select * from events', true, true, '') FROM v_teams",
        "SELECT pg_sleep(10) FROM v_teams",
        "SELECT current_setting('server_version') FROM v_teams",
        "SELECT pg_read_file('/etc/passwd') FROM v_teams",
        "SELECT lo_import('/etc/passwd') FROM v_teams",
        "SELECT dblink('host=x', 'select 1') FROM v_teams",
        "not sql at all",
        "",
    ],
)
def test_anything_else_is_rejected(sql: str) -> None:
    with pytest.raises(UnsafeSqlError):
        guard(sql)
