"""Pydantic configuration models + YAML loader with env-var interpolation.

Why: Polar uses pydantic for strict config validation. We mirror that
pattern here so the gateway fails fast on misconfiguration rather than
halfway through a request.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


class ServerConfig(BaseModel):
    """HTTP server settings."""

    model_config = ConfigDict(extra="forbid")

    host: str = "0.0.0.0"
    port: int = Field(default=9000, ge=1, le=65535)
    log_level: str = "INFO"


class LogConfig(BaseModel):
    """Where logs go on disk.

    Layout: <dir>/<project_id>/<YYYY-MM-DD>.jsonl (one line per request).
    """

    model_config = ConfigDict(extra="forbid")

    dir: Path = Field(default=Path("./logs"))
    # Max in-flight queued records before the writer starts dropping.
    # Mirrors Polar's CompletionWriter.queue_size; default 1024.
    queue_size: int = Field(default=1024, gt=0)


UpstreamStyle = Literal["openai", "anthropic"]


class UpstreamConfig(BaseModel):
    """One upstream provider (OpenAI-style or Anthropic-style)."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    style: UpstreamStyle
    base_url: HttpUrl
    api_key: str = Field(min_length=1)
    timeout_seconds: float = Field(default=60.0, gt=0)
    # Anthropic requires an `anthropic-version` header. Only used when
    # style == "anthropic"; ignored otherwise.
    version: str = "2023-06-01"

    @field_validator("base_url", mode="after")
    @classmethod
    def _strip_trailing_slash(cls, value: HttpUrl) -> HttpUrl:
        # HttpUrl may carry a trailing slash; we append paths like
        # "/v1/chat/completions" ourselves, so strip it.
        url_str = str(value).rstrip("/")
        return HttpUrl(url_str)


class RouteConfig(BaseModel):
    """A model_id → upstream mapping.

    `upstream_model` is the actual model name sent to the upstream. If
    omitted, the agent's `model_id` is forwarded verbatim (useful when
    the gateway and upstream already agree on names).
    """

    model_config = ConfigDict(extra="forbid")

    model_id: str = Field(min_length=1)
    upstream: str = Field(min_length=1)
    upstream_model: str | None = None


class GatewayConfig(BaseModel):
    """Top-level config loaded from YAML."""

    model_config = ConfigDict(extra="forbid")

    server: ServerConfig = Field(default_factory=ServerConfig)
    log: LogConfig = Field(default_factory=LogConfig)
    upstreams: list[UpstreamConfig] = Field(min_length=1)
    routes: list[RouteConfig] = Field(min_length=1)

    @field_validator("upstreams")
    @classmethod
    def _unique_upstream_names(cls, value: list[UpstreamConfig]) -> list[UpstreamConfig]:
        names = [u.name for u in value]
        if len(names) != len(set(names)):
            seen: set[str] = set()
            dups: list[str] = []
            for n in names:
                if n in seen and n not in dups:
                    dups.append(n)
                seen.add(n)
            raise ValueError(f"upstream names must be unique; duplicates: {dups}")
        return value

    @field_validator("routes")
    @classmethod
    def _unique_model_ids(cls, value: list[RouteConfig]) -> list[RouteConfig]:
        ids = [r.model_id for r in value]
        if len(ids) != len(set(ids)):
            seen: set[str] = set()
            dups: list[str] = []
            for i in ids:
                if i in seen and i not in dups:
                    dups.append(i)
                seen.add(i)
            raise ValueError(f"model_id routes must be unique; duplicates: {dups}")
        return value

    def upstream_names(self) -> set[str]:
        return {u.name for u in self.upstreams}


# Matches ${VAR} and ${VAR:-default}.
_ENV_PATTERN = re.compile(r"\$\{(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?::-(?P<default>[^}]*))?\}")


def _interpolate_env(value: Any) -> Any:
    """Recursively expand ${VAR} / ${VAR:-default} in string leaves.

    Why: API keys should never be checked in. We accept them via env
    vars in the YAML rather than as plaintext.
    """
    if isinstance(value, str):
        def repl(m: re.Match[str]) -> str:
            name = m.group("name")
            default = m.group("default")
            env_val = os.environ.get(name)
            if env_val is not None:
                return env_val
            if default is not None:
                return default
            raise ValueError(
                f"environment variable {name!r} is not set and no default was given"
            )

        return _ENV_PATTERN.sub(repl, value)
    if isinstance(value, dict):
        return {k: _interpolate_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_interpolate_env(item) for item in value]
    return value


def load_config(path: str | Path) -> GatewayConfig:
    """Load a YAML file from `path`, expand env vars, return validated config.

    Raises pydantic.ValidationError on bad input; raises ValueError on
    missing env vars (no default).
    """
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"config file not found: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"config root must be a mapping, got {type(raw).__name__}")
    expanded = _interpolate_env(raw)
    return GatewayConfig.model_validate(expanded)
