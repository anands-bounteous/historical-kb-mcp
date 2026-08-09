"""Shared logging configuration for the Historical KB MCP.

Logging is intentionally verbose: we log tool entry/exit with timing so a POC
investigation is traceable end-to-end, matching the Observability requirements
in the backend spec.

Log level is controlled by the ``LOG_LEVEL`` environment variable (default INFO).
Set ``LOG_JSON=1`` for structured single-line JSON logs; otherwise a
human-readable console format is used.

Every log record also carries a ``ticket_id`` field (default ``"-"``), sourced
from a contextvar rather than threaded through every function signature. Any
code running inside a tool call wrapped with :func:`with_tool_logging` picks up
that call's ticket automatically, so one ``grep 'ticket=EA-1234'`` across
``logs/historical_kb_mcp.log`` reconstructs everything this service did for
that ticket, at any point later — including after the process has restarted
(the file survives that; stderr alone does not).
"""
from __future__ import annotations

import inspect
import json
import logging
import os
import sys
import time
from contextvars import ContextVar, Token
from functools import wraps
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Callable, Optional

_ticket_id_var: ContextVar[str] = ContextVar("ticket_id", default="-")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_LOG_FILE = _REPO_ROOT / "logs" / "historical_kb_mcp.log"


def set_ticket_context(ticket_id: Optional[str]) -> Token:
    """Mark all logging on this async task / thread as belonging to ``ticket_id``
    until :func:`reset_ticket_context` is called with the returned token."""
    return _ticket_id_var.set(ticket_id or "-")


def reset_ticket_context(token: Token) -> None:
    _ticket_id_var.reset(token)


class _TicketIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.ticket_id = _ticket_id_var.get()
        return True


class _JsonFormatter(logging.Formatter):
    """Render each record as a single JSON line for log aggregators."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "ticket_id": getattr(record, "ticket_id", "-"),
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def _build_handlers() -> list[logging.Handler]:
    use_json = os.getenv("LOG_JSON", "0") == "1"
    if use_json:
        formatter: logging.Formatter = _JsonFormatter()
    else:
        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)-7s | %(name)s | ticket=%(ticket_id)s | %(message)s",
            datefmt="%H:%M:%S",
        )

    ticket_filter = _TicketIdFilter()

    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setFormatter(formatter)
    console_handler.addFilter(ticket_filter)

    _LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(_LOG_FILE, maxBytes=10_000_000, backupCount=5, encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler.addFilter(ticket_filter)

    return [console_handler, file_handler]


_root_configured = False


def get_logger(name: str) -> logging.Logger:
    global _root_configured
    if not _root_configured:
        root = logging.getLogger("historical_kb_mcp")
        root.setLevel(getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO))
        for handler in _build_handlers():
            root.addHandler(handler)
        root.propagate = False
        _root_configured = True
    return logging.getLogger(name)


def _format_call(sig: Optional[inspect.Signature], args: tuple, kwargs: dict) -> str:
    if sig is None:
        return ""
    try:
        bound = sig.bind_partial(*args, **kwargs)
    except TypeError:
        return ""
    parts = []
    for key, value in bound.arguments.items():
        text = repr(value)
        if len(text) > 120:
            text = text[:117] + "..."
        parts.append(f"{key}={text}")
    return ", ".join(parts)


def _extract_ticket_id(sig: Optional[inspect.Signature], args: tuple, kwargs: dict) -> Optional[str]:
    if "ticket_id" in kwargs:
        return kwargs["ticket_id"]
    if sig is None:
        return None
    try:
        bound = sig.bind_partial(*args, **kwargs)
    except TypeError:
        return None
    if "ticket_id" in bound.arguments:
        return bound.arguments["ticket_id"]
    # Some tools (e.g. store_analysis) accept a single ``data: dict`` payload
    # carrying ``ticket_id`` as a key rather than a direct parameter.
    for value in bound.arguments.values():
        if isinstance(value, dict) and "ticket_id" in value:
            return value["ticket_id"]
    return None


def with_tool_logging(func: Callable) -> Callable:
    """Decorator for MCP tool handlers.

    Sets the ``ticket_id`` log-correlation context (read from a ``ticket_id``
    argument, or a ``ticket_id`` key inside a dict argument, if present) for
    the duration of the call, and logs entry (with arguments), exit, and
    failure with elapsed milliseconds.
    """
    logger = get_logger(func.__module__)
    label = func.__name__
    try:
        sig: Optional[inspect.Signature] = inspect.signature(func)
    except (TypeError, ValueError):
        sig = None

    @wraps(func)
    async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
        token = set_ticket_context(_extract_ticket_id(sig, args, kwargs))
        start = time.perf_counter()
        logger.info("-> TOOL %s(%s) start", label, _format_call(sig, args, kwargs))
        try:
            result = await func(*args, **kwargs)
            elapsed = (time.perf_counter() - start) * 1000
            logger.info("<- TOOL %s done in %.1f ms", label, elapsed)
            return result
        except Exception:
            elapsed = (time.perf_counter() - start) * 1000
            logger.exception("!! TOOL %s failed after %.1f ms", label, elapsed)
            raise
        finally:
            reset_ticket_context(token)

    @wraps(func)
    def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
        token = set_ticket_context(_extract_ticket_id(sig, args, kwargs))
        start = time.perf_counter()
        logger.info("-> TOOL %s(%s) start", label, _format_call(sig, args, kwargs))
        try:
            result = func(*args, **kwargs)
            elapsed = (time.perf_counter() - start) * 1000
            logger.info("<- TOOL %s done in %.1f ms", label, elapsed)
            return result
        except Exception:
            elapsed = (time.perf_counter() - start) * 1000
            logger.exception("!! TOOL %s failed after %.1f ms", label, elapsed)
            raise
        finally:
            reset_ticket_context(token)

    return async_wrapper if inspect.iscoroutinefunction(func) else sync_wrapper
