"""One-off: delete ticket SI-18 from the Historical KB (record + vector + BM25).

Targets the same data dir the running server uses (./si_data). Run with the venv:
    .venv/Scripts/python.exe delete_si18.py
"""
import os
from pathlib import Path

# Pin to this MCP's local si_data (what the live server logs as data_dir=si_data),
# regardless of any inherited SI_DATA_DIR from .env.
os.environ["SI_DATA_DIR"] = str(Path(__file__).resolve().parent / "si_data")

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from historical_kb_mcp.store import KBEngine

TICKET = "SI-18"

engine = KBEngine()
before = engine.get_kb_stats()
print(f"Before: total_records={before['total_records']} vector_count={before['vector_count']}")

result = engine.delete_analysis(TICKET)
print("delete_analysis ->", result)

after = engine.get_kb_stats()
print(f"After:  total_records={after['total_records']} vector_count={after['vector_count']}")

# Confirm it's really gone
check = engine.get_analysis(TICKET)
print("get_analysis after delete ->", check)
