#!/usr/bin/env bash
# Run after `node video/record.mjs`: builds every deliverable in video/out/deliver/ and prints QC. See finish.py.
set -euo pipefail
exec python3 "$(dirname "$0")/finish.py" "$@"
