"""Tests for the Historical KB MCP — exercises the full pipeline offline.

No MCP SDK required; tests call tool handlers directly.
Run with: python tests/_runner.py  (or pytest when available)
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path


def test_model_roundtrip(tmp_path: Path):
    """AnalysisRecord serialises to JSON and deserialises losslessly."""
    os.environ["SI_DATA_DIR"] = str(tmp_path / "si")
    from historical_kb_mcp.models import AnalysisRecord

    rec = AnalysisRecord(
        ticket_id="TEST-1",
        summary="Widget crashes on null input",
        root_cause="Missing null check in Widget.process()",
        verdict="code_fix",
        defect_type="null_pointer",
        affected_class="com.example.Widget",
        affected_method="process",
        error_type="NullPointerException",
        pr_link="https://github.com/example/pr/42",
        tags=["null-check", "widget"],
        confidence=0.95,
    )
    json_str = rec.to_json()
    restored = AnalysisRecord.from_json(json_str)
    assert restored.ticket_id == "TEST-1"
    assert restored.verdict == "code_fix"
    assert restored.confidence == 0.95
    assert restored.pr_link == "https://github.com/example/pr/42"
    assert "null-check" in restored.tags
    assert restored.record_id == rec.record_id
    assert restored.created_at > 0


def test_searchable_text(tmp_path: Path):
    """searchable_text concatenates the right fields in priority order."""
    os.environ["SI_DATA_DIR"] = str(tmp_path / "si")
    from historical_kb_mcp.models import AnalysisRecord

    rec = AnalysisRecord(
        ticket_id="T-2",
        summary="Login fails",
        error_type="AuthException",
        root_cause="LDAP misconfigured",
        affected_class="AuthService",
    )
    text = rec.searchable_text()
    assert "AuthException" in text
    assert "LDAP misconfigured" in text
    assert "AuthService" in text
    # error_type should come before summary (priority ordering)
    assert text.index("AuthException") < text.index("Login fails")


def test_filter_metadata(tmp_path: Path):
    """filter_metadata returns flat metadata safe for Chroma."""
    os.environ["SI_DATA_DIR"] = str(tmp_path / "si")
    from historical_kb_mcp.models import AnalysisRecord

    rec = AnalysisRecord(
        ticket_id="T-3",
        component="Scan Engine",
        verdict="code_fix",
        defect_type="resource_leak",
        confidence=0.88,
    )
    meta = rec.filter_metadata()
    assert meta["ticket_id"] == "T-3"
    assert meta["component"] == "Scan Engine"
    assert meta["verdict"] == "code_fix"
    assert meta["confidence"] == 0.88
    # All values must be str, int, float, or bool (Chroma requirement)
    for v in meta.values():
        assert isinstance(v, (str, int, float, bool))


def test_bm25_basic(tmp_path: Path):
    """BM25 returns keyword matches ranked by relevance."""
    os.environ["SI_DATA_DIR"] = str(tmp_path / "si")
    os.environ["EMBED_BACKEND"] = "hashing"
    os.environ["VECTOR_BACKEND"] = "numpy"
    from historical_kb_mcp.store import BM25Index

    idx = BM25Index()
    idx.add("d1", "NullPointerException in XmlReportGenerator.appendAsset")
    idx.add("d2", "ArithmeticException divide by zero in RiskCalculator")
    idx.add("d3", "ConcurrentModificationException in AssetCorrelator")

    results = idx.search("NullPointerException", top_k=3)
    assert len(results) > 0
    assert results[0][0] == "d1"  # exact keyword match should rank first

    results2 = idx.search("ArithmeticException divide zero", top_k=3)
    assert results2[0][0] == "d2"


def test_store_and_retrieve(tmp_path: Path):
    """store_analysis persists a record; get_analysis retrieves it."""
    os.environ["SI_DATA_DIR"] = str(tmp_path / "si")
    os.environ["EMBED_BACKEND"] = "hashing"
    os.environ["VECTOR_BACKEND"] = "numpy"
    # Reset singleton
    import historical_kb_mcp.tools as t
    t._engine = None

    result = t.store_analysis({
        "ticket_id": "NEX-9999",
        "summary": "Test defect for KB",
        "root_cause": "Off-by-one in loop counter",
        "verdict": "code_fix",
        "defect_type": "arithmetic",
        "affected_class": "com.example.LoopProcessor",
        "error_type": "ArrayIndexOutOfBoundsException",
        "pr_link": "https://github.com/example/pr/999",
    })
    assert result["action"] == "created"
    assert result["ticket_id"] == "NEX-9999"

    retrieved = t.get_analysis("NEX-9999")
    assert retrieved["ticket_id"] == "NEX-9999"
    assert retrieved["root_cause"] == "Off-by-one in loop counter"
    assert retrieved["pr_link"] == "https://github.com/example/pr/999"


def test_update_analysis(tmp_path: Path):
    """update_analysis patches fields without losing existing data."""
    os.environ["SI_DATA_DIR"] = str(tmp_path / "si")
    os.environ["EMBED_BACKEND"] = "hashing"
    os.environ["VECTOR_BACKEND"] = "numpy"
    import historical_kb_mcp.tools as t
    t._engine = None

    t.store_analysis({
        "ticket_id": "NEX-8888",
        "summary": "Scan times out under load",
        "verdict": "needs_info",
    })

    t.update_analysis("NEX-8888", {
        "verdict": "code_fix",
        "pr_link": "https://github.com/example/pr/888",
        "confidence": 0.92,
    })

    rec = t.get_analysis("NEX-8888")
    assert rec["verdict"] == "code_fix"
    assert rec["pr_link"] == "https://github.com/example/pr/888"
    assert rec["confidence"] == 0.92
    assert rec["summary"] == "Scan times out under load"  # not lost


def test_search_similar(tmp_path: Path):
    """search_similar returns ranked results from hybrid retrieval."""
    os.environ["SI_DATA_DIR"] = str(tmp_path / "si")
    os.environ["EMBED_BACKEND"] = "hashing"
    os.environ["VECTOR_BACKEND"] = "numpy"
    import historical_kb_mcp.tools as t
    t._engine = None

    t.store_analysis({
        "ticket_id": "T-A",
        "summary": "NullPointerException in report generation",
        "error_type": "NullPointerException",
        "affected_class": "ReportGenerator",
        "component": "Report Engine",
        "verdict": "code_fix",
    })
    t.store_analysis({
        "ticket_id": "T-B",
        "summary": "LDAP connection timeout on directory login",
        "error_type": "CommunicationException",
        "affected_class": "LdapAuthenticator",
        "component": "Authentication",
        "verdict": "config_change",
    })
    t.store_analysis({
        "ticket_id": "T-C",
        "summary": "ClassCastException in report section handling",
        "error_type": "ClassCastException",
        "affected_class": "ReportEngine",
        "component": "Report Engine",
        "verdict": "code_fix",
    })

    result = t.search_similar("NullPointerException report", top_k=3)
    assert result["count"] >= 1
    tickets = [r["ticket_id"] for r in result["results"]]
    assert "T-A" in tickets  # best match for NPE + report

    # Filter by component
    filtered = t.search_similar("exception", top_k=3, component="Report Engine")
    ftids = [r["ticket_id"] for r in filtered["results"]]
    assert "T-B" not in ftids  # Auth component should be excluded


def test_delete_analysis(tmp_path: Path):
    """delete_analysis removes the record from vectors, BM25, and disk."""
    os.environ["SI_DATA_DIR"] = str(tmp_path / "si")
    os.environ["EMBED_BACKEND"] = "hashing"
    os.environ["VECTOR_BACKEND"] = "numpy"
    import historical_kb_mcp.tools as t
    t._engine = None

    t.store_analysis({"ticket_id": "DEL-1", "summary": "To be deleted"})
    assert t.get_analysis("DEL-1")["ticket_id"] == "DEL-1"

    t.delete_analysis("DEL-1")
    assert "error" in t.get_analysis("DEL-1")


def test_list_analyses(tmp_path: Path):
    """list_analyses returns filtered summaries."""
    os.environ["SI_DATA_DIR"] = str(tmp_path / "si")
    os.environ["EMBED_BACKEND"] = "hashing"
    os.environ["VECTOR_BACKEND"] = "numpy"
    import historical_kb_mcp.tools as t
    t._engine = None

    t.store_analysis({"ticket_id": "L-1", "component": "Scan", "verdict": "code_fix"})
    t.store_analysis({"ticket_id": "L-2", "component": "Report", "verdict": "code_fix"})
    t.store_analysis({"ticket_id": "L-3", "component": "Scan", "verdict": "config_change"})

    all_r = t.list_analyses()
    assert all_r["count"] == 3

    scan_only = t.list_analyses(component="Scan")
    assert scan_only["count"] == 2

    config_only = t.list_analyses(verdict="config_change")
    assert config_only["count"] == 1
    assert config_only["records"][0]["ticket_id"] == "L-3"


def test_kb_stats(tmp_path: Path):
    """get_kb_stats returns meaningful aggregates."""
    os.environ["SI_DATA_DIR"] = str(tmp_path / "si")
    os.environ["EMBED_BACKEND"] = "hashing"
    os.environ["VECTOR_BACKEND"] = "numpy"
    import historical_kb_mcp.tools as t
    t._engine = None

    t.store_analysis({"ticket_id": "S-1", "verdict": "code_fix", "defect_type": "null_pointer",
                       "component": "Report", "resolution_time_hours": 0.5})
    t.store_analysis({"ticket_id": "S-2", "verdict": "config_change", "defect_type": "config_invalid",
                       "component": "Auth", "resolution_time_hours": 0.1})

    stats = t.get_kb_stats()
    assert stats["total_records"] == 2
    assert stats["by_verdict"]["code_fix"] == 1
    assert stats["by_verdict"]["config_change"] == 1
    assert stats["by_defect_type"]["null_pointer"] == 1
    assert stats["avg_resolution_hours"] > 0


def test_upsert_merge(tmp_path: Path):
    """Storing the same ticket_id again merges fields, not duplicates."""
    os.environ["SI_DATA_DIR"] = str(tmp_path / "si")
    os.environ["EMBED_BACKEND"] = "hashing"
    os.environ["VECTOR_BACKEND"] = "numpy"
    import historical_kb_mcp.tools as t
    t._engine = None

    t.store_analysis({"ticket_id": "M-1", "summary": "Initial", "verdict": "needs_info"})
    t.store_analysis({"ticket_id": "M-1", "verdict": "code_fix", "pr_link": "https://pr/1"})

    rec = t.get_analysis("M-1")
    assert rec["summary"] == "Initial"      # preserved from first store
    assert rec["verdict"] == "code_fix"     # overwritten by second store
    assert rec["pr_link"] == "https://pr/1"

    # Should still be only 1 record
    listing = t.list_analyses()
    assert listing["count"] == 1


def test_seed_loads_all_defects(tmp_path: Path):
    """The seed module populates 10 records into the KB."""
    os.environ["SI_DATA_DIR"] = str(tmp_path / "si")
    os.environ["EMBED_BACKEND"] = "hashing"
    os.environ["VECTOR_BACKEND"] = "numpy"
    import historical_kb_mcp.tools as t
    t._engine = None

    from historical_kb_mcp.seed import seed
    seed()

    stats = t.get_kb_stats()
    assert stats["total_records"] == 10
    assert stats["vector_count"] == 10
    assert "code_fix" in stats["by_verdict"]
    assert "config_change" in stats["by_verdict"]

    # Verify a specific record
    rec = t.get_analysis("NEX-3101")
    assert rec["error_type"] == "NullPointerException"
    assert rec["affected_class"] == "com.rapid7.nexpose.console.report.XmlReportGenerator"
    assert "pr_link" in rec and rec["pr_link"]
