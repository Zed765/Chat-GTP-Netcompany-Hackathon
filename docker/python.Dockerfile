# One Dockerfile for every Python service. Each compose service picks a target and the
# dependency group to install, so images hold only what that service needs.
ARG PYTHON_IMAGE=python:3.12.16-slim-trixie

FROM ghcr.io/astral-sh/uv:0.13.8 AS uv

FROM ${PYTHON_IMAGE} AS deps
ARG GROUP
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /build
RUN --mount=from=uv,source=/uv,target=/bin/uv \
    --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    uv sync --frozen --no-default-groups --group "${GROUP}"

FROM ${PYTHON_IMAGE} AS runtime
RUN groupadd --system --gid 10001 aspida \
    && useradd --system --uid 10001 --gid aspida --home-dir /srv --no-create-home aspida
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONPATH=/srv \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /srv
COPY --from=deps /opt/venv /opt/venv
# Services other than the gateway import its shared types and nothing else from it.
COPY gateway/__init__.py gateway/
COPY gateway/app/__init__.py gateway/app/
COPY gateway/app/core/__init__.py gateway/app/core/types.py gateway/app/core/

FROM runtime AS gateway
RUN install -d -o aspida -g aspida /var/lib/aspida/keys
COPY gateway/ gateway/
COPY eval/ eval/
COPY defaults/ defaults/
COPY policies/ policies/
# Mock data: what the unknown domains in the demo logs say about themselves.
COPY seeder/site_descriptions.json seeder/
COPY scripts/__init__.py scripts/smoke.py scripts/acceptance.py scripts/sample_log.py scripts/
USER aspida
EXPOSE 8000
HEALTHCHECK --interval=5s --timeout=3s --start-period=60s --retries=12 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz')"]
# No access log: query strings can carry search terms such as client names.
CMD ["sh", "-c", "python -m gateway.app.migrate && exec uvicorn gateway.app.main:app --host 0.0.0.0 --port 8000 --no-access-log"]

FROM runtime AS agent
COPY agent/ agent/
USER aspida
EXPOSE 8001
HEALTHCHECK --interval=5s --timeout=3s --start-period=20s --retries=12 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/healthz')"]
CMD ["uvicorn", "agent.main:app", "--host", "0.0.0.0", "--port", "8001"]

FROM runtime AS mcp
ARG SERVER
ARG PORT
ENV MCP_APP=mcp_servers.${SERVER}.server:app \
    MCP_PORT=${PORT}
COPY mcp_servers/ mcp_servers/
COPY seeder/data/ seeder/data/
USER aspida
EXPOSE ${PORT}
HEALTHCHECK --interval=5s --timeout=3s --start-period=20s --retries=12 \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"MCP_PORT\"]}/healthz')"]
CMD ["sh", "-c", "exec uvicorn \"$MCP_APP\" --host 0.0.0.0 --port \"$MCP_PORT\""]

FROM runtime AS mock-upstream
COPY mock_upstream/ mock_upstream/
USER aspida
EXPOSE 9100
HEALTHCHECK --interval=5s --timeout=3s --start-period=20s --retries=12 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9100/healthz')"]
CMD ["uvicorn", "mock_upstream.main:app", "--host", "0.0.0.0", "--port", "9100"]

FROM runtime AS seeder
COPY seeder/ seeder/
USER aspida
CMD ["python", "-m", "seeder.main"]
