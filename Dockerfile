FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    UV_CACHE_DIR=/tmp/uv-cache \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PATH="/app/.venv/bin:${PATH}" \
    UVICORN_TIMEOUT_GRACEFUL_SHUTDOWN=30

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:0.9.17 /uv /uvx /bin/

RUN groupadd --system app && useradd --system --create-home --gid app app


FROM base AS builder

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
COPY config ./config

RUN uv sync --frozen --no-dev


FROM base AS runtime

COPY --chown=app:app --from=builder /app/.venv /app/.venv
COPY --chown=app:app pyproject.toml uv.lock ./
COPY --chown=app:app funboost_config.py nb_log_config.py ./
COPY --chown=app:app src ./src
COPY --chown=app:app config ./config

USER app

STOPSIGNAL SIGTERM

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 CMD python -c "import urllib.request; from src.infrastructure.settings.app_settings_loader import AppSettingsLoader; prefix = AppSettingsLoader().load().runtime.web.api_prefix.strip().rstrip('/'); path = f'{prefix}/health/ready' if prefix else '/health/ready'; response = urllib.request.urlopen(f'http://127.0.0.1:8000{path}', timeout=3); response.close()"

CMD ["python", "-m", "src.cli.run_web_server"]
