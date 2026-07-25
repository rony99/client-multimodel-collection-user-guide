"""Command-line entry point for `lightweight-gateway`."""

from __future__ import annotations

import argparse
import logging
import sys

import uvicorn

from .app import create_app
from .config import load_config


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="lightweight-gateway",
        description="Trajectory collection proxy for agent → LLM API calls.",
    )
    parser.add_argument(
        "-c",
        "--config",
        required=True,
        help="Path to YAML config (see config.example.yaml).",
    )
    args = parser.parse_args()

    try:
        config = load_config(args.config)
    except Exception as exc:
        print(f"error: failed to load config: {exc}", file=sys.stderr)
        sys.exit(2)

    logging.basicConfig(
        level=getattr(logging, config.server.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # Silence noisy third-party loggers.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    uvicorn.run(
        create_app(config),
        host=config.server.host,
        port=config.server.port,
        log_level=config.server.log_level.lower(),
        # Don't pass `log_config=None` so uvicorn keeps its own access log.
    )


if __name__ == "__main__":
    main()
