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

.PHONY: help install seed seed-data dev api demo warm test e2e clean

help:
	@echo "targets: install seed seed-data dev api demo warm test e2e clean"

$(PY):
	$(PYTHON_BIN) -m venv $(VENV)

install: $(PY)
	$(PY) -m pip install -q --upgrade pip
	$(PY) -m pip install -q -e "backend[$(EXTRAS)]"
	cd frontend && if [ -f package-lock.json ]; then npm ci; else npm install; fi

# Fixtures only, no network; idempotent.
seed:
	cd backend && $(PY) -m app.db seed && $(PY) -m app.books.seed

# Optional: needs raw data/ and network. Dewey first, so the feature build sees the restaurant series.
seed-data:
	cd backend && $(PY) -m app.data.dewey build && $(PY) -m app.data.build

dev:
	@trap 'kill 0' EXIT; \
	(cd backend && $(PY) -m uvicorn app.main:app --reload --port $(API_PORT)) & \
	(cd frontend && NEXT_PUBLIC_API_URL=$(API_URL) npm run dev -- --port $(WEB_PORT)) & \
	wait

# Backend only (the API seeds an empty db on first start).
api:
	cd backend && $(PY) -m uvicorn app.main:app --reload --port $(API_PORT)

# Offline demo: seed, start the API (no reload) at once, then the production frontend.
# The frontend is rebuilt only when its sources or API_URL changed since the last build.
# DEMO_WEB=0 serves the API alone (used by the C8-A1/A3 boot test).
DEMO_WEB ?= 1
demo: export DEMO_OFFLINE := 1
demo: export NEXT_TELEMETRY_DISABLED := 1
demo: seed
	@trap 'kill 0' EXIT; \
	(cd backend && exec $(PY) -m uvicorn app.main:app --host 127.0.0.1 --port $(API_PORT)) & \
	if [ "$(DEMO_WEB)" != 0 ]; then \
	  (cd frontend && \
	   if [ ! -f .next/BUILD_ID ] || [ "$$(cat .next/.api_url 2>/dev/null)" != "$(API_URL)" ] || \
	      [ -n "$$(find app components lib public next.config.mjs package.json -newer .next/BUILD_ID 2>/dev/null | head -1)" ]; then \
	     NEXT_PUBLIC_API_URL=$(API_URL) npm run build && echo "$(API_URL)" > .next/.api_url || exit 1; \
	   fi && exec npm run start -- --port $(WEB_PORT)) & \
	fi; \
	for i in $$(seq 1 120); do \
	  curl -sf $(API_URL)/health >/dev/null && { echo "Hedge Desk API ready: $(API_URL)"; break; }; \
	  sleep 0.25; \
	done; \
	curl -sf $(API_URL)/health >/dev/null || { echo "Hedge Desk API did not start on $(API_URL)" >&2; exit 1; }; \
	if [ "$(DEMO_WEB)" != 0 ]; then \
	  for i in $$(seq 1 600); do \
	    curl -sf -o /dev/null http://localhost:$(WEB_PORT) && { echo "Hedge Desk ready: http://localhost:$(WEB_PORT)"; break; }; \
	    sleep 0.5; \
	  done; \
	fi; \
	wait

# Online once: fill fixtures/kalshi_cache/, then replay offline and diff.
warm:
	cd backend && $(PY) -m app.markets.warm

test:
	cd backend && $(PY) -m pytest -q
	cd frontend && npx tsc --noEmit

# C8-A tests (tests/e2e/conftest.py blocks sockets and empties the API key).
E2E_ARGS ?= -q
e2e:
	cd backend && DEMO_OFFLINE=1 $(PY) -m pytest $(E2E_ARGS) ../tests/e2e

# Removes the SQLite file and generated ledgers, never fixtures.
clean:
	rm -f backend/*.db backend/*.db-wal backend/*.db-shm *.db
	rm -f ledgers/*.beancount backend/ledgers/*.beancount
	rm -rf frontend/.next
