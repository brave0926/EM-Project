#!/bin/sh
# Single-container start (Render and other PaaS): em-mcp-server on loopback, API on 0.0.0.0:$PORT.
# docker-compose.yml overrides this with one command per service.
set -eu

export EM_MCP_HOST=127.0.0.1
export EM_MCP_PORT="${EM_MCP_PORT:-8001}"
export EM_MCP_URL="http://127.0.0.1:${EM_MCP_PORT}/mcp"

python -m mcp_server.server &
mcp_pid=$!

# Wait for the MCP port so the first request does not hit a closed socket (max ~10 s).
python - <<'EOF'
import os, socket, time
port = int(os.environ["EM_MCP_PORT"])
for _ in range(50):
    try:
        socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
        break
    except OSError:
        time.sleep(0.2)
EOF

if ! kill -0 "$mcp_pid" 2>/dev/null; then
  echo "em-mcp-server exited during startup" >&2
  exit 1
fi

exec uvicorn backend.app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
