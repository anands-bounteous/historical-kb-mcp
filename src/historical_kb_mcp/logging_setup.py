"""Shared logging configuration for the Historical KB MCP."""
from __future__ import annotations

import logging
import os
import sys


def _build_handler() -> logging.Handler:
    handler = logging.StreamHandler(sys.stderr)
    if os.getenv("LOG_JSON", "0") == "1":
        import json, time

        class JsonFormatter(logging.Formatter):
            def format(self, record):
                return json.dumps({
                    "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
                    "level": record.levelname,
                    "logger": record.name,
                    "msg": record.getMessage(),
                }, default=str)

        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
            datefmt="%H:%M:%S",
        ))
    return handler


_root_configured = False


def get_logger(name: str) -> logging.Logger:
    global _root_configured
    if not _root_configured:
        root = logging.getLogger("historical_kb_mcp")
        root.setLevel(getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO))
        root.addHandler(_build_handler())
        root.propagate = False
        _root_configured = True
    return logging.getLogger(name)
