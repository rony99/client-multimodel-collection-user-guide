"""Tests for gateway.routing: model_id → upstream lookup."""

from __future__ import annotations

import pytest

from gateway.routing import ResolvedRoute, Router, UnknownModelIdError


def test_resolve_known_model() -> None:
    r = Router(
        routes=[
            {"model_id": "gpt-4o", "upstream": "openai", "upstream_model": "gpt-4o-2024"},
            {"model_id": "claude-sonnet", "upstream": "anthropic"},
        ],
        upstream_names={"openai", "anthropic"},
    )
    out = r.resolve("gpt-4o")
    assert out == ResolvedRoute(
        model_id="gpt-4o", upstream="openai", upstream_model="gpt-4o-2024"
    )

    # No upstream_model in config → forward model_id as-is
    out2 = r.resolve("claude-sonnet")
    assert out2.upstream_model == "claude-sonnet"


def test_resolve_unknown_raises() -> None:
    r = Router(
        routes=[{"model_id": "gpt-4o", "upstream": "openai"}],
        upstream_names={"openai"},
    )
    with pytest.raises(UnknownModelIdError) as ei:
        r.resolve("gpt-5")
    assert ei.value.model_id == "gpt-5"


def test_unknown_upstream_in_route_rejected() -> None:
    with pytest.raises(ValueError, match="unknown upstreams"):
        Router(
            routes=[{"model_id": "gpt-4o", "upstream": "ghost"}],
            upstream_names={"openai"},
        )


def test_known_model_ids_sorted() -> None:
    r = Router(
        routes=[
            {"model_id": "zeta", "upstream": "openai"},
            {"model_id": "alpha", "upstream": "openai"},
            {"model_id": "mu", "upstream": "openai"},
        ],
        upstream_names={"openai"},
    )
    assert r.known_model_ids() == ["alpha", "mu", "zeta"]
