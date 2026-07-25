"""Acceptance tests: raw HTTP trace logging + ShareGPT export.

Run: pytest tests/acceptance/test_raw_http_trace.py -q

These tests define the public contract. Read test names and assertions before
implementing ``gateway/raw_http_log.py`` and ``scripts/raw_to_sharegpt.py``.
"""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
import uvicorn
from fastapi import FastAPI, Request

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "tests" / "fixtures"


def test_raw_http_logger_module_exists():
    assert (REPO_ROOT / "gateway" / "raw_http_log.py").exists()


def test_sharegpt_converter_script_exists():
    assert (REPO_ROOT / "scripts" / "raw_to_sharegpt.py").exists()


def _find_converter_script() -> Path:
    path = REPO_ROOT / "scripts" / "raw_to_sharegpt.py"
    assert path.exists()
    return path


def _mock_upstream_app() -> FastAPI:
    app = FastAPI()

    @app.post("/v1/chat/completions")
    async def chat(request: Request):
        await request.json()
        return {
            "id": "cmpl-mock",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "mock-reply"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
        }

    return app


@pytest.fixture
def trace_gateway_env(tmp_path: Path):
    import socket
    import threading
    import time

    from gateway.app import create_app
    from gateway.config import GatewayConfig, LogConfig, RouteConfig, ServerConfig, UpstreamConfig

    def free_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    up_port = free_port()
    gw_port = free_port()
    log_dir = tmp_path / "logs"
    raw_dir = tmp_path / "raw_http"
    raw_dir.mkdir(parents=True, exist_ok=True)

    upstream_app = _mock_upstream_app()
    up_cfg = uvicorn.Config(upstream_app, host="127.0.0.1", port=up_port, log_level="warning")
    up_server = uvicorn.Server(up_cfg)

    def run_up():
        import asyncio

        asyncio.run(up_server.serve())

    up_thread = threading.Thread(target=run_up, daemon=True)
    up_thread.start()
    time.sleep(0.3)

    gw_config = GatewayConfig(
        server=ServerConfig(host="127.0.0.1", port=gw_port, log_level="WARNING"),
        log=LogConfig(dir=str(log_dir)),
        upstreams=[
            UpstreamConfig(
                name="mock",
                style="openai",
                base_url=f"http://127.0.0.1:{up_port}",
                api_key="k",
                timeout_seconds=10,
            )
        ],
        routes=[RouteConfig(model_id="gpt-4o", upstream="mock")],
    )
    os.environ["GATEWAY_RAW_HTTP_DIR"] = str(raw_dir)
    if hasattr(gw_config, "raw_http_dir"):
        gw_config.raw_http_dir = str(raw_dir)  # type: ignore[attr-defined]

    gw_app = create_app(gw_config)
    gw_cfg = uvicorn.Config(gw_app, host="127.0.0.1", port=gw_port, log_level="warning")
    gw_server = uvicorn.Server(gw_cfg)

    def run_gw():
        import asyncio

        asyncio.run(gw_server.serve())

    gw_thread = threading.Thread(target=run_gw, daemon=True)
    gw_thread.start()
    time.sleep(0.3)

    yield {
        "gw_port": gw_port,
        "log_dir": log_dir,
        "raw_dir": raw_dir,
        "session_id": "eval-trace-sess-42",
    }

    gw_server.should_exit = True
    up_server.should_exit = True


def test_raw_http_logs_grouped_by_session_query_param(trace_gateway_env):
    env = trace_gateway_env
    sid = env["session_id"]
    url = (
        f"http://127.0.0.1:{env['gw_port']}/v1/chat/completions"
        f"?project_id=eval&model_id=gpt-4o&session_id={sid}"
    )
    with httpx.Client(timeout=10) as client:
        resp = client.post(
            url,
            json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
        )
        assert resp.status_code == 200

    raw_dir: Path = env["raw_dir"]
    hits = list(raw_dir.rglob("raw_http.jsonl"))
    assert hits, f"Expected raw_http.jsonl under {raw_dir} for session_id={sid}"
    assert any(sid in str(p) for p in hits)


