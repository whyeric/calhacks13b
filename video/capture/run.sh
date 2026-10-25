#!/usr/bin/env bash
# Same setup as `make demo` (DEMO_OFFLINE=1, DEMO_AS_OF week, `make seed`, production frontend), but
# isolated: the frontend is built in a temp dir, and each pass (stills, video) gets a freshly seeded
# SQLite db + ledgers dir, then capture.mjs runs against it.
# Uses ports 8010/3010 so it never touches a dev server on 3000/8000 or the repo's hedge_desk.db.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
API_PORT=${API_PORT:-8010}
WEB_PORT=${WEB_PORT:-3010}
PASSES=${PASSES:-"stills video"}
TMP="$(mktemp -d)"
PIDS=()
cleanup() { for p in "${PIDS[@]:-}"; do [ -n "$p" ] && kill "$p" 2>/dev/null || true; done; }
trap cleanup EXIT

echo "build frontend in $TMP/fe"
rsync -a --exclude node_modules --exclude .next --exclude test-results "$REPO/frontend/" "$TMP/fe/"
ln -sfn "$REPO/frontend/node_modules" "$TMP/fe/node_modules"
(cd "$TMP/fe" && NEXT_TELEMETRY_DISABLED=1 NEXT_PUBLIC_API_URL="http://localhost:$API_PORT" npm run build >"$TMP/build.log" 2>&1)
(cd "$TMP/fe" && NEXT_TELEMETRY_DISABLED=1 exec npm run start -- --port "$WEB_PORT" >"$TMP/web.log" 2>&1) &
PIDS+=($!)

for pass in $PASSES; do
  db="$TMP/$pass"; mkdir -p "$db/ledgers"
  export DEMO_OFFLINE=1 DEMO_AS_OF=2026-10-24T19:00:00Z ANTHROPIC_API_KEY= \
    DATABASE_URL="sqlite:///$db/video.db" LEDGERS_DIR="$db/ledgers" \
    CORS_ORIGINS="http://localhost:$WEB_PORT,http://127.0.0.1:$WEB_PORT"
  (cd "$REPO/backend" && PY=.venv/bin/python && $PY -m app.db seed && $PY -m app.books.seed \
    && $PY -m scripts.run_backtest --if-missing) >"$db/seed.log" 2>&1
  (cd "$REPO/backend" && exec .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port "$API_PORT" >"$db/api.log" 2>&1) &
  api=$!; PIDS+=($api)
  for _ in $(seq 1 120); do curl -sf "localhost:$API_PORT/health" >/dev/null && break; sleep 0.5; done
  for _ in $(seq 1 120); do curl -sf -o /dev/null "localhost:$WEB_PORT" && break; sleep 0.5; done
  echo "pass: $pass"
  WEB="http://localhost:$WEB_PORT" node "$HERE/capture.mjs" "$pass"
  kill "$api"; wait "$api" 2>/dev/null || true
done
rm -rf "$REPO/video/assets/.video-tmp"
echo "done: $REPO/video/assets"
