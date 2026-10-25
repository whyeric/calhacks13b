# Hedge Desk API (backend/) for Render (render.yaml) or any Docker host. The frontend deploys separately (Vercel).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv/backend

# Deps first so code changes don't reinstall them.
COPY backend/pyproject.toml ./
RUN mkdir app && touch app/__init__.py && pip install ".[data,books]" && rm -rf app build *.egg-info

COPY backend/ ./
RUN pip install --no-deps -e .

# State lives in /data. Render free has no disk, so it resets (and re-seeds) on every restart.
ENV DATABASE_URL=sqlite:////data/hedge_desk.db \
    LEDGERS_DIR=/data/ledgers \
    DEMO_OFFLINE=1 \
    DEMO_AS_OF=2026-10-24T19:00:00Z

# Same steps as `make seed` (idempotent), then one uvicorn worker: desk runs are in-process.
CMD mkdir -p /data/ledgers \
 && python -m app.db seed && python -m app.books.seed && python -m scripts.run_backtest --if-missing \
 && exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
