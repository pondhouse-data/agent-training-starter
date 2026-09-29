# Prüfservice (A2A) für Azure Container Apps. Baut aus dem Repository-Stamm:
#   docker build -t pruefservice .
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/app/.venv PYTHONUNBUFFERED=1

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

COPY training_tools.py ./
COPY training_data ./training_data
COPY pruefservice ./pruefservice

ARG APP_VERSION=lokal
ENV APP_VERSION=${APP_VERSION} PORT=8000 PATH="/app/.venv/bin:${PATH}"
RUN useradd --uid 10001 --no-create-home pruefservice
USER pruefservice
EXPOSE 8000
CMD ["python", "-m", "pruefservice"]
