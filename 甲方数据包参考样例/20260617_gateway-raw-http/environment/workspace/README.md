# Lightweight LLM API Gateway (v1)

A trajectory-collection HTTP proxy for agent → LLM calls. Modeled after
[Polar](https://github.com/NVIDIA-NeMo/ProRL-Agent-Server)'s gateway
(`src/polar/gateway/`) but stripped down to the bare minimum needed
to learn how a multi-provider LLM proxy works end-to-end.

**v1 focus:** capture every agent → LLM call as a trajectory (one agent
session = one JSONL file). Nothing more. Tokenization, evaluation,
export, and training all live in later versions (see [Roadmap](#roadmap)).

## Why

The Polar gateway does a lot — it manages rollout sessions, runs
agents in containers, plumbs LLM API transforms, and feeds trajectories
into a trainer. That's too much surface area to read in one sitting.

This project is the same idea at 1/10 the size: **one FastAPI app, one
catch-all route, one JSONL file per session**. The data layout is
deliberately training-ready so v2-v6 can build directly on top.

## Quick start

```bash
# 1. Install (in the parent polar repo's venv, or your own)
uv pip install -e .

# 2. Configure
cp gateway/config.example.yaml ./config.yaml
# Edit ./config.yaml: at minimum set api_key via $OPENAI_API_KEY.

# 3. Run
lightweight-gateway -c config.yaml

# 4. Smoke test (server is on :9000 by default)
curl -X POST "http://127.0.0.1:9000/v1/chat/completions?project_id=acme&model_id=gpt-4o" \
  -H "Authorization: Bearer test" -H "Content-Type: application/json" \
  -d '{"model":"gpt-4o","messages":[{"role":"user","content":"hi"}]}'

# 5. Inspect the trajectory
ls -la ./logs/acme/                 # one dir per session
cat ./logs/acme/<session_id>/completions.jsonl | jq .
cat ./logs/acme/<session_id>/meta.json | jq .
```

The session_id is returned in the `X-Polar-Session-Id` response header
on the first call. Pass it back on subsequent calls (via
`X-Session-Id` header, `?session_id=` query, or `_proxy_session_id`
body field) to keep building the same trajectory.

## Architecture

```
Agent (curl / SDK / Claude Code / Codex / …)
    │
    │  POST /v1/chat/completions?project_id=…&model_id=…
    │  Header X-Session-Id: <existing or new>
    ▼
[Gateway FastAPI app]
    │
    ├─ catch-all  POST/GET/…  /{path:path}   (gateway/proxy.py)
    │     1. parse query → project_id, model_id
    │     2. resolve session_id (header > query > body > auth > uuid)
    │     3. router.resolve(model_id) → (upstream, upstream_model)
    │     4. forward to upstream (real SSE passthrough for streams)
    │     5. capture response (or buffer for streaming)
    │     6. extract token usage + latency
    │     7. writer.append(CompletionRecord)  → JSONL
    │     8. respond to agent with X-Polar-Session-Id set
    │
    ▼
Upstream (api.openai.com, api.anthropic.com, your self-hosted SGLang…)
```

### Data layout on disk

```
<log.dir>/
└── <project_id>/                       # one dir per online project
    └── <session_id>/                   # one dir per agent run
        ├── completions.jsonl           # one line per LLM call (append-only)
        └── meta.json                   # session-level aggregates
```

Each `completions.jsonl` line is a `CompletionRecord` (see
`gateway/models.py`):

```json
{
  "completion_id": "abc123…",
  "sequence": 0,
  "timestamp": "2026-06-17T01:23:45.678Z",
  "project_id": "acme",
  "session_id": "f1e2d3c4…",
  "model_id": "gpt-4o",
  "upstream": "openai-primary",
  "upstream_model": "gpt-4o-2024-08-06",
  "request_body": {"model": "gpt-4o", "messages": [...]},
  "response_body": {"choices": [...], "usage": {...}},
  "is_streaming": false,
  "response_status": 200,
  "timing_ms": 432.1,
  "token_usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20}
}
```

For streaming requests: `response_body` is `null` and `response_raw`
holds the concatenated SSE text (truncated at 16 MB by default).

## What's in v1

- ✅ HTTP proxy, OpenAI Chat Completions + Anthropic Messages
- ✅ Real SSE passthrough (no synthetic streaming)
- ✅ Multi-provider routing via YAML `routes:` table
- ✅ Model-name rewrite (`gpt-4o` → `gpt-4o-2024-08-06` etc.)
- ✅ Per-project / per-session JSONL log files
- ✅ Token usage extraction (OpenAI + Anthropic, both mapped to
     prompt/completion/total)
- ✅ Latency timing
- ✅ Tokenizer-free: raw messages are stored; tokenization happens in v5
- ✅ Session ID resolution: header > query > body > auth key > UUID
- ✅ Mock upstream for testing (in `tests/conftest.py`)
- ✅ Raw HTTP trace logging (full request/response including headers)

### Raw HTTP trace logging

In addition to the structured `completions.jsonl` trajectory, the gateway
can record **every upstream HTTP request and response** (including all
headers and bodies) as a raw HTTP log. This is useful for debugging,
auditing, and producing ShareGPT-format traces for evaluation.

**Enable** by setting the `GATEWAY_RAW_HTTP_DIR` environment variable:

```bash
export GATEWAY_RAW_HTTP_DIR=./raw_http_logs
```

Each session's raw log is written to:

```
<GATEWAY_RAW_HTTP_DIR>/<session_id>/raw_http.jsonl
```

Every line is a JSON object with `"direction": "request"` or
`"direction": "response"`, containing the full HTTP method, URL,
headers, body, and status code.

#### `?session_id=` query parameter

The raw HTTP log is grouped by session. To ensure logs are correctly
associated, pass the `?session_id=` query parameter on every request:

```bash
curl -X POST "http://127.0.0.1:9000/v1/chat/completions?project_id=acme&model_id=gpt-4o&session_id=my-session-123" \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-4o","messages":[{"role":"user","content":"hi"}]}'
```

The session_id can also be passed via `X-Session-Id` header or
`_proxy_session_id` body field, but the query parameter is the most
reliable method (some agents may not forward custom headers).

#### Converting raw logs to ShareGPT format

Use the included converter script to transform raw HTTP logs into
ShareGPT-compatible JSONL:

```bash
python scripts/raw_to_sharegpt.py raw_http_logs/my-session-123/raw_http.jsonl \
  -o output/my-session-123.sharegpt.jsonl
```

For traces that contain sub-agent conversations, use `--subagent-mode split`
to produce separate output files per sub-agent:

```bash
python scripts/raw_to_sharegpt.py raw_http_logs/my-session/raw_http.jsonl \
  -o output/main.sharegpt.jsonl --subagent-mode split
```

Sub-agent traces are written to `{stem}-subid_{n}.sharegpt.jsonl` files.

## What's NOT in v1 (and where it lives)

- ❌ Tokenization → v5 (export step)
- ❌ Trajectory analysis / prefix_merging → v2
- ❌ LLM-as-judge evaluation → v3
- ❌ Skill / Memory optimization → v4
- ❌ Export to TRL / Slime / VERL → v5
- ❌ Training framework bridge → v6
- ❌ Agent sandbox / runtime → v7+
- ❌ Dashboard → v7+
- ❌ Multi-tenant auth, rate limiting, billing → v7+
- ❌ Chunk-level token usage extraction from streams (we capture the
     raw text and let v3/v5 parse it) → revisit if needed in v2

## Roadmap

Two-layer architecture, mirroring Polar's `trajectory/` + `slime_bridge|verl_bridge/`
split. Layer 1 is "trajectory work" (uses LLM APIs for analysis). Layer 2
is "training bridge" (talks to training platforms but does not run them).

### Layer 1 — Trajectory work

| v | Theme | What it adds |
|---|---|---|
| **v1** | **Trajectory collection** *(this)* | Proxy + per-session JSONL + meta.json + token usage + latency |
| v2 | Trajectory organization + analysis | `prefix_merging` builder, per-session statistics, cross-session aggregation |
| v3 | LLM-as-judge evaluation | Configurable judge model + prompt; per-trajectory score + reasoning written back to meta.json |
| **v4** | **Skill / Memory optimization** | Extract reusable Skills from high-scoring trajectories (Hermes-style), accumulate per-project Memory, optional re-run loop (AutoResearch-style feedback) before training |

### Layer 2 — Training bridge (no actual training)

| v | Theme | What it adds |
|---|---|---|
| v5 | Export to training format | `gateway export --format {trl,slime,verl}` — converts trajectories to token-level training data |
| v6 | Training platform integration | HTTP bridge + weight pause/resume handshake (mirrors Polar `slime_bridge/`) |

### v7+ — Beyond

- v7: Agent sandbox (Docker runtime; each session spins up a container,
  the agent's LLM traffic auto-routes through the gateway)
- v8: Web dashboard (sessions list, completion diff view, real-time SSE tail)
- v9+: multi-tenant auth, per-project rate limits, cost tracking,
  A/B routing between upstreams

## Development

```bash
# Run the test suite (mock upstream, no real LLM calls)
pytest gateway/tests/ -v

# Lint
ruff check gateway/

# End-to-end demo with a real local mock upstream
bash gateway/examples/run_local.sh
```

## Polar mapping

If you already know Polar, here's the cross-reference:

| This project | Polar equivalent |
|---|---|
| `gateway/proxy.py` catch-all route | `src/polar/gateway/server.py:609` |
| `gateway/session.py` resolution | `src/polar/gateway/session.py:215-244` |
| `gateway/routing.py` | `src/polar/gateway/server.py:644-647` (per-session model rewrite) |
| `gateway/writer.py` JSONL appender | `src/polar/gateway/completion_writer.py` |
| `gateway/models.py CompletionRecord` | `src/polar/gateway/storage.py CompletionRecord` |
| Per-session JSONL on disk | `<save_dir>/task_<id>/sessions/<sid>/completions/*.json` (one file per completion; we use one JSONL instead) |
| (future) v3 evaluator | `src/polar/trajectory/evaluator/` |
| (future) v5 exporter | `src/slime_bridge/adapter.py` |
