FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.26 /uv /usr/local/bin/uv

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/app/backend/.venv \
    PATH="/app/backend/.venv/bin:$PATH"

WORKDIR /app

COPY backend/pyproject.toml backend/uv.lock backend/
COPY backend/app backend/app
COPY scripts/deepseek_v4_tokenizer/deepseek_v4_tokenizer/tokenizer.json scripts/deepseek_v4_tokenizer/deepseek_v4_tokenizer/tokenizer.json
COPY scripts/deepseek_v4_tokenizer/deepseek_v4_tokenizer/tokenizer_config.json scripts/deepseek_v4_tokenizer/deepseek_v4_tokenizer/tokenizer_config.json
RUN uv sync --project backend --frozen --no-dev

COPY backend/alembic backend/alembic
COPY backend/alembic.ini backend/alembic.ini

RUN groupadd --system app && useradd --system --gid app --create-home app \
    && mkdir -p /app/data/audio /app/data/logs \
    && chown -R app:app /app

USER app

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=6 \
    CMD python -c "from urllib.request import urlopen; urlopen('http://127.0.0.1:8000/api/health', timeout=2)"

CMD ["/app/backend/.venv/bin/python", "-m", "uvicorn", "app.main:app", "--app-dir", "/app/backend", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
