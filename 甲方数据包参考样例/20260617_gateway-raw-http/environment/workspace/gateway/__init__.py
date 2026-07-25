"""Lightweight LLM API logging gateway.

A minimal, dependency-light HTTP proxy that records every agent → LLM
request/response to JSONL files and forwards to upstream OpenAI or
Anthropic providers.
"""

from __future__ import annotations

__version__ = "0.1.0"