def test_raw_http_log_includes_request_and_response_headers(trace_gateway_env):
    env = trace_gateway_env
    sid = env["session_id"]
    url = (
        f"http://127.0.0.1:{env['gw_port']}/v1/chat/completions"
        f"?project_id=eval&model_id=gpt-4o&session_id={sid}"
    )
    with httpx.Client(timeout=10) as client:
        client.post(
            url,
            headers={"X-Eval-Trace": "1", "Content-Type": "application/json"},
            json={"model": "gpt-4o", "messages": [{"role": "user", "content": "headers"}]},
        )

    raw_dir: Path = env["raw_dir"]
    log_files = list(raw_dir.rglob("*.jsonl")) + list(raw_dir.rglob("*.json"))
    assert log_files

    combined = "".join(lf.read_text(encoding="utf-8") for lf in log_files)
    assert "headers" in combined.lower()
    assert "content-type" in combined.lower() or "content_type" in combined.lower()
    assert "request" in combined.lower() and "response" in combined.lower()


def test_sharegpt_converter_cli_runs_on_fixture(tmp_path: Path):
    script = _find_converter_script()
    fixture = FIXTURES / "raw_http_demo-sess-001.jsonl"
    assert fixture.exists()

    out = tmp_path / "demo-sess-001.sharegpt.jsonl"
    result = subprocess.run(
        [sys.executable, str(script), str(fixture), "-o", str(out)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert out.exists()

    lines = [ln for ln in out.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert lines
    record = json.loads(lines[0])
    conv = record.get("conversations") or record.get("messages")
    assert conv
    roles = {c.get("from") or c.get("role") for c in conv}
    assert "human" in roles or "user" in roles
    assert "gpt" in roles or "assistant" in roles


def test_sharegpt_orders_by_messages_and_timestamp(tmp_path: Path):
    script = _find_converter_script()
    fixture = FIXTURES / "raw_http_demo-sess-001.jsonl"
    out = tmp_path / "ordered.sharegpt.jsonl"
    subprocess.run(
        [sys.executable, str(script), str(fixture), "-o", str(out)],
        check=True,
        cwd=REPO_ROOT,
        capture_output=True,
    )
    record = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
    conv = record.get("conversations") or record.get("messages")
    texts = [c.get("value") or c.get("content") for c in conv]
    assert any("hi" in (t or "").lower() for t in texts)
    assert any("welcome" in (t or "").lower() for t in texts)


def test_subagent_trace_file_naming(tmp_path: Path):
    script = _find_converter_script()
    fixture = FIXTURES / "raw_http_demo-sess-001.jsonl"
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    result = subprocess.run(
        [
            sys.executable,
            str(script),
            str(fixture),
            "-o",
            str(out_dir / "main.sharegpt.jsonl"),
            "--subagent-mode",
            "split",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        sub_fixture = FIXTURES / "raw_http_demo-sess-001-subid_0.jsonl"
        if sub_fixture.exists():
            out = out_dir / "demo-sess-001-subid_0.sharegpt.jsonl"
            subprocess.run(
                [sys.executable, str(script), str(sub_fixture), "-o", str(out)],
                check=True,
                cwd=REPO_ROOT,
            )
            assert "subid_0" in out.name
        else:
            pytest.fail(
                "Converter must support subagent split files named "
                "{session_id}-subid_{n} or --subagent-mode split"
            )
    else:
        sub_files = list(out_dir.glob("*-subid_*.jsonl"))
        assert sub_files or (out_dir / "main.sharegpt.jsonl").exists()


def test_session_id_query_param_documented_for_raw_trace():
    texts = []
    for name in ("README.md", "CLAUDE.md"):
        p = REPO_ROOT / name
        if p.exists():
            texts.append(p.read_text(encoding="utf-8").lower())
    combined = "\n".join(texts)
    raw_trace_phrases = (
        "raw_http",
        "raw http log",
        "raw http trace",
        "http header log",
        "raw_http_log",
    )
    assert any(p in combined for p in raw_trace_phrases)
    assert "?session_id" in combined or "session_id query" in combined
