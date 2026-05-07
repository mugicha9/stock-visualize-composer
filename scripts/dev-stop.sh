#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PATTERN='uvicorn backend.app.main:app|next dev -H 127.0.0.1|npm run dev'

contains_pid() {
  local target="$1"
  shift
  local pid
  for pid in "$@"; do
    if [ "$pid" = "$target" ]; then
      return 0
    fi
  done
  return 1
}

find_pids() {
  local pid cwd cmd
  local pids=()
  while IFS= read -r pid; do
    [ -n "$pid" ] || continue
    [ "$pid" != "$$" ] || continue
    [ "$pid" != "${PPID:-}" ] || continue
    cwd="$(readlink "/proc/$pid/cwd" 2>/dev/null || true)"
    cmd="$(tr '\0' ' ' <"/proc/$pid/cmdline" 2>/dev/null || true)"
    if [[ "$cwd" == "$ROOT_DIR"* || "$cmd" == *"$ROOT_DIR"* ]]; then
      if ! contains_pid "$pid" "${pids[@]:-}"; then
        pids+=("$pid")
      fi
    fi
  done < <(pgrep -f "$PATTERN" 2>/dev/null || true)
  if [ "${#pids[@]}" -gt 0 ]; then
    printf '%s\n' "${pids[@]}"
  fi
}

mapfile -t PIDS < <(find_pids)
if [ "${#PIDS[@]}" -eq 0 ]; then
  echo "No matching dev processes found."
  exit 0
fi

echo "Stopping dev processes: ${PIDS[*]}"
kill "${PIDS[@]}" 2>/dev/null || true
sleep 1

mapfile -t REMAINING < <(find_pids)
if [ "${#REMAINING[@]}" -gt 0 ]; then
  echo "Force stopping remaining dev processes: ${REMAINING[*]}"
  kill -9 "${REMAINING[@]}" 2>/dev/null || true
fi

echo "Stopped."
"$ROOT_DIR/scripts/llama_cpp_docker.py" stop >/dev/null 2>&1 || true
