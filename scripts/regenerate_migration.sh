#!/bin/sh
# Rebuild the initial migration from the models. Only valid until the first release:
# after that, schema changes get their own revision. Needs `make test-deps`.
set -eu
cd "$(dirname "$0")/.."
versions=gateway/migrations/versions
server=postgresql+asyncpg://aspida:aspida@127.0.0.1:55432
scratch="scratch_$$"
held=$(mktemp -d)

docker compose -f docker-compose.test.yml exec -T postgres createdb -U aspida "$scratch"
mv "$versions"/0002_*.py "$held"/
: > "$versions/0001_initial_schema.py"
mv "$versions/0001_initial_schema.py" "$held"/
# Building a migration calls no model; the key is set only so that the settings load.
OPENAI_API_KEY=unused ASPIDA_DATABASE_URL="$server/$scratch" \
    uv run alembic -c gateway/alembic.ini revision --autogenerate -m "initial schema" --rev-id 0001
mv "$held"/0002_*.py "$versions"/
docker compose -f docker-compose.test.yml exec -T postgres dropdb -U aspida "$scratch"
uv run ruff format "$versions"
