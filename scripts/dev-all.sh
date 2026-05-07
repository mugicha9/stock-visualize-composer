#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCAL_NODE_PATH="$ROOT_DIR/.node/bin"
PIDS=()

cleanup() {
  "$ROOT_DIR/scripts/llama_cpp_docker.py" stop >/dev/null 2>&1 || true
  for pid in "${PIDS[@]:-}"; do
    if kill -0 "$pid" >/dev/null 2>&1; then
      kill "$pid" >/dev/null 2>&1 || true
    fi
  done
}

trap cleanup EXIT INT TERM

cd "$ROOT_DIR"

"$ROOT_DIR/scripts/ensure-node.sh"
if [ -d "$ROOT_DIR/frontend/node_modules/.bin" ]; then
  find "$ROOT_DIR/frontend/node_modules/.bin" -maxdepth 1 -type f -exec chmod +x {} +
fi

"$ROOT_DIR/scripts/llama_cpp_docker.py" serve

. "$ROOT_DIR/.venv/bin/activate"
uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000 &
PIDS+=("$!")

cd "$ROOT_DIR/frontend"
PATH="$LOCAL_NODE_PATH:$PATH" npm run dev &
PIDS+=("$!")

echo "API: http://127.0.0.1:8000"
echo "UI:  http://127.0.0.1:3000"
echo "llama.cpp: http://127.0.0.1:10000"

wait -n "${PIDS[@]}"
