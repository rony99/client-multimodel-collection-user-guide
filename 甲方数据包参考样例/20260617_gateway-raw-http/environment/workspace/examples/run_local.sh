#!/usr/bin/env bash
# End-to-end demo: start mock upstream + gateway + a few curl calls.
#
# Usage: bash gateway/examples/run_local.sh
# Stops everything on Ctrl-C.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

# Make the venv-created `lightweight-gateway` console script visible.
# Allows running this script without first `source .venv/bin/activate`.
if [ -x "$REPO_ROOT/.venv/bin/lightweight-gateway" ]; then
  export PATH="$REPO_ROOT/.venv/bin:$PATH"
fi

PORT_UPSTREAM=9100
PORT_GATEWAY=9000
LOG_DIR="$REPO_ROOT/gateway_logs"
DEMO_CONFIG="$REPO_ROOT/gateway/examples/config.demo.yaml"
PIDFILE_UPSTREAM="$REPO_ROOT/.mock_upstream.pid"
PIDFILE_GATEWAY="$REPO_ROOT/.gateway.pid"

cleanup() {
  echo
  echo "→ stopping background processes"
  if [ -f "$PIDFILE_GATEWAY" ]; then
    kill "$(cat "$PIDFILE_GATEWAY")" 2>/dev/null || true
    rm -f "$PIDFILE_GATEWAY"
  fi
  if [ -f "$PIDFILE_UPSTREAM" ]; then
    kill "$(cat "$PIDFILE_UPSTREAM")" 2>/dev/null || true
    rm -f "$PIDFILE_UPSTREAM"
  fi
}
trap cleanup EXIT INT TERM

rm -rf "$LOG_DIR"
mkdir -p "$LOG_DIR"

echo "→ starting mock upstream on 127.0.0.1:$PORT_UPSTREAM"
python -m gateway.examples.mock_upstream \
  > "$LOG_DIR/mock_upstream.log" 2>&1 &
echo $! > "$PIDFILE_UPSTREAM"

# wait for upstream
for _ in $(seq 1 50); do
  if curl -fsS -X POST "http://127.0.0.1:$PORT_UPSTREAM/v1/chat/completions" \
        -H "Content-Type: application/json" \
        -d '{"model":"gpt-4o","messages":[]}' > /dev/null 2>&1; then
    break
  fi
  sleep 0.1
done
echo "   mock upstream is up"

echo "→ starting gateway on 127.0.0.1:$PORT_GATEWAY"
lightweight-gateway -c "$DEMO_CONFIG" \
  > "$LOG_DIR/gateway.log" 2>&1 &
echo $! > "$PIDFILE_GATEWAY"

for _ in $(seq 1 50); do
  if curl -fsS "http://127.0.0.1:$PORT_GATEWAY/healthz" > /dev/null 2>&1; then
    break
  fi
  sleep 0.1
done
echo "   gateway is up"

echo
echo "=== Demo 1: OpenAI non-streaming ==="
curl -sS -X POST \
  "http://127.0.0.1:$PORT_GATEWAY/v1/chat/completions?project_id=demo&model_id=gpt-4o" \
  -H "X-Session-Id: demo-session-1" \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-4o","messages":[{"role":"user","content":"hi"}]}' | python -m json.tool

echo
echo "=== Demo 2: OpenAI streaming ==="
curl -sN -X POST \
  "http://127.0.0.1:$PORT_GATEWAY/v1/chat/completions?project_id=demo&model_id=gpt-4o" \
  -H "X-Session-Id: demo-session-1" \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-4o","messages":[{"role":"user","content":"hi"}],"stream":true}'

echo
echo "=== Demo 3: Anthropic non-streaming ==="
curl -sS -X POST \
  "http://127.0.0.1:$PORT_GATEWAY/v1/messages?project_id=demo&model_id=claude-3-5-sonnet" \
  -H "X-Session-Id: demo-session-2" \
  -H "Content-Type: application/json" \
  -d '{"model":"claude-3-5-sonnet","max_tokens":256,"messages":[{"role":"user","content":"hi"}]}' \
  | python -m json.tool

echo
echo "=== Trajectory on disk ==="
ls -la "$LOG_DIR/demo" 2>/dev/null
for sid in demo-session-1 demo-session-2; do
  if [ -d "$LOG_DIR/demo/$sid" ]; then
    echo
    echo "--- $sid/completions.jsonl (one JSON per line) ---"
    # JSONL: one JSON per line. Print each line as a pretty block.
    while IFS= read -r line; do
      echo "$line" | python -m json.tool
    done < "$LOG_DIR/demo/$sid/completions.jsonl"
    echo
    echo "--- $sid/meta.json ---"
    cat "$LOG_DIR/demo/$sid/meta.json" | python -m json.tool
  fi
done

echo
echo "=== Done ==="
echo "Gateway log:   $LOG_DIR/gateway.log"
echo "Mock log:      $LOG_DIR/mock_upstream.log"
echo "Trajectories:  $LOG_DIR/<project_id>/<session_id>/"
