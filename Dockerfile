FROM ghcr.io/astral-sh/uv:0.9.17-python3.12-bookworm-slim AS builder
WORKDIR /build
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/app ./app
COPY backend/migrations ./migrations
COPY config.yaml ./config.yaml
COPY config ./config
RUN uv sync --frozen --no-dev
RUN mkdir -p /opt/tiktoken && TIKTOKEN_CACHE_DIR=/opt/tiktoken .venv/bin/python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')"
RUN .venv/bin/python -c "import fastapi, uvicorn, psycopg, tiktoken"

FROM python:3.12-slim-bookworm
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PATH="/app/.venv/bin:$PATH" PORT=8000 TIKTOKEN_CACHE_DIR=/opt/tiktoken REQUIRE_EXACT_TOKENIZER=true
RUN addgroup --system app && adduser --system --ingroup app app
WORKDIR /app
COPY --from=builder /build/.venv /app/.venv
COPY --from=builder /build/app /app/app
COPY --from=builder /build/migrations /app/migrations
COPY --from=builder /build/config.yaml /app/config.yaml
COPY --from=builder /opt/tiktoken /opt/tiktoken
RUN mkdir -p /app/data && chown -R app:app /app
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"
CMD ["sh", "-c", "exec /app/.venv/bin/python -m app.serve"]
