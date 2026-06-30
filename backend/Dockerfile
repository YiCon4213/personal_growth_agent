FROM python:3.12-slim AS builder

ARG UV_VERSION=0.11.21
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

RUN pip install --no-cache-dir "uv==${UV_VERSION}"

WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project


FROM python:3.12-slim AS runtime

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/home/app

RUN groupadd --system app && useradd --system --gid app --create-home app

WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /usr/local/bin/uv /usr/local/bin/uv
COPY --from=builder /usr/local/bin/uvx /usr/local/bin/uvx
COPY --chown=app:app backend/app ./app
COPY --chown=app:app infra/migrations ./infra/migrations

USER app
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
