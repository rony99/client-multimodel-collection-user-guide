"""Model_id → upstream routing table.

The agent sends a logical `model_id` (e.g. "gpt-4o", "claude-3-5-sonnet")
as a query param. The router maps that to:
  - which upstream client to use (OpenAI / Anthropic / future)
  - what model name to actually send upstream (often the same string,
    but the gateway can transparently rewrite — e.g. "gpt-4o" ->
    "gpt-4o-2024-08-06", or "claude-3-5-sonnet" -> a self-hosted alias)

v1: a simple dict. v2 could add regex/glob matching and weighted
multi-upstream routing (e.g. A/B test between two providers).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ResolvedRoute(BaseModel):
    """The output of a routing lookup."""

    model_config = ConfigDict(extra="forbid")

    model_id: str
    upstream: str
    upstream_model: str


class UnknownModelIdError(KeyError):
    """Raised when the agent asks for a model_id we have no route for."""

    def __init__(self, model_id: str) -> None:
        super().__init__(model_id)
        self.model_id = model_id

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"unknown model_id: {self.model_id!r}"


class Router:
    """In-memory model_id → (upstream, upstream_model) lookup."""

    def __init__(self, routes: list[dict[str, str]], upstream_names: set[str]) -> None:
        self._table: dict[str, ResolvedRoute] = {}
        unknown_upstreams: list[str] = []
        for r in routes:
            upstream = r["upstream"]
            if upstream not in upstream_names:
                unknown_upstreams.append(upstream)
                continue
            upstream_model = r.get("upstream_model") or r["model_id"]
            self._table[r["model_id"]] = ResolvedRoute(
                model_id=r["model_id"],
                upstream=upstream,
                upstream_model=upstream_model,
            )
        if unknown_upstreams:
            raise ValueError(
                f"routes reference unknown upstreams: {sorted(set(unknown_upstreams))}"
            )

    def resolve(self, model_id: str) -> ResolvedRoute:
        route = self._table.get(model_id)
        if route is None:
            raise UnknownModelIdError(model_id)
        return route

    def known_model_ids(self) -> list[str]:
        return sorted(self._table.keys())
