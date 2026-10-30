# syntax=docker/dockerfile:1
FROM ghcr.io/astral-sh/uv:0.12.23 AS uv
FROM python:3.12-slim

COPY --from=uv /uv /bin/uv
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_NO_CACHE=1 \
    OPENBLAS_NUM_THREADS=1 \
    OMP_NUM_THREADS=1 \
    PORT=8000

WORKDIR /app
COPY pyproject.toml uv.lock ./

# Optional CA bundle for builds in managed environments; never bake it into layers.
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then \
      SSL_CERT_FILE=/run/secrets/proxy_ca uv sync --locked --no-dev --no-install-project; \
    else \
      uv sync --locked --no-dev --no-install-project; \
    fi

RUN /app/.venv/bin/python -c "from zoneinfo import ZoneInfo; ZoneInfo('Asia/Taipei'); ZoneInfo('America/New_York')"
COPY --chown=10001:10001 stockpredict ./stockpredict
ENV PATH="/app/.venv/bin:$PATH"
USER 10001:10001
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('PORT', '8000') + '/api/health', timeout=3)" || exit 1

CMD ["sh", "-c", "exec uvicorn stockpredict.main:app --host 0.0.0.0 --port \"${PORT:-8000}\""]
