#!/usr/bin/env python3
"""Seed the Historical KB with completed analyses for all 10 Nexpose defects.

Run after starting the KB engine (or import directly in tests):

    python -m historical_kb_mcp.seed

This populates the KB with rich, realistic triage records — one per planted
defect — so search_similar returns meaningful results the moment the system
goes live.  Each record has the full metadata: root cause, verdict, fix,
affected class/method, error signature, PR link (fictional), and linked tickets.
"""
from __future__ import annotations

import sys
import time

from .logging_setup import get_logger
from .tools import get_engine

logger = get_logger(__name__)

SEED_RECORDS = [
    {
        "ticket_id": "NEX-3101",
        "summary": "XML report generation throws NullPointerException for unfingerprinted assets",
        "description": (
            "Generating an XML scan report via /report/xml fails with NPE when the scan "
            "contains an asset that was discovered but not fingerprinted (vulnerability list is null). "
            "This affects roughly 1 in 6 hosts in any multi-target scan."
        ),
        "product": "nexpose-root",
        "component": "Report Engine",
        "version": "1.0.0",
        "environment": "Spring Boot 3.2.5, Java 17, H2 in-memory",
        "reporter": "si-triage-bot",
        "priority": "High",
        "labels": ["report", "xml", "npe", "nsc"],
        "root_cause": (
            "XmlReportGenerator.appendAsset() iterates asset.getVulnerabilities() with a for-each "
            "loop and calls .size() without first checking for null. The MockScanEngine legitimately "
            "returns live-but-unfingerprinted assets whose vulnerability list is null, so the very "
            "first such asset in the report triggers a NullPointerException."
        ),
        "verdict": "code_fix",
        "defect_type": "null_pointer",
        "severity_assessed": "High",
        "confidence": 0.97,
        "affected_class": "com.rapid7.nexpose.console.report.XmlReportGenerator",
        "affected_method": "appendAsset",
        "affected_file": "XmlReportGenerator.java",
        "affected_line": 83,
        "error_type": "NullPointerException",
        "error_message": 'Cannot invoke "java.util.List.size()" because the return value of "...getVulnerabilities()" is null',
        "error_code": "NEXL-RPT-001",
        "stack_trace_signature": "XmlReportGenerator.appendAsset:83 > XmlReportGenerator.generate:47 > ReportService.generateXml:44",
        "fix_description": (
            "Add a null-guard before iterating the vulnerability list: "
            "List<Vulnerability> vulns = asset.getVulnerabilities(); "
            "if (vulns == null) vulns = List.of(); "
            "then use vulns instead of asset.getVulnerabilities() for both .size() and the for-each."
        ),
        "fix_type": "code_change",
        "pr_link": "https://github.com/rapid7/nexpose-console/pull/1501",
        "pr_status": "merged",
        "commit_hash": "a1b2c3d",
        "branch": "fix/NEX-3101-report-npe",
        "files_changed": ["nexpose-console/src/main/java/com/rapid7/nexpose/console/report/XmlReportGenerator.java"],
        "related_tickets": ["NEX-3105"],
        "analyst": "si-triage-bot",
        "model_used": "claude-sonnet-4-6",
        "pipeline_version": "1.0.0",
        "tags": ["report", "null-check", "defensive-coding"],
        "resolution_time_hours": 0.4,
    },
    {
        "ticket_id": "NEX-3102",
        "summary": "RiskCalculator throws ArithmeticException (/ by zero) for assets with no vulnerabilities",
        "product": "nexpose-console",
        "component": "Risk Scoring",
        "priority": "High",
        "labels": ["risk", "arithmetic", "scan"],
        "root_cause": (
            "RiskCalculator.averageCvss() divides totalPenalty by count without guarding against "
            "zero. A fingerprinted asset with an empty (non-null) vulnerability list drives count "
            "to 0 and throws ArithmeticException: / by zero."
        ),
        "verdict": "code_fix",
        "defect_type": "arithmetic",
        "severity_assessed": "High",
        "confidence": 0.98,
        "affected_class": "com.rapid7.nexpose.console.risk.RiskCalculator",
        "affected_method": "averageCvss",
        "affected_file": "RiskCalculator.java",
        "affected_line": 74,
        "error_type": "ArithmeticException",
        "error_message": "/ by zero",
        "stack_trace_signature": "RiskCalculator.averageCvss:74 > RiskCalculator.scoreAsset:52 > ScanService.executeScan:118",
        "fix_description": "Add if (count == 0) return 0.0; before the division.",
        "fix_type": "code_change",
        "pr_link": "https://github.com/rapid7/nexpose-console/pull/1502",
        "pr_status": "merged",
        "commit_hash": "b2c3d4e",
        "branch": "fix/NEX-3102-risk-divzero",
        "files_changed": ["nexpose-console/src/main/java/com/rapid7/nexpose/console/risk/RiskCalculator.java"],
        "analyst": "si-triage-bot",
        "model_used": "claude-sonnet-4-6",
        "tags": ["zero-guard", "arithmetic"],
        "resolution_time_hours": 0.2,
    },
    {
        "ticket_id": "NEX-3103",
        "summary": "Malformed CIDR target raises NumberFormatException instead of a validation error",
        "product": "nexpose-console",
        "component": "Scan Targeting",
        "priority": "Medium",
        "labels": ["scan", "cidr", "validation"],
        "root_cause": (
            "IpAddressUtils.expandCidr() splits the prefix and parses with Integer.parseInt() "
            "without validating the token is numeric. A malformed prefix like '2a' throws "
            "NumberFormatException which escapes into the scan pipeline."
        ),
        "verdict": "code_fix",
        "defect_type": "number_format",
        "confidence": 0.95,
        "affected_class": "com.rapid7.nexpose.console.util.IpAddressUtils",
        "affected_method": "expandCidr",
        "affected_file": "IpAddressUtils.java",
        "affected_line": 71,
        "error_type": "NumberFormatException",
        "error_message": 'For input string: "2a"',
        "stack_trace_signature": "IpAddressUtils.expandCidr:71 > ScanTargetParser.resolve:38 > ScanService.executeScan:112",
        "fix_description": "Validate parts.length == 2 and parts[1].matches('\\\\d+') before parsing; throw InvalidScanTargetException on failure.",
        "fix_type": "code_change",
        "pr_link": "https://github.com/rapid7/nexpose-console/pull/1503",
        "pr_status": "merged",
        "files_changed": ["nexpose-console/src/main/java/com/rapid7/nexpose/console/util/IpAddressUtils.java"],
        "analyst": "si-triage-bot",
        "tags": ["input-validation", "cidr"],
        "resolution_time_hours": 0.3,
    },
    {
        "ticket_id": "NEX-3104",
        "summary": "Asset correlation throws ConcurrentModificationException on duplicate assets",
        "product": "nexpose-console",
        "component": "Correlation",
        "priority": "High",
        "labels": ["correlation", "cme", "scan"],
        "root_cause": (
            "AssetCorrelator.mergeDuplicates() removes elements from the list during an enhanced "
            "for-loop. The first duplicate triggers list mutation mid-iteration causing "
            "ConcurrentModificationException."
        ),
        "verdict": "code_fix",
        "defect_type": "concurrent_modification",
        "confidence": 0.99,
        "affected_class": "com.rapid7.nexpose.console.correlation.AssetCorrelator",
        "affected_method": "mergeDuplicates",
        "affected_file": "AssetCorrelator.java",
        "affected_line": 52,
        "error_type": "ConcurrentModificationException",
        "error_code": "NEXL-CORR-001",
        "stack_trace_signature": "AssetCorrelator.mergeDuplicates:52 > ScanService.executeScan:115",
        "fix_description": "Use an explicit Iterator and call iterator.remove(), or collect survivors into a new list.",
        "fix_type": "code_change",
        "pr_link": "https://github.com/rapid7/nexpose-console/pull/1504",
        "pr_status": "merged",
        "files_changed": ["nexpose-console/src/main/java/com/rapid7/nexpose/console/correlation/AssetCorrelator.java"],
        "analyst": "si-triage-bot",
        "tags": ["iterator", "collections", "concurrent-modification"],
        "resolution_time_hours": 0.25,
    },
    {
        "ticket_id": "NEX-3105",
        "summary": "ReportEngine throws ClassCastException assembling the sectioned report layout",
        "product": "nexpose-console",
        "component": "Report Engine",
        "priority": "Medium",
        "root_cause": (
            "ReportEngine.assetSectionOf() casts sections.get(0) to AssetReportSection, but "
            "buildSections() adds SummaryReportSection first. The cast always fails."
        ),
        "verdict": "code_fix",
        "defect_type": "class_cast",
        "confidence": 0.98,
        "affected_class": "com.rapid7.nexpose.console.report.ReportEngine",
        "affected_method": "assetSectionOf",
        "affected_file": "ReportEngine.java",
        "affected_line": 81,
        "error_type": "ClassCastException",
        "error_code": "NEXL-RPT-001",
        "stack_trace_signature": "ReportEngine.assetSectionOf:81 > ReportEngine.generateXml:52 > ReportService.previewLayout:51",
        "fix_description": "Locate the asset section by type (stream + filter) instead of by index.",
        "fix_type": "code_change",
        "pr_link": "https://github.com/rapid7/nexpose-console/pull/1505",
        "pr_status": "merged",
        "related_tickets": ["NEX-3101"],
        "analyst": "si-triage-bot",
        "tags": ["type-safety", "polymorphism"],
        "resolution_time_hours": 0.3,
    },
    {
        "ticket_id": "NEX-3106",
        "summary": "Scan detail page fails to parse engine timestamps with a numeric GMT offset",
        "product": "nexpose-console",
        "component": "Utilities / Date handling",
        "priority": "Medium",
        "root_cause": (
            "DateUtils.parseScanTimestamp() uses pattern yyyy-MM-dd'T'HH:mm:ss'Z' with a literal "
            "'Z'. Engine timestamps carry +00:00 offset which never matches the literal pattern."
        ),
        "verdict": "code_fix",
        "defect_type": "parse_error",
        "confidence": 0.96,
        "affected_class": "com.rapid7.nexpose.console.util.DateUtils",
        "affected_method": "parseScanTimestamp",
        "affected_file": "DateUtils.java",
        "affected_line": 42,
        "error_type": "IllegalArgumentException",
        "error_message": "Unparseable scan timestamp: 2026-08-04T09:21:07+00:00",
        "stack_trace_signature": "DateUtils.parseScanTimestamp:42 > ScanService.parseCompletion:139 > ScanController.scanDetail:70",
        "fix_description": "Use java.time.OffsetDateTime.parse(value) or pattern yyyy-MM-dd'T'HH:mm:ssXXX.",
        "fix_type": "code_change",
        "pr_link": "https://github.com/rapid7/nexpose-console/pull/1506",
        "pr_status": "merged",
        "analyst": "si-triage-bot",
        "tags": ["date-parsing", "timezone", "iso8601"],
        "resolution_time_hours": 0.2,
    },
    {
        "ticket_id": "NEX-3107",
        "summary": "Scan engine pool leaks slots on scan failure and becomes permanently exhausted",
        "product": "nexpose-console",
        "component": "Scan Engine Pool",
        "priority": "Critical",
        "root_cause": (
            "ScanEnginePool.runScan() releases its Semaphore permit only on the normal return "
            "path. When engine.scan() throws, the permit is never released. After pool-size "
            "failures every slot is leaked and subsequent scans fail permanently."
        ),
        "verdict": "code_fix",
        "defect_type": "resource_leak",
        "severity_assessed": "Critical",
        "confidence": 0.99,
        "affected_class": "com.rapid7.nexpose.console.scan.ScanEnginePool",
        "affected_method": "runScan",
        "affected_file": "ScanEnginePool.java",
        "affected_line": 83,
        "error_type": "ScanEnginePoolExhaustedException",
        "error_code": "NEXL-SCAN-002",
        "stack_trace_signature": "ScanEnginePool.runScan:78 > ScanService.executeScan:114",
        "fix_description": "Wrap engine.scan() in try/finally and call permits.release() in the finally block.",
        "fix_type": "code_change",
        "pr_link": "https://github.com/rapid7/nexpose-console/pull/1507",
        "pr_status": "merged",
        "analyst": "si-triage-bot",
        "tags": ["resource-leak", "semaphore", "concurrency", "finally-block"],
        "resolution_time_hours": 0.35,
    },
    {
        "ticket_id": "NEX-3108",
        "summary": "Directory (LDAP) logins fail: nexpose.ldap.url / base-dn point at a non-existent server",
        "product": "nexpose-root",
        "component": "Authentication / LDAP",
        "priority": "High",
        "root_cause": (
            "application.properties ships nexpose.ldap.url=ldap://ldap.internal.rapid7.local:389 "
            "and nexpose.ldap.base-dn=dc=rapid7,dc=local. That host does not resolve and the "
            "base DN is wrong. Every LDAP bind fails with CommunicationException / "
            "UnknownHostException. The code is correct; the configuration is wrong."
        ),
        "verdict": "config_change",
        "defect_type": "config_invalid",
        "confidence": 0.99,
        "affected_class": "com.rapid7.nexpose.console.auth.LdapAuthenticator",
        "affected_method": "authenticate",
        "affected_file": "application.properties",
        "error_type": "LdapConnectionException",
        "error_code": "NEXL-AUTH-002",
        "stack_trace_signature": "LdapAuthenticator.authenticate:71 > AuthService.login:53",
        "fix_description": "Correct two properties: nexpose.ldap.url=ldap://ldap.lab.rapid7.com:389 and nexpose.ldap.base-dn=dc=rapid7,dc=com. No code change.",
        "fix_type": "config_change",
        "pr_link": "https://github.com/rapid7/nexpose-root/pull/301",
        "pr_status": "merged",
        "files_changed": ["nexpose-root/src/main/resources/application.properties"],
        "analyst": "si-triage-bot",
        "tags": ["config", "ldap", "auth", "dns"],
        "resolution_time_hours": 0.1,
    },
    {
        "ticket_id": "NEX-3109",
        "summary": "Report History fails: REPORT_HISTORY table missing because SQL init is disabled",
        "product": "nexpose-root",
        "component": "Persistence / H2",
        "priority": "Medium",
        "root_cause": (
            "The report_history table is created by schema.sql which Spring Boot only runs when "
            "spring.sql.init.mode is enabled. The shipped value is 'never' so the script is "
            "skipped and ReportHistoryDao fails with Table REPORT_HISTORY not found."
        ),
        "verdict": "config_change",
        "defect_type": "missing_table",
        "confidence": 0.98,
        "affected_class": "com.rapid7.nexpose.nsc.repository.ReportHistoryDao",
        "affected_method": "recent",
        "affected_file": "application.properties",
        "error_type": "BadSqlGrammarException",
        "stack_trace_signature": "ReportHistoryDao.recent:57 > ReportController.history:78",
        "fix_description": "Set spring.sql.init.mode=always in application.properties. No code change.",
        "fix_type": "config_change",
        "pr_link": "https://github.com/rapid7/nexpose-root/pull/302",
        "pr_status": "merged",
        "files_changed": ["nexpose-root/src/main/resources/application.properties"],
        "analyst": "si-triage-bot",
        "tags": ["config", "h2", "sql-init", "schema"],
        "resolution_time_hours": 0.1,
    },
    {
        "ticket_id": "NEX-3110",
        "summary": "Background scans fail: async executor max pool size is 0",
        "product": "nexpose-root",
        "component": "Scan Scheduler",
        "priority": "High",
        "root_cause": (
            "application.properties sets nexpose.scan.async.max-pool-size=0. "
            "ThreadPoolExecutor requires max > 0 so initialization throws "
            "IllegalArgumentException on the first background scan submission."
        ),
        "verdict": "config_change",
        "defect_type": "thread_pool",
        "confidence": 0.99,
        "affected_class": "com.rapid7.nexpose.nsc.service.ScanService",
        "affected_method": "submitBackground",
        "affected_file": "application.properties",
        "error_type": "IllegalArgumentException",
        "error_message": "Max pool size must be greater than zero",
        "stack_trace_signature": "ScanService.submitBackground:96 > ScanService.runScan:78 > ScanController.runScan:60",
        "fix_description": "Set nexpose.scan.async.max-pool-size=4 (>= core-pool-size). No code change.",
        "fix_type": "config_change",
        "pr_link": "https://github.com/rapid7/nexpose-root/pull/303",
        "pr_status": "merged",
        "files_changed": ["nexpose-root/src/main/resources/application.properties"],
        "analyst": "si-triage-bot",
        "tags": ["config", "executor", "threadpool", "async"],
        "resolution_time_hours": 0.1,
    },
]


def seed() -> None:
    """Store all seed records into the KB."""
    engine = get_engine()
    for i, rec_data in enumerate(SEED_RECORDS, 1):
        rec_data.setdefault("resolved_at", time.time())
        result = engine.store_analysis(rec_data)
        logger.info("[%02d/%d] %s: %s → %s",
                    i, len(SEED_RECORDS), rec_data["ticket_id"],
                    result.get("action"), result.get("record_id"))
    stats = engine.get_kb_stats()
    logger.info("Seed complete: %d records, %d vectors", stats["total_records"], stats["vector_count"])


if __name__ == "__main__":
    seed()
