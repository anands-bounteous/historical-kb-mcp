"""MCP server exposing Historical KB tools over stdio and HTTP.

Uses the @mcp.tool() decorator pattern — the correct FastMCP registration API.
Each wrapper delegates to the transport-agnostic handler in tools.py.
"""
from __future__ import annotations

from typing import Any

from .config import get_config
from .logging_setup import get_logger
from . import tools

logger = get_logger(__name__)


def build_server():
    """Construct a FastMCP server with all Historical KB tools registered."""
    from mcp.server.fastmcp import FastMCP  # lazy import

    mcp = FastMCP("historical-kb-mcp")

    @mcp.tool()
    def store_analysis(data: dict) -> dict:
        """Store a completed triage analysis in the Historical KB.

        Accepts a dictionary with ticket_id (required) and any of: summary,
        description, product, component, version, root_cause, verdict,
        defect_type, confidence, affected_class, affected_method, error_type,
        error_message, error_code, stack_trace_signature, fix_description,
        fix_type, pr_link, pr_status, commit_hash, branch, files_changed,
        confluence_page_ids, related_tickets, analyst, model_used, tags, etc.

        If the ticket already has a record, fields are merged (non-empty new
        values overwrite existing).
        """
        return tools.store_analysis(data)

    @mcp.tool()
    def get_analysis(ticket_id: str) -> dict:
        """Retrieve the full analysis record for a ticket by its Jira key.

        Returns every field: root_cause, verdict, fix_description, PR link,
        affected class/method, error signature, confidence, timestamps, and all
        linked artefacts.
        """
        return tools.get_analysis(ticket_id)

    @mcp.tool()
    def search_similar(query: str, top_k: int = 10,
                       component: str = "", verdict: str = "",
                       product: str = "", error_type: str = "") -> dict:
        """Hybrid semantic + keyword search for similar past defects in the KB.

        Combines dense vector similarity with BM25 keyword matching via
        Reciprocal Rank Fusion. Use this at the start of a new triage to find
        historical defects with similar error signatures, root causes, or
        affected components. Optional filters narrow results.
        """
        return tools.search_similar(query, top_k, component, verdict, product, error_type)

    @mcp.tool()
    def update_analysis(ticket_id: str, updates: dict) -> dict:
        """Update fields on an existing analysis record.

        Common use: adding the PR link and commit hash after the fix is merged,
        updating verdict after further investigation, or enriching with
        confluence_page_ids.
        """
        return tools.update_analysis(ticket_id, updates)

    @mcp.tool()
    def list_analyses(component: str = "", verdict: str = "",
                      product: str = "", limit: int = 50) -> dict:
        """List stored analyses with optional filters by component, verdict, or product.

        Returns a compact summary per record for browsing/dashboarding.
        """
        return tools.list_analyses(component, verdict, product, limit)

    @mcp.tool()
    def delete_analysis(ticket_id: str) -> dict:
        """Remove an analysis record from the KB (vectors, BM25 index, and JSON)."""
        return tools.delete_analysis(ticket_id)

    @mcp.tool()
    def get_kb_stats() -> dict:
        """Aggregate statistics: records by verdict, defect type, component,
        product, and average resolution time across the whole KB."""
        return tools.get_kb_stats()

    logger.info("Registered %d tools on historical-kb-mcp", len(tools.TOOL_FUNCTIONS))
    return mcp


def run(transport: str = "stdio") -> None:
    """Run the server on the given transport: 'stdio' or 'http'."""
    config = get_config()
    config.ensure_dirs()
    tools.get_engine()   # warm up engine + log backend selection

    mcp = build_server()

    if transport == "stdio":
        logger.info("Starting historical-kb-mcp on STDIO transport")
        mcp.run(transport="stdio")
    elif transport in ("http", "streamable-http"):
        mcp.settings.host = config.http_host
        mcp.settings.port = config.http_port
        logger.info(
            "Starting historical-kb-mcp on HTTP at http://%s:%d/mcp",
            config.http_host, config.http_port,
        )
        mcp.run(transport="streamable-http")
    else:
        raise ValueError(f"Unknown transport: {transport!r} (use 'stdio' or 'http')")
