"""Data models for the Historical KB.

An ``AnalysisRecord`` captures everything the triage pipeline produces for one
defect — structured metadata for filtering **and** free-text fields for
semantic search.  The record is the atomic unit of the KB; it is embedded as a
single vector (or a small set of section-vectors) and stored alongside its full
JSON representation so both rich retrieval and exact lookup are fast.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Optional


# ---- verdict taxonomy (closed set) ----------------------------------------
VERDICTS = frozenset({
    "code_fix",          # bug in application source
    "config_change",     # wrong/missing configuration
    "infra",             # infrastructure/environment issue
    "dependency",        # third-party library / upstream bug
    "data_issue",        # corrupt / unexpected data
    "user_error",        # operator or user mistake
    "duplicate",         # duplicate of an existing ticket
    "wontfix",           # intentional behaviour / risk-accepted
    "needs_info",        # cannot determine — needs more context
    "not_a_bug",         # works as designed
})

# ---- defect type taxonomy --------------------------------------------------
DEFECT_TYPES = frozenset({
    "null_pointer",
    "class_cast",
    "arithmetic",
    "concurrent_modification",
    "number_format",
    "parse_error",
    "resource_leak",
    "timeout",
    "connection_failure",
    "auth_failure",
    "permission_denied",
    "missing_table",
    "schema_mismatch",
    "config_invalid",
    "thread_pool",
    "memory",
    "other",
})


@dataclass
class AnalysisRecord:
    """A completed defect-triage analysis.

    Required fields: ``ticket_id`` and ``summary``. Everything else has a
    sensible default so partial analyses can be stored early and enriched later
    via ``update_analysis``.
    """

    # ---- identity -----------------------------------------------------------
    ticket_id: str                         # Jira key, e.g. "NEX-3101"
    record_id: str = ""                    # unique KB ID (auto-generated)

    # ---- ticket context -----------------------------------------------------
    summary: str = ""                      # Jira summary / one-line description
    description: str = ""                  # full Jira description text
    product: str = ""                      # e.g. "nexpose-console"
    component: str = ""                    # e.g. "Report Engine"
    version: str = ""                      # affected version
    environment: str = ""                  # runtime environment (JDK, OS, …)
    reporter: str = ""
    priority: str = ""                     # Critical / High / Medium / Low
    labels: list[str] = field(default_factory=list)

    # ---- triage analysis (written by the agent) ----------------------------
    root_cause: str = ""                   # free-text root-cause analysis
    verdict: str = ""                      # one of VERDICTS
    defect_type: str = ""                  # one of DEFECT_TYPES (or free)
    severity_assessed: str = ""            # agent's own severity assessment
    confidence: float = 0.0                # 0.0-1.0 confidence in the verdict

    # ---- code location ------------------------------------------------------
    affected_class: str = ""               # e.g. "c.r.n.c.report.XmlReportGenerator"
    affected_method: str = ""              # e.g. "appendAsset"
    affected_file: str = ""                # e.g. "XmlReportGenerator.java"
    affected_line: int = 0                 # approximate line number

    # ---- error signature (for de-dup and similarity) -----------------------
    error_type: str = ""                   # e.g. "NullPointerException"
    error_message: str = ""                # first line of the exception message
    error_code: str = ""                   # stable app error code e.g. "NEXL-RPT-001"
    stack_trace_signature: str = ""        # normalised top-N frames fingerprint

    # ---- fix / resolution ---------------------------------------------------
    fix_description: str = ""              # what to change and why
    fix_type: str = ""                     # "code_change" | "config_change" | …
    pr_link: str = ""                      # pull request URL
    pr_status: str = ""                    # "open" | "merged" | "closed"
    commit_hash: str = ""
    branch: str = ""
    files_changed: list[str] = field(default_factory=list)

    # ---- linked artefacts ---------------------------------------------------
    confluence_page_ids: list[str] = field(default_factory=list)
    related_tickets: list[str] = field(default_factory=list)
    log_query_used: str = ""               # the query the agent ran on the log MCP
    log_chunks_referenced: list[str] = field(default_factory=list)

    # ---- timestamps ---------------------------------------------------------
    created_at: float = 0.0                # epoch seconds
    resolved_at: float = 0.0
    resolution_time_hours: float = 0.0
    updated_at: float = 0.0

    # ---- agent metadata -----------------------------------------------------
    analyst: str = ""                      # "si-triage-bot" or a human name
    model_used: str = ""                   # "claude-sonnet-4-6"
    pipeline_version: str = ""             # "1.0.0"

    # ---- free-form extension ------------------------------------------------
    tags: list[str] = field(default_factory=list)
    custom_fields: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.record_id:
            self.record_id = f"kb-{uuid.uuid4().hex[:12]}"
        if not self.created_at:
            self.created_at = time.time()
        if not self.updated_at:
            self.updated_at = self.created_at

    # ---- serialisation ------------------------------------------------------
    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, default=str)

    @classmethod
    def from_dict(cls, d: dict) -> "AnalysisRecord":
        known = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in d.items() if k in known}
        return cls(**filtered)

    @classmethod
    def from_json(cls, raw: str) -> "AnalysisRecord":
        return cls.from_dict(json.loads(raw))

    # ---- text for embedding -------------------------------------------------
    def searchable_text(self) -> str:
        """Concatenate all free-text fields into a single block for embedding.

        The order is intentional: the most semantically distinctive fields
        (error signature, root cause, fix) come first so they dominate the
        embedding when the text is long.
        """
        parts = [
            self.error_type,
            self.error_message,
            self.error_code,
            self.stack_trace_signature,
            self.root_cause,
            self.fix_description,
            self.summary,
            self.description,
            self.affected_class,
            self.affected_method,
            self.defect_type,
            self.verdict,
            self.component,
            self.product,
            " ".join(self.labels),
            " ".join(self.tags),
        ]
        return "\n".join(p for p in parts if p).strip()

    # ---- flat metadata for vector-store filters ----------------------------
    def filter_metadata(self) -> dict:
        """Flat string/numeric metadata safe for Chroma/numpy metadata filters."""
        return {
            "ticket_id": self.ticket_id,
            "record_id": self.record_id,
            "product": self.product,
            "component": self.component,
            "verdict": self.verdict,
            "defect_type": self.defect_type,
            "error_type": self.error_type,
            "error_code": self.error_code,
            "priority": self.priority,
            "severity_assessed": self.severity_assessed,
            "confidence": self.confidence,
            "affected_class": self.affected_class,
            "fix_type": self.fix_type,
            "analyst": self.analyst,
            "created_at": self.created_at,
            "resolved_at": self.resolved_at,
            "resolution_time_hours": self.resolution_time_hours,
        }
