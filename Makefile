# Hedge Desk repo-root tasks. Backend runs from backend/ with its own venv.
SHELL := /bin/bash
.DEFAULT_GOAL := help

PYTHON_BIN ?= $(shell command -v python3.12 || command -v python3)
VENV       := backend/.venv
PY         := $(abspath $(VENV))/bin/python
EXTRAS     ?= dev,data,books
API_PORT   ?= 8000
WEB_PORT   ?= 3000
API_URL    ?= http://localhost:$(API_PORT)

.PHONY: help install seed seed-data dev demo warm test e2e clean

help:
	@echo "targets: install seed seed-data dev demo warm test e2e clean"

$(PY):
	$(PYTHON_BIN) -m venv $(VENV)

install: $(PY)
	$(PY) -m pip install -q --upgrade pip
	$(PY) -m pip install -q -e "backend[$(EXTRAS)]"
	cd frontend && if [ -f package-lock.json ]; then npm ci; else npm install; fi

# Fixtures only, no network; idempotent.
seed:
	cd backend && $(PY) -m app.db seed

# Optional: needs raw data/ and network; rebuilds fixtures/*.parquet.
seed-data:
	cd backend && $(PY) -m app.data.dewey build

dev:
	@trap 'kill 0' EXIT; \
	(cd backend && $(PY) -m uvicorn app.main:app --reload --port $(API_PORT)) & \
	(cd frontend && NEXT_PUBLIC_API_URL=$(API_URL) npm run dev -- --port $(WEB_PORT)) & \
	wait

demo: export DEMO_OFFLINE := 1
demo: seed
	cd frontend && NEXT_PUBLIC_API_URL=$(API_URL) npm run build
	@trap 'kill 0' EXIT; \
	(cd backend && $(PY) -m uvicorn app.main:app --port $(API_PORT)) & \
	(cd frontend && npm run start -- --port $(WEB_PORT)) & \
	for i in $$(seq 1 60); do \
	  curl -sf $(API_URL)/health >/dev/null && { echo "Hedge Desk ready: http://localhost:$(WEB_PORT)"; break; }; \
	  sleep 0.5; \
	done; \
	wait

# Online once: fill fixtures/kalshi_cache/, then replay offline and diff.
warm:
	cd backend && $(PY) -m app.markets.warm

test:
	cd backend && $(PY) -m pytest -q
	cd frontend && npx tsc --noEmit

# C8-A tests, sockets blocked, no API key.
e2e:
	cd backend && ANTHROPIC_API_KEY= DEMO_OFFLINE=1 $(PY) -m pytest -q ../tests/e2e

# Removes the SQLite file and generated ledgers, never fixtures.
clean:
	rm -f backend/*.db backend/*.db-wal backend/*.db-shm *.db
	rm -f ledgers/*.beancount backend/ledgers/*.beancount
