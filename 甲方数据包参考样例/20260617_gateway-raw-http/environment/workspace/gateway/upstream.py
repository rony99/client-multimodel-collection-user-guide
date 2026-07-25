"""Long-lived httpx clients, one per upstream provider.

Each upstream config gets its own `httpx.AsyncClient` so connection
pooling (TCP, HTTP/2, TLS) is reused across requests. Clients are
created at app startup and closed at shutdown — see app.py lifespan.

Auth is handled per-style:
  - openai     → "Authorization: Bearer <api_key>"
  - anthropic  → "x-api-key: <api_key>" + "anthropic-version: <version>"

The client's `base_url` is the upstream root; the proxy concatenates
the inbound path (e.g. "/v1/chat/completions") itself.
"""

from __future__ import annotations

from typing import Literal

import httpx

from .config import UpstreamConfig


UpstreamStyle = Literal["openai", "anthropic"]


def _default_headers(style: UpstreamStyle, api_key: str, version: str) -> dict[str, str]:
    if style == "openai":
        return {"Authorization": f"Bearer {api_key}"}
    if style == "anthropic":
        return {
            "x-api-key": api_key,
            "anthropic-version": version,
        }
    raise ValueError(f"unknown upstream style: {style!r}")


class UpstreamClient:
    """A live httpx client plus the headers we must inject on every call."""

    def __init__(self, cfg: UpstreamConfig) -> None:
        self.name = cfg.name
        self.style: UpstreamStyle = cfg.style  # type: ignore[assignment]
        self.base_url = str(cfg.base_url).rstrip("/")
        self.timeout = httpx.Timeout(cfg.timeout_seconds)
        # We strip the agent's Authorization/Content-Type/etc. in the proxy
        # and inject these headers instead — keeps auth in one place.
        self.inject_headers = _default_headers(cfg.style, cfg.api_key, cfg.version)
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout,
            headers=self.inject_headers,
            follow_redirects=False,
            # Don't pick up HTTP_PROXY/HTTPS_PROXY from the agent's
            # environment — the gateway MUST talk directly to the
            # configured upstream, never through some intermediate
            # proxy the agent happens to be using.
            trust_env=False,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    def request(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
        content: bytes | None = None,
    ) -> httpx.Request:
        """Build an httpx.Request that can be sent with `client.send()`
        (preferred for streaming) or `await client.send(...)`.

        The proxy module is the only caller.
        """
        merged_headers = dict(self.inject_headers)
        if headers:
            merged_headers.update(headers)
        return self._client.build_request(
            method=method,
            url=path if path.startswith("/") else f"/{path}",
            headers=merged_headers,
            params=params,
            content=content,
        )

    async def send(self, request: httpx.Request, *, stream: bool = False) -> httpx.Response:
        return await self._client.send(request, stream=stream)


class UpstreamPool:
    """Maps upstream name → UpstreamClient."""

    def __init__(self, configs: list[UpstreamConfig]) -> None:
        self._clients: dict[str, UpstreamClient] = {c.name: UpstreamClient(c) for c in configs}

    def get(self, name: str) -> UpstreamClient:
        try:
            return self._clients[name]
        except KeyError as exc:
            raise KeyError(f"unknown upstream: {name!r}") from exc

    async def aclose(self) -> None:
        for c in self._clients.values():
            await c.aclose()
