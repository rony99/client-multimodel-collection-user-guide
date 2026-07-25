"""Tests for gateway.config: YAML loading + env-var interpolation + pydantic validation."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from pydantic import ValidationError

from gateway.config import (
    GatewayConfig,
    load_config,
)


def _write_yaml(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "config.yaml"
    p.write_text(textwrap.dedent(body))
    return p


def test_minimal_config_loads(tmp_path: Path) -> None:
    p = _write_yaml(
        tmp_path,
        """\
        upstreams:
          - name: openai-primary
            style: openai
            base_url: https://api.openai.com/v1
            api_key: sk-test
        routes:
          - model_id: gpt-4o
            upstream: openai-primary
        """,
    )
    cfg = load_config(p)
    assert isinstance(cfg, GatewayConfig)
    assert cfg.server.host == "0.0.0.0"
    assert cfg.server.port == 9000
    assert len(cfg.upstreams) == 1
    assert cfg.upstreams[0].style == "openai"
    assert len(cfg.routes) == 1
    assert cfg.routes[0].upstream_model is None  # default = forward as-is


def test_env_var_interpolation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MY_API_KEY", "sk-from-env")
    p = _write_yaml(
        tmp_path,
        """\
        upstreams:
          - name: openai-primary
            style: openai
            base_url: https://api.openai.com/v1
            api_key: ${MY_API_KEY}
        routes:
          - model_id: gpt-4o
            upstream: openai-primary
        """,
    )
    cfg = load_config(p)
    assert cfg.upstreams[0].api_key == "sk-from-env"


def test_env_var_with_default(tmp_path: Path) -> None:
    p = _write_yaml(
        tmp_path,
        """\
        upstreams:
          - name: openai-primary
            style: openai
            base_url: https://api.openai.com/v1
            api_key: ${MISSING_KEY:-fallback-key}
        routes:
          - model_id: gpt-4o
            upstream: openai-primary
        """,
    )
    cfg = load_config(p)
    assert cfg.upstreams[0].api_key == "fallback-key"


def test_missing_env_var_raises(tmp_path: Path) -> None:
    p = _write_yaml(
        tmp_path,
        """\
        upstreams:
          - name: openai-primary
            style: openai
            base_url: https://api.openai.com/v1
            api_key: ${DEFINITELY_NOT_SET_VAR}
        routes:
          - model_id: gpt-4o
            upstream: openai-primary
        """,
    )
    with pytest.raises(ValueError, match="DEFINITELY_NOT_SET_VAR"):
        load_config(p)


def test_duplicate_upstream_names_rejected(tmp_path: Path) -> None:
    p = _write_yaml(
        tmp_path,
        """\
        upstreams:
          - name: dup
            style: openai
            base_url: https://api.openai.com/v1
            api_key: sk-1
          - name: dup
            style: anthropic
            base_url: https://api.anthropic.com
            api_key: sk-2
        routes:
          - model_id: gpt-4o
            upstream: dup
        """,
    )
    with pytest.raises(ValidationError, match="unique"):
        load_config(p)


def test_duplicate_model_ids_rejected(tmp_path: Path) -> None:
    p = _write_yaml(
        tmp_path,
        """\
        upstreams:
          - name: openai-primary
            style: openai
            base_url: https://api.openai.com/v1
            api_key: sk-test
        routes:
          - model_id: gpt-4o
            upstream: openai-primary
          - model_id: gpt-4o
            upstream: openai-primary
        """,
    )
    with pytest.raises(ValidationError, match="unique"):
        load_config(p)


def test_unknown_style_rejected(tmp_path: Path) -> None:
    p = _write_yaml(
        tmp_path,
        """\
        upstreams:
          - name: openai-primary
            style: bogus
            base_url: https://api.openai.com/v1
            api_key: sk-test
        routes:
          - model_id: gpt-4o
            upstream: openai-primary
        """,
    )
    with pytest.raises(ValidationError):
        load_config(p)


def test_missing_config_file() -> None:
    with pytest.raises(FileNotFoundError):
        load_config("/tmp/does-not-exist-lightweight-gateway.yaml")


def test_trailing_slash_stripped_from_base_url(tmp_path: Path) -> None:
    p = _write_yaml(
        tmp_path,
        """\
        upstreams:
          - name: openai-primary
            style: openai
            base_url: https://api.openai.com/v1/
            api_key: sk-test
        routes:
          - model_id: gpt-4o
            upstream: openai-primary
        """,
    )
    cfg = load_config(p)
    assert str(cfg.upstreams[0].base_url) == "https://api.openai.com/v1"


def test_yaml_must_be_a_mapping(tmp_path: Path) -> None:
    p = _write_yaml(tmp_path, "- just a list\n")
    with pytest.raises(ValueError, match="mapping"):
        load_config(p)
