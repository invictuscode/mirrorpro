#!/usr/bin/env bash
# Start the Vite dev server on http://127.0.0.1:5173 (proxies /api and /ws to the backend).
set -euo pipefail
cd "$(dirname "$0")/../frontend"
exec npm run dev
