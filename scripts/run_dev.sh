#!/usr/bin/env bash
# Start em-mcp-server and the API together for local development; Ctrl+C stops both.
#   scripts/run_dev.sh                    # EM_PROVIDER from the shell, else .env, else mock
#   EM_PROVIDER=live scripts/run_dev.sh   # data.go.kr (keys in .env)
# Ports: API_PORT (default 8000), EM_MCP_PORT (default 8001).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PY="$ROOT/.venv/bin/python"
[[ -x "$PY" ]] || PY="$(command -v python3)"

API_PORT="${API_PORT:-8000}"
export EM_MCP_PORT="${EM_MCP_PORT:-8001}"
export EM_MCP_URL="http://127.0.0.1:${EM_MCP_PORT}/mcp"
# Only the provider name is read here; the server loads the keys from .env itself (shell wins).
if [[ -z "${EM_PROVIDER:-}" && -f .env ]]; then
  EM_PROVIDER="$(sed -n 's/^[[:space:]]*\(export[[:space:]]\+\)\?EM_PROVIDER[[:space:]]*=[[:space:]]*//p' .env | tail -n1 | tr -d "\"'[:space:]")"
fi
export EM_PROVIDER="${EM_PROVIDER:-mock}"

for port in "$API_PORT" "$EM_MCP_PORT"; do
  if (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null; then
    echo "port $port is already in use; set API_PORT / EM_MCP_PORT to free ports" >&2
    exit 1
  fi
done

pids=()
cleanup() {
  trap - INT TERM EXIT
  echo
  echo "stopping..."
  for pid in "${pids[@]}"; do kill "$pid" 2>/dev/null || true; done
  wait 2>/dev/null || true
}
trap cleanup INT TERM EXIT

"$PY" -m mcp_server.server &
pids+=($!)
"$PY" -m uvicorn backend.app.main:app --host 127.0.0.1 --port "$API_PORT" &
pids+=($!)

for _ in $(seq 50); do
  curl -fs -o /dev/null "http://127.0.0.1:${API_PORT}/health" && break
  sleep 0.2
done
echo
echo "EM-Agent running (EM_PROVIDER=${EM_PROVIDER})"
echo "  page:    http://127.0.0.1:${API_PORT}/"
echo "  swagger: http://127.0.0.1:${API_PORT}/docs"
echo "  mcp:     ${EM_MCP_URL}"
echo "Ctrl+C to stop."
wait -n
