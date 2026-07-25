# lightweight-gateway — Claude Code project context

Trajectory-collection HTTP proxy for agent → LLM calls. See [README.md](README.md) for architecture and API details.

## Docker environment

**Prerequisites:** Docker CLI; prefer [Colima](https://github.com/abiosoft/colima) on macOS.

```bash
docker context use colima   # or: colima start && docker context use colima
```

**Build** (from this directory):

```bash
docker build -t gateway-dev .
```

**Interactive shell** (code lives at `/app/source`):

```bash
docker run --rm -it gateway-dev bash
```

**Unit tests** (mock upstream, no real API keys):

```bash
docker run --rm gateway-dev pytest tests/ -q --ignore=tests/acceptance
```

**Feature acceptance** (TDD — read tests before implementing; see [TASK.md](TASK.md)):

```bash
docker run --rm gateway-dev pytest tests/acceptance/ -q
```

**Run the gateway server** (needs upstream API keys):

```bash
cp config.example.yaml config.yaml
# Edit config.yaml or pass env vars (OPENAI_API_KEY, ANTHROPIC_API_KEY)
docker run --rm -p 9000:9000 \
  -e OPENAI_API_KEY -e ANTHROPIC_API_KEY \
  -v "$(pwd)/config.yaml:/app/source/config.yaml:ro" \
  gateway-dev lightweight-gateway -c config.yaml
```

## Web search (MiniMax CLI fallback)

Claude Code may not have a built-in web search tool. When the user mentions an unfamiliar **format**, **framework**, **spec**, or **convention** (e.g. “output in X format”, “use Y framework”) and the answer is not in this repo, **search before implementing**.

Use the official [MiniMax CLI](https://github.com/MiniMax-AI/cli) via Bash on the **host** (not pre-installed in the Docker image):

```bash
# One-time setup (Node.js 18+)
npm install -g mmx-cli
mmx auth login --api-key "$MINIMAX_API_KEY"

# Agent-friendly structured search
mmx search query --q "FastAPI streaming SSE response format" --output json
```

Parse the JSON from stdout. If `mmx` is missing, ask the user to install it and set `MINIMAX_API_KEY`.

## Secrets

- Never commit `.env` or `config.yaml` with real API keys (see `.gitignore`).
- In Docker, inject secrets with `-e` or a mounted config file.

## Raw HTTP trace logging

Set `GATEWAY_RAW_HTTP_DIR` to record full upstream HTTP request/response
(including headers and bodies) grouped by `?session_id=` query param:

```bash
docker run --rm -p 9000:9000 \
  -e GATEWAY_RAW_HTTP_DIR=/app/source/raw_http \
  -e OPENAI_API_KEY -e ANTHROPIC_API_KEY \
  -v "$(pwd)/config.yaml:/app/source/config.yaml:ro" \
  gateway-dev lightweight-gateway -c config.yaml
```

Logs land at `<GATEWAY_RAW_HTTP_DIR>/<session_id>/raw_http.jsonl`.
Convert to ShareGPT format with `scripts/raw_to_sharegpt.py`.

## Constraints

- Do not document or leak ground-truth answers or task solutions in this file.
- Prefer `tests/` for verification (not `gateway/tests/`).
