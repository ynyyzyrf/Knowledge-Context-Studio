FROM node:22-bookworm-slim@sha256:48e4b67d85f87bd551df43704e24d252f56cc5f8e9718841aace50f19948f0f9 AS frontend
WORKDIR /build
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM ghcr.io/astral-sh/uv:0.10.12@sha256:72ab0aeb448090480ccabb99fb5f52b0dc3c71923bffb5e2e26517a1c27b7fec AS uv
FROM python:3.13-slim-bookworm@sha256:2325bb286ec344af3e5898cc224b5844e2707ac6e26b1632516fd3edc84a5e26 AS runtime
COPY --from=uv /uv /uvx /usr/local/bin/
WORKDIR /app
ENV UV_LINK_MODE=copy PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" KCS_FRONTEND_DIST=/app/web/dist
COPY pyproject.toml uv.lock README.md ./
COPY src/ ./src/
RUN uv sync --frozen --no-dev --no-editable \
    && groupadd --gid 10001 kcs \
    && useradd --uid 10001 --gid kcs --no-create-home kcs \
    && mkdir -p /app/runtime \
    && ln -s /app/runtime/.env /app/.env
COPY alembic.ini ./
COPY migrations/ ./migrations/
COPY scripts/ ./scripts/
COPY deploy/ ./deploy/
COPY --from=frontend /build/dist ./web/dist
USER 10001:10001
EXPOSE 8088
CMD ["uvicorn", "kcs.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8088"]
