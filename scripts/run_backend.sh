#!/usr/bin/env bash
# Start the Python tracking backend on http://127.0.0.1:8000.
# Pass settings as env vars, e.g.: PTM_PROFILE=pi PTM_CAMERA_INDEX=1 scripts/run_backend.sh
set -euo pipefail
cd "$(dirname "$0")/../backend"
if [[ ! -x .venv/bin/python ]]; then
  echo "backend/.venv missing — see README 'Setup'." >&2
  exit 1
fi
exec .venv/bin/python -m app
