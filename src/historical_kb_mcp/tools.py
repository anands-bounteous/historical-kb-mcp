"""Transport-agnostic tool handlers for the Historical KB MCP.

Plain functions with no MCP SDK dependency — the test suite exercises them
directly, and ``server.py`` registers thin ``@mcp.tool()`` wrappers.
"""
from __future__ import annotations

from typing import Any, Optional

from .logging_setup import get_logger, with_tool_logging
from .store import KBEngine

logger = get_logger(__name__)

_engine: Optional[KBEngine] = None


def get_engine() -> KBEngine:
    global _engine
    if _engine is None:
        _engine = KBEngine()
    return _engine


@with_tool_logging
def store_analysis(data: dict) -> dict:
    """Store a completed triage analysis in the KB.

    Accepts a dictionary with ticket_id (required) and any combination of:
    summary, description, product, component, version, environment, reporter,
    priority, labels, root_cause, verdict, defect_type, severity_assessed,
    confidence, affected_class, affected_method, affected_file, affected_line,
    error_type, error_message, error_code, stack_trace_signature,
    fix_description, fix_type, pr_link, pr_status, commit_hash, branch,
    files_changed, confluence_page_ids, related_tickets, log_query_used,
    log_chunks_referenced, analyst, model_used, pipeline_version, tags,
    custom_fields, resolved_at, resolution_time_hours.

    If a record for the same ticket_id already exists, the fields are merged
    (existing values preserved unless overwritten by non-empty new values).
    """
    return get_engine().store_analysis(data)


@with_tool_logging
def get_analysis(ticket_id: str) -> dict:
    """Retrieve the full analysis record for a ticket by its Jira key."""
    return get_engine().get_analysis(ticket_id)


def search_similar(query: str, top_k: int = 10,
                   component: str = "", verdict: str = "",
                   product: str = "", error_type: str = "") -> dict:
    """Hybrid semantic + keyword search for similar past defects.

    Combines dense vector similarity (captures semantic meaning like
    'payment failed' ≈ 'authorization error') with BM25 keyword matching
    (nails exact identifiers like class names, error codes, CVEs) using
    Reciprocal Rank Fusion.

    Optional filters narrow the search to a specific component, verdict,
    product, or error type.
    """
    logger.info("TOOL search_similar(query=%r, top_k=%d, component=%r, "
                "verdict=%r, product=%r, error_type=%r)",
                query[:60], top_k, component, verdict, product, error_type)
    filters = {}
    if component:
        filters["component"] = component
    if verdict:
        filters["verdict"] = verdict
    if product:
        filters["product"] = product
    if error_type:
        filters["error_type"] = error_type
    return get_engine().search_similar(query, top_k, filters or None)


@with_tool_logging
def update_analysis(ticket_id: str, updates: dict) -> dict:
    """Update specific fields on an existing analysis (e.g. add PR link after merge).

    Accepts a dictionary of field names and new values. Only fields present in
    the AnalysisRecord schema are updated; record_id, ticket_id, and created_at
    are immutable.
    """
    return get_engine().update_analysis(ticket_id, updates)


def list_analyses(component: str = "", verdict: str = "",
                  product: str = "", limit: int = 50) -> dict:
    """List stored analyses with optional filters.

    Returns a summary of each record (ticket_id, summary, verdict,
    defect_type, component, product, priority, pr_link, created_at).
    """
    logger.info("TOOL list_analyses(component=%r, verdict=%r, product=%r, limit=%d)",
                component, verdict, product, limit)
    return get_engine().list_analyses(component, verdict, product, limit)


@with_tool_logging
def delete_analysis(ticket_id: str) -> dict:
    """Remove an analysis record from the KB entirely (vectors, BM25, JSON)."""
    return get_engine().delete_analysis(ticket_id)


def get_kb_stats() -> dict:
    """Aggregate statistics across the KB: counts by verdict, defect type,
    component, product, and average resolution time."""
    logger.info("TOOL get_kb_stats()")
    return get_engine().get_kb_stats()


TOOL_FUNCTIONS = [
    store_analysis,
    get_analysis,
    search_similar,
    update_analysis,
    list_analyses,
    delete_analysis,
    get_kb_stats,
]
