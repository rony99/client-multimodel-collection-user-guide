#!/usr/bin/env bash
# Various query / header / body patterns the gateway recognizes.
# Assumes the gateway is running on 127.0.0.1:9000.

set -euo pipefail
GATEWAY="http://127.0.0.1:9000"

echo "=== 1. project_id + model_id in query, session_id in query ==="
curl -sS -X POST \
  "$GATEWAY/v1/chat/completions?project_id=acme&model_id=gpt-4o&session_id=qs-1" \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-4o","messages":[{"role":"user","content":"hi"}]}' > /dev/null
echo "ok"

echo "=== 2. session_id in X-Session-Id header (recommended) ==="
curl -sS -X POST \
  "$GATEWAY/v1/chat/completions?project_id=acme&model_id=gpt-4o" \
  -H "X-Session-Id: hdr-1" \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-4o","messages":[{"role":"user","content":"hi"}]}' > /dev/null
echo "ok"

echo "=== 3. session_id in body field _proxy_session_id ==="
curl -sS -X POST \
  "$GATEWAY/v1/chat/completions?project_id=acme&model_id=gpt-4o" \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-4o","messages":[],"_proxy_session_id":"body-1"}' > /dev/null
echo "ok"

echo "=== 4. No session id → gateway generates a UUID; the agent picks it up from response header ==="
RESP=$(curl -sS -i -X POST \
  "$GATEWAY/v1/chat/completions?project_id=acme&model_id=gpt-4o" \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-4o","messages":[]}')
SID=$(echo "$RESP" | grep -i '^x-polar-session-id:' | awk '{print $2}' | tr -d '\r\n')
echo "generated session id: $SID"

echo "=== 5. Continue that same session (proves multi-turn layout) ==="
curl -sS -X POST \
  "$GATEWAY/v1/chat/completions?project_id=acme&model_id=gpt-4o" \
  -H "X-Session-Id: $SID" \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-4o","messages":[]}' > /dev/null
echo "ok — both calls live under $SID"

echo "=== 6. Multi-provider within one session ==="
curl -sS -X POST \
  "$GATEWAY/v1/chat/completions?project_id=acme&model_id=gpt-4o" \
  -H "X-Session-Id: mixed-1" \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-4o","messages":[]}' > /dev/null
curl -sS -X POST \
  "$GATEWAY/v1/messages?project_id=acme&model_id=claude-3-5-sonnet" \
  -H "X-Session-Id: mixed-1" \
  -H "Content-Type: application/json" \
  -d '{"model":"claude-3-5-sonnet","max_tokens":256,"messages":[]}' > /dev/null
echo "ok — OpenAI + Anthropic turns live side-by-side under mixed-1"
