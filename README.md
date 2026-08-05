# Historical Search Engineering KB MCP

Stores and retrieves **completed defect-triage analyses** so the orchestrator
can find similar past defects when triaging a new ticket. This is the third MCP
in the Rapid7 SI Triage pipeline — the persistent memory of the system.

---

## What it does

1. **Store** — after the triage agent completes its analysis, it calls
   `store_analysis` with the full triage result: root cause, verdict, fix,
   affected class/method, error signature, PR link, confidence, and 30+ other
   metadata fields.  If the same ticket is stored again, fields are merged
   (upsert).
2. **Search** — at the start of a new triage, `search_similar` runs **hybrid
   retrieval** (dense + BM25 via Reciprocal Rank Fusion) to find historical
   defects with similar error signatures, root causes, or components.
3. **Retrieve** — `get_analysis` returns the full record for a specific ticket.
4. **Update** — `update_analysis` patches fields (e.g. adding the PR link after
   the fix is merged, or upgrading the verdict after investigation).
5. **List** — `list_analyses` with optional filters for browsing/dashboarding.
6. **Delete** — `delete_analysis` removes a record.
7. **Stats** — `get_kb_stats` returns counts by verdict, defect type, component,
   product, and average resolution time.

## Tools

| Tool | Purpose |
|------|---------|
| `store_analysis(data)` | Store or merge a triage result (ticket_id required) |
| `get_analysis(ticket_id)` | Retrieve full record by Jira key |
| `search_similar(query, top_k, component?, verdict?, product?, error_type?)` | Hybrid search with optional filters |
| `update_analysis(ticket_id, updates)` | Patch specific fields |
| `list_analyses(component?, verdict?, product?, limit?)` | Filtered listing |
| `delete_analysis(ticket_id)` | Remove from KB |
| `get_kb_stats()` | Aggregate statistics |

---

## Metadata schema (AnalysisRecord)

Every analysis stores **30+ fields** across these categories:

- **Identity** — ticket_id, record_id
- **Ticket context** — summary, description, product, component, version, environment, reporter, priority, labels
- **Triage analysis** — root_cause, verdict, defect_type, severity_assessed, confidence
- **Code location** — affected_class, affected_method, affected_file, affected_line
- **Error signature** — error_type, error_message, error_code, stack_trace_signature
- **Fix / resolution** — fix_description, fix_type, pr_link, pr_status, commit_hash, branch, files_changed
- **Linked artefacts** — confluence_page_ids, related_tickets, log_query_used, log_chunks_referenced
- **Timestamps** — created_at, resolved_at, resolution_time_hours, updated_at
- **Agent metadata** — analyst, model_used, pipeline_version
- **Extension** — tags, custom_fields

### Verdict taxonomy

`code_fix` · `config_change` · `infra` · `dependency` · `data_issue` ·
`user_error` · `duplicate` · `wontfix` · `needs_info` · `not_a_bug`

### Defect type taxonomy

`null_pointer` · `class_cast` · `arithmetic` · `concurrent_modification` ·
`number_format` · `parse_error` · `resource_leak` · `timeout` ·
`connection_failure` · `auth_failure` · `permission_denied` · `missing_table` ·
`schema_mismatch` · `config_invalid` · `thread_pool` · `memory` · `other`

---

## Install & run

```bash
cd historical-kb-mcp
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e .
cp .env.example .env    # adjust SI_DATA_DIR if needed

# stdio (for Claude Desktop / local MCP client):
python -m historical_kb_mcp --transport stdio

# HTTP (for MCP Inspector / remote clients):
python -m historical_kb_mcp --transport http
# Serves at http://127.0.0.1:8082/mcp
```

> This server is one of four processes in the SI Triage POC (this + the
> Jira/Confluence and Log Intelligence MCPs + the orchestrator). For the full
> multi-service manual startup sequence, `.env` layout across all four repos,
> and end-to-end test steps, see **`orchestrator-agent/si-triage-automation/README.md`
> → "Running the full system manually"**.

### Seed the KB with the 10 Nexpose defects

```bash
python -m historical_kb_mcp.seed
```

This pre-populates the KB with completed triage analyses for all 10 planted
defects (root causes, verdicts, fixes, PR links, error signatures), so
`search_similar` returns meaningful results immediately.

### MCP Inspector

```
npx @modelcontextprotocol/inspector
# URL: http://127.0.0.1:8082/mcp
```

### Register with an MCP client (stdio)

```json
{
  "mcpServers": {
    "historical-kb": {
      "command": "python",
      "args": ["-m", "historical_kb_mcp", "--transport", "stdio"],
      "env": { "SI_DATA_DIR": "/absolute/path/to/si_data" }
    }
  }
}
```

---

## How it fits in the pipeline

```
 Orchestrator (Claude)
   │
   ├──1─▶ jira-confluence-mcp       (get ticket, download logs, search Confluence)
   │      └─writes→ si_data/logs/<ticket_id>/
   │
   ├──2─▶ log-intelligence-mcp      (ingest logs, hybrid query)
   │      └─reads←  si_data/logs/<ticket_id>/
   │      └─writes→ si_data/vector_store/
   │
   ├──3─▶ historical-kb-mcp         ◀── THIS MCP
   │      ├─ search_similar(error_signature)   ← find past defects
   │      └─ store_analysis(triage_result)     ← save when done
   │         └─writes→ si_data/kb/records/ + si_data/kb/vectors/
   │
   └──4─▶ jira-confluence-mcp       (post comment, update ticket)
```

All three MCPs share `SI_DATA_DIR` — set it to the same absolute path.

---

## Hybrid search

Same approach as the Log Intelligence MCP:

- **Dense** — sentence-transformers `all-mpnet-base-v2` (768-dim) for semantic
  similarity ("payment failed" ≈ "authorization error")
- **BM25** — keyword matching for exact identifiers (class names, error codes,
  CVEs)
- **Reciprocal Rank Fusion** — merges the two rankings without fragile score
  normalisation

The text embedded is the concatenation of error signature fields, root cause,
fix, summary, description, and class/method — ordered so the most semantically
distinctive fields dominate.

---

## Backends (same as log MCP)

| Concern | Production | Offline fallback |
|---------|------------|------------------|
| Embeddings | sentence-transformers `all-mpnet-base-v2` | Hashed n-gram TF-IDF (numpy) |
| Vector store | Chroma (persistent) | Numpy `.npz` + JSON |
| Sparse search | BM25 (always) | same |

`EMBED_BACKEND=auto` / `VECTOR_BACKEND=auto` use production backends when
importable and fall back otherwise. The offline backends are real (genuine
vectors, real cosine search) — not mocks.

---

## Tests

```bash
pytest                        # in the POC environment
python tests/_runner.py       # offline (when pytest isn't installed)
```

12 tests: model serialisation, searchable text ordering, BM25 keyword ranking,
store/retrieve, update (field merge), search (hybrid + filters), delete,
list (with filters), stats aggregation, upsert merge (no duplicates), and the
full seed of all 10 defects.

## Configuration

See `.env.example`. Key variables: `SI_DATA_DIR`, `EMBED_BACKEND`,
`VECTOR_BACKEND`, `RRF_K`, `DEFAULT_TOP_K`, `MCP_HTTP_PORT` (default 8082).
