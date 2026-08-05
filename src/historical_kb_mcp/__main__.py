"""CLI entrypoint: run the Historical KB MCP over stdio or HTTP.

Examples
--------
    python -m historical_kb_mcp --transport stdio
    python -m historical_kb_mcp --transport http
    MCP_HTTP_PORT=8082 python -m historical_kb_mcp --transport http
"""
from __future__ import annotations

import argparse

from .logging_setup import get_logger
from .server import run

logger = get_logger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(prog="historical-kb-mcp")
    parser.add_argument(
        "--transport", choices=["stdio", "http"], default="stdio",
        help="Transport to serve on (default: stdio).",
    )
    args = parser.parse_args()
    logger.info("Launching historical-kb-mcp (transport=%s)", args.transport)
    run(transport=args.transport)


if __name__ == "__main__":
    main()
