FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY backend/pyproject.toml backend/pyproject.toml
COPY backend/app backend/app
COPY scripts/deepseek_v4_tokenizer/deepseek_v4_tokenizer/tokenizer.json scripts/deepseek_v4_tokenizer/deepseek_v4_tokenizer/tokenizer.json
COPY scripts/deepseek_v4_tokenizer/deepseek_v4_tokenizer/tokenizer_config.json scripts/deepseek_v4_tokenizer/deepseek_v4_tokenizer/tokenizer_config.json
RUN python -m pip install --no-cache-dir ./backend

COPY backend/alembic backend/alembic
COPY backend/alembic.ini backend/alembic.ini

RUN groupadd --system app && useradd --system --gid app --create-home app \
    && mkdir -p /app/data/audio /app/data/logs \
    && chown -R app:app /app

USER app

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=6 \
    CMD python -c "from urllib.request import urlopen; urlopen('http://127.0.0.1:8000/api/health', timeout=2)"

CMD ["python", "-m", "uvicorn", "app.main:app", "--app-dir", "/app/backend", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
