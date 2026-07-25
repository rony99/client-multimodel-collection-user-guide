"""FastAPI app factory + lifespan management.

The app holds a `GatewayState` object on `app.state.gateway` that bundles
the router, upstream pool, and trajectory writer. Created at startup,
closed at shutdown.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI

from .config import GatewayConfig
from .proxy import router as proxy_router
from .raw_http_log import RawHttpLogger, create_raw_http_logger
from .routing import Router
from .upstream import UpstreamPool
from .writer import TrajectoryWriter

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class GatewayState:
    """All long-lived objects the proxy depends on."""

    config: GatewayConfig
    router: Router
    pool: UpstreamPool
    writer: TrajectoryWriter
    raw_http_logger: RawHttpLogger | None = None


def create_app(config: GatewayConfig) -> FastAPI:
    """Build a FastAPI app bound to the given gateway config."""
    log_dir = Path(config.log.dir).expanduser().resolve()
    pool = UpstreamPool(config.upstreams)
    writer = TrajectoryWriter(log_dir)
    router = Router(
        routes=[r.model_dump() for r in config.routes],
        upstream_names=config.upstream_names(),
    )
    # Raw HTTP trace logger (optional, gated by env var or config field).
    config_raw_dir = getattr(config, "raw_http_dir", None)
    raw_http_logger = create_raw_http_logger(config_raw_dir)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        log_dir.mkdir(parents=True, exist_ok=True)
        app.state.gateway = GatewayState(
            config=config,
            router=router,
            pool=pool,
            writer=writer,
            raw_http_logger=raw_http_logger,
        )
        logger.info(
            "Gateway ready: %d upstream(s), %d route(s), log_dir=%s",
            len(config.upstreams),
            len(config.routes),
            log_dir,
        )
        logger.info("Routable model_ids: %s", router.known_model_ids())
        try:
            yield
        finally:
            await pool.aclose()
            await writer.close()

    app = FastAPI(
        title="Lightweight LLM API Gateway",
        version="0.1.0",
        description="Trajectory collection proxy for agent → LLM calls.",
        docs_url="/docs",
        redoc_url=None,
        lifespan=lifespan,
    )

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(proxy_router)
    return app
