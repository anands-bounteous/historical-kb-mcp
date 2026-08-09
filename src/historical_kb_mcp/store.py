"""Historical KB storage engine.

Combines:
  - **Vector store** (Chroma or numpy fallback) for dense semantic search
  - **BM25** for keyword / identifier matching
  - **Reciprocal Rank Fusion** to merge dense + sparse rankings
  - **JSON record files** for durable, full-fidelity storage of AnalysisRecord

Each analysis is embedded as a single vector from its ``searchable_text()`` and
stored with ``filter_metadata()`` for faceted retrieval.  The full record (all
fields) lives as a JSON file in ``<kb_dir>/records/<record_id>.json``.
"""
from __future__ import annotations

import json
import math
import os
import re
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np

from .config import Config, get_config
from .embeddings import Embedder, create_embedder
from .logging_setup import get_logger
from .models import AnalysisRecord

logger = get_logger(__name__)


# =========================================================================== #
# BM25 (lightweight, pure-Python, same as log MCP)
# =========================================================================== #
_SPLIT_RE = re.compile(r"[.\-_/\\:$]")
_CAMEL_RE = re.compile(r"(?<=[a-z])(?=[A-Z])")
_WORD_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for raw in text.lower().split():
        tokens.append(raw)
        for sub in _SPLIT_RE.split(raw):
            if sub and sub != raw:
                tokens.append(sub)
        for sub in _CAMEL_RE.sub(" ", raw).split():
            if sub and sub != raw:
                tokens.append(sub)
    return tokens


def _iso_date(ts: float) -> str:
    """Unix timestamp -> 'YYYY-MM-DD', or '' if unset (0.0 default)."""
    if not ts:
        return ""
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


class BM25Index:
    """In-memory BM25 index over (doc_id, text) pairs."""

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self._docs: dict[str, list[str]] = {}   # doc_id -> tokens
        self._df: Counter = Counter()
        self._avg_dl: float = 0.0

    def add(self, doc_id: str, text: str) -> None:
        tokens = _tokenize(text)
        if doc_id in self._docs:
            self.remove(doc_id)
        self._docs[doc_id] = tokens
        for t in set(tokens):
            self._df[t] += 1
        self._recompute_avg()

    def remove(self, doc_id: str) -> None:
        tokens = self._docs.pop(doc_id, None)
        if tokens is None:
            return
        for t in set(tokens):
            self._df[t] -= 1
            if self._df[t] <= 0:
                del self._df[t]
        self._recompute_avg()

    def _recompute_avg(self) -> None:
        if self._docs:
            self._avg_dl = sum(len(t) for t in self._docs.values()) / len(self._docs)
        else:
            self._avg_dl = 0.0

    def search(self, query: str, top_k: int = 20) -> list[tuple[str, float]]:
        qtokens = _tokenize(query)
        n = len(self._docs)
        if n == 0:
            return []
        scores: dict[str, float] = defaultdict(float)
        for qt in qtokens:
            df = self._df.get(qt, 0)
            if df == 0:
                continue
            idf = math.log((n - df + 0.5) / (df + 0.5) + 1.0)
            for doc_id, tokens in self._docs.items():
                tf = tokens.count(qt)
                if tf == 0:
                    continue
                dl = len(tokens)
                num = tf * (self.k1 + 1)
                den = tf + self.k1 * (1 - self.b + self.b * dl / max(self._avg_dl, 1))
                scores[doc_id] += idf * num / den
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return ranked[:top_k]

    def __len__(self) -> int:
        return len(self._docs)


# =========================================================================== #
# Vector store adapter (Chroma or numpy)
# =========================================================================== #
class VectorStore:
    """Chroma-first, numpy-fallback vector store for the KB collection."""

    def __init__(self, store_dir: Path, embedder: Embedder, backend: str = "auto"):
        self._dir = store_dir
        self._embedder = embedder
        self._backend = backend
        self._impl: Any = None
        self._init_backend()

    def _init_backend(self) -> None:
        if self._backend in ("auto", "chroma"):
            try:
                import chromadb
                client = chromadb.PersistentClient(path=str(self._dir))
                self._client = client
                self._impl = client.get_or_create_collection(
                    name="historical_kb",
                    metadata={"hnsw:space": "cosine"},
                )
                self._backend = "chroma"
                logger.info("Vector store backend: chroma (persistent) at %s", self._dir)
                return
            except Exception:
                if self._backend == "chroma":
                    raise
                logger.info("chromadb not available; falling back to numpy store")

        self._backend = "numpy"
        self._np_ids: list[str] = []
        self._np_vecs: np.ndarray | None = None
        self._np_meta: list[dict] = []
        self._np_file = self._dir / "kb_vectors.npz"
        self._load_numpy()
        logger.info("Vector store backend: numpy (persistent) at %s", self._dir)

    # ---- numpy persistence ------------------------------------------------
    def _load_numpy(self) -> None:
        meta_file = self._dir / "kb_meta.json"
        if self._np_file.exists() and meta_file.exists():
            data = np.load(self._np_file, allow_pickle=False)
            self._np_vecs = data["vecs"]
            self._np_ids = json.loads(meta_file.read_text())["ids"]
            self._np_meta = json.loads(meta_file.read_text()).get("meta", [])
            logger.debug("Loaded %d numpy vectors", len(self._np_ids))
        else:
            self._np_vecs = np.empty((0, self._embedder.dim), dtype=np.float32)
            self._np_ids = []
            self._np_meta = []

    def _save_numpy(self) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        np.savez(self._np_file, vecs=self._np_vecs)
        meta_file = self._dir / "kb_meta.json"
        meta_file.write_text(json.dumps({"ids": self._np_ids, "meta": self._np_meta}))

    # ---- public API -------------------------------------------------------
    def upsert(self, ids: list[str], texts: list[str], metadatas: list[dict]) -> None:
        vecs = self._embedder.embed(texts)
        if self._backend == "chroma":
            self._impl.upsert(
                ids=ids,
                documents=texts,
                embeddings=[v.tolist() for v in vecs],
                metadatas=metadatas,
            )
        else:
            for i, rid in enumerate(ids):
                if rid in self._np_ids:
                    idx = self._np_ids.index(rid)
                    self._np_vecs[idx] = vecs[i]
                    self._np_meta[idx] = metadatas[i]
                else:
                    self._np_ids.append(rid)
                    self._np_meta.append(metadatas[i])
                    self._np_vecs = np.vstack([self._np_vecs, vecs[i:i+1]])
            self._save_numpy()
        logger.debug("Upserted %d vectors", len(ids))

    def query(self, text: str, top_k: int = 10,
              where: Optional[dict] = None) -> list[dict]:
        qvec = self._embedder.embed([text])[0]
        if self._backend == "chroma":
            kwargs: dict = {"query_embeddings": [qvec.tolist()], "n_results": top_k}
            if where:
                kwargs["where"] = where
            results = self._impl.query(**kwargs)
            hits = []
            for i in range(len(results["ids"][0])):
                hits.append({
                    "id": results["ids"][0][i],
                    "score": 1.0 - (results["distances"][0][i] if results.get("distances") else 0.0),
                    "metadata": results["metadatas"][0][i] if results.get("metadatas") else {},
                })
            return hits
        else:
            if len(self._np_ids) == 0:
                return []
            sims = self._np_vecs @ qvec
            # apply metadata filter
            mask = np.ones(len(self._np_ids), dtype=bool)
            if where:
                for k, v in where.items():
                    for j, m in enumerate(self._np_meta):
                        if m.get(k) != v:
                            mask[j] = False
            sims[~mask] = -999.0
            top_idx = np.argsort(sims)[::-1][:top_k]
            return [
                {"id": self._np_ids[j], "score": float(sims[j]),
                 "metadata": self._np_meta[j]}
                for j in top_idx if sims[j] > -999.0
            ]

    def delete(self, ids: list[str]) -> int:
        if self._backend == "chroma":
            self._impl.delete(ids=ids)
            return len(ids)
        else:
            removed = 0
            for rid in ids:
                if rid in self._np_ids:
                    idx = self._np_ids.index(rid)
                    self._np_ids.pop(idx)
                    self._np_meta.pop(idx)
                    self._np_vecs = np.delete(self._np_vecs, idx, axis=0)
                    removed += 1
            if removed:
                self._save_numpy()
            return removed

    def count(self) -> int:
        if self._backend == "chroma":
            return self._impl.count()
        return len(self._np_ids)

    def reset(self) -> None:
        """Drop all vectors and recreate an empty collection.

        Used to recover from an embedding-dimension change: a Chroma collection
        fixes its dimension at first insert, so a collection seeded with the
        512-d hashing fallback cannot accept 768-d sentence-transformer vectors.
        Callers re-embed from the durable JSON records after resetting.
        """
        if self._backend == "chroma":
            try:
                self._client.delete_collection("historical_kb")
            except Exception:
                pass  # not present yet — recreate below
            self._impl = self._client.get_or_create_collection(
                name="historical_kb",
                metadata={"hnsw:space": "cosine"},
            )
        else:
            self._np_ids = []
            self._np_meta = []
            self._np_vecs = np.empty((0, self._embedder.dim), dtype=np.float32)
            self._save_numpy()


# =========================================================================== #
# KB Engine (orchestrates records + vectors + BM25)
# =========================================================================== #
class KBEngine:
    """High-level KB: stores, searches, and manages AnalysisRecords."""

    def __init__(self, config: Optional[Config] = None):
        self.config = config or get_config()
        self.config.ensure_dirs()
        self._embedder = create_embedder()
        self._vectors = VectorStore(
            self.config.kb_vector_dir, self._embedder, self.config.vector_backend
        )
        self._bm25 = BM25Index()
        self._records_dir = self.config.kb_records_dir
        self._rebuild_bm25()
        self._reconcile_vector_dim()
        logger.info(
            "KBEngine ready: %d records, embedder=%s, vector=%s",
            self._vectors.count(), self._embedder.name, self._vectors._backend,
        )

    def _reconcile_vector_dim(self) -> None:
        """Self-heal a stale vector collection whose embedding dimension no
        longer matches the active embedder.

        This happens when the collection was seeded while sentence-transformers
        was unavailable (512-d hashing fallback) and the real model is now
        loadable (768-d), or vice versa. Left unhandled, the first search_similar
        raises "Collection expecting embedding with dimension of N, got M".
        We detect the mismatch and rebuild the vectors from the durable JSON
        records at the current dimension.
        """
        vs = self._vectors
        if vs.count() == 0:
            return  # empty collection has no fixed dimension yet
        mismatch = False
        if vs._backend == "numpy":
            if vs._np_vecs is not None and vs._np_vecs.shape[1] != self._embedder.dim:
                mismatch = True
        else:  # chroma — probe with a real query and inspect the error
            try:
                vs.query("__dimension_probe__", top_k=1)
            except Exception as e:  # noqa: BLE001 — narrow on message below
                if "dimension" in str(e).lower():
                    mismatch = True
                else:
                    raise
        if mismatch:
            logger.warning(
                "KB vector dimension mismatch (embedder dim=%d); rebuilding "
                "collection from %d JSON record(s)",
                self._embedder.dim, len(list(self._records_dir.glob("*.json"))),
            )
            self._rebuild_vectors_from_records()

    def _rebuild_vectors_from_records(self) -> None:
        """Drop and re-embed every persisted JSON record into a fresh collection."""
        self._vectors.reset()
        n = 0
        for f in self._records_dir.glob("*.json"):
            try:
                rec = AnalysisRecord.from_json(f.read_text())
            except Exception as e:
                logger.warning("Skipping corrupt record %s during rebuild: %s", f.name, e)
                continue
            self._vectors.upsert(
                ids=[rec.record_id],
                texts=[rec.searchable_text()],
                metadatas=[rec.filter_metadata()],
            )
            n += 1
        logger.info("KB vector rebuild complete: %d record(s) at dim=%d",
                    n, self._embedder.dim)

    def _rebuild_bm25(self) -> None:
        """Rebuild BM25 from persisted JSON records at startup."""
        for f in self._records_dir.glob("*.json"):
            try:
                rec = AnalysisRecord.from_json(f.read_text())
                self._bm25.add(rec.record_id, rec.searchable_text())
            except Exception as e:
                logger.warning("Skipping corrupt record %s: %s", f.name, e)

    def _persist_record(self, rec: AnalysisRecord) -> Path:
        path = self._records_dir / f"{rec.record_id}.json"
        path.write_text(rec.to_json())
        return path

    def _load_record(self, record_id: str) -> Optional[AnalysisRecord]:
        path = self._records_dir / f"{record_id}.json"
        if not path.exists():
            return None
        return AnalysisRecord.from_json(path.read_text())

    def _find_record_by_ticket(self, ticket_id: str) -> Optional[AnalysisRecord]:
        for f in self._records_dir.glob("*.json"):
            try:
                rec = AnalysisRecord.from_json(f.read_text())
                if rec.ticket_id == ticket_id:
                    return rec
            except Exception:
                continue
        return None

    # ---------------------------------------------------------------------- #
    # Public API
    # ---------------------------------------------------------------------- #
    def store_analysis(self, data: dict) -> dict:
        """Store a new or update an existing analysis record.

        If ``ticket_id`` already has a record in the KB, it is updated
        (merged); otherwise a new record is created.
        """
        ticket_id = data.get("ticket_id", "")
        if not ticket_id:
            return {"error": "ticket_id is required"}

        existing = self._find_record_by_ticket(ticket_id)
        if existing:
            # Merge: existing fields kept unless overwritten by non-empty values
            merged = existing.to_dict()
            for k, v in data.items():
                if v is not None and v != "" and v != [] and v != {} and v != 0 and v != 0.0:
                    merged[k] = v
            merged["updated_at"] = time.time()
            rec = AnalysisRecord.from_dict(merged)
            rec.record_id = existing.record_id
            action = "updated"
        else:
            rec = AnalysisRecord.from_dict(data)
            action = "created"

        rec.updated_at = time.time()
        self._persist_record(rec)

        text = rec.searchable_text()
        self._vectors.upsert(
            ids=[rec.record_id],
            texts=[text],
            metadatas=[rec.filter_metadata()],
        )
        self._bm25.add(rec.record_id, text)

        logger.info("store_analysis: %s record %s for ticket %s",
                     action, rec.record_id, rec.ticket_id)
        return {
            "action": action,
            "record_id": rec.record_id,
            "ticket_id": rec.ticket_id,
            "searchable_text_length": len(text),
        }

    def get_analysis(self, ticket_id: str) -> dict:
        """Retrieve a full analysis record by ticket ID."""
        rec = self._find_record_by_ticket(ticket_id)
        if not rec:
            return {"error": f"No analysis found for ticket {ticket_id}"}
        return rec.to_dict()

    def search_similar(
        self,
        query: str,
        top_k: int = 10,
        filters: Optional[dict] = None,
    ) -> dict:
        """Hybrid semantic + keyword search across the KB.

        Returns ranked analysis summaries with scores.
        """
        cfg = self.config
        pool = max(top_k, cfg.candidate_pool)

        # Dense retrieval
        dense_hits = self._vectors.query(query, top_k=pool, where=filters)
        dense_ranking = {h["id"]: rank for rank, h in enumerate(dense_hits)}

        # Sparse (BM25) retrieval
        sparse_hits = self._bm25.search(query, top_k=pool)
        sparse_ranking = {doc_id: rank for rank, (doc_id, _) in enumerate(sparse_hits)}

        # RRF fusion
        all_ids = set(dense_ranking.keys()) | set(sparse_ranking.keys())
        scored: list[tuple[str, float]] = []
        for rid in all_ids:
            score = 0.0
            if rid in dense_ranking:
                score += cfg.dense_weight / (cfg.rrf_k + dense_ranking[rid])
            if rid in sparse_ranking:
                score += cfg.sparse_weight / (cfg.rrf_k + sparse_ranking[rid])
            scored.append((rid, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        scored = scored[:top_k]

        # RRF fusion scores are only meaningful in rank order; their raw magnitude
        # (max possible = (dense_weight + sparse_weight) / rrf_k, ~0.033 at
        # defaults) is far below similarity thresholds like MIN_SIMILARITY_FOR_PRECEDENT
        # that expect a [0,1]-scaled value. Normalize by the theoretical max (best
        # rank on both dense and sparse, i.e. rank 0 on each) so callers get a
        # genuine [0,1] similarity score rather than an unusably tiny one.
        max_possible_score = (cfg.dense_weight + cfg.sparse_weight) / cfg.rrf_k

        # Build result summaries
        results = []
        for rid, score in scored:
            rec = self._load_record(rid)
            if rec is None:
                continue
            normalized_score = min(1.0, score / max_possible_score) if max_possible_score else 0.0
            results.append({
                "record_id": rec.record_id,
                "ticket_id": rec.ticket_id,
                "summary": rec.summary,
                "verdict": rec.verdict,
                "defect_type": rec.defect_type,
                "component": rec.component,
                "product": rec.product,
                "error_type": rec.error_type,
                "error_code": rec.error_code,
                "affected_class": rec.affected_class,
                "confidence": rec.confidence,
                "pr_link": rec.pr_link,
                "pr_status": rec.pr_status,
                "fix_description": rec.fix_description,
                "resolution_date": _iso_date(rec.resolved_at),
                "score": round(normalized_score, 6),
            })

        logger.info(
            "search_similar: query=%r top_k=%d filters=%s -> %d results "
            "(dense=%d, sparse=%d)",
            query[:60], top_k, filters, len(results),
            len(dense_hits), len(sparse_hits),
        )
        return {"query": query, "count": len(results), "results": results}

    def update_analysis(self, ticket_id: str, updates: dict) -> dict:
        """Patch specific fields on an existing analysis record."""
        rec = self._find_record_by_ticket(ticket_id)
        if not rec:
            return {"error": f"No analysis found for ticket {ticket_id}"}

        d = rec.to_dict()
        for k, v in updates.items():
            if k in d and k not in ("record_id", "ticket_id", "created_at"):
                d[k] = v
        d["updated_at"] = time.time()
        updated = AnalysisRecord.from_dict(d)
        updated.record_id = rec.record_id
        self._persist_record(updated)

        text = updated.searchable_text()
        self._vectors.upsert(
            ids=[updated.record_id],
            texts=[text],
            metadatas=[updated.filter_metadata()],
        )
        self._bm25.add(updated.record_id, text)

        logger.info("update_analysis: ticket %s record %s — %d field(s)",
                     ticket_id, updated.record_id, len(updates))
        return {
            "record_id": updated.record_id,
            "ticket_id": updated.ticket_id,
            "fields_updated": list(updates.keys()),
        }

    def delete_analysis(self, ticket_id: str) -> dict:
        """Remove an analysis record from the KB (vectors + JSON + BM25)."""
        rec = self._find_record_by_ticket(ticket_id)
        if not rec:
            return {"error": f"No analysis found for ticket {ticket_id}"}

        self._vectors.delete([rec.record_id])
        self._bm25.remove(rec.record_id)
        path = self._records_dir / f"{rec.record_id}.json"
        if path.exists():
            path.unlink()

        logger.info("delete_analysis: removed ticket %s record %s", ticket_id, rec.record_id)
        return {"deleted_record_id": rec.record_id, "ticket_id": ticket_id}

    def list_analyses(
        self,
        component: str = "",
        verdict: str = "",
        product: str = "",
        limit: int = 50,
    ) -> dict:
        """List stored analyses, optionally filtered by component/verdict/product."""
        records = []
        for f in sorted(self._records_dir.glob("*.json"), reverse=True):
            try:
                rec = AnalysisRecord.from_json(f.read_text())
            except Exception:
                continue
            if component and rec.component.lower() != component.lower():
                continue
            if verdict and rec.verdict.lower() != verdict.lower():
                continue
            if product and rec.product.lower() != product.lower():
                continue
            records.append({
                "record_id": rec.record_id,
                "ticket_id": rec.ticket_id,
                "summary": rec.summary,
                "verdict": rec.verdict,
                "defect_type": rec.defect_type,
                "component": rec.component,
                "product": rec.product,
                "priority": rec.priority,
                "pr_link": rec.pr_link,
                "created_at": rec.created_at,
            })
            if len(records) >= limit:
                break
        return {"count": len(records), "records": records}

    def get_kb_stats(self) -> dict:
        """Aggregate statistics across the whole KB."""
        verdicts: Counter = Counter()
        defect_types: Counter = Counter()
        components: Counter = Counter()
        products: Counter = Counter()
        total = 0
        resolution_times: list[float] = []

        for f in self._records_dir.glob("*.json"):
            try:
                rec = AnalysisRecord.from_json(f.read_text())
            except Exception:
                continue
            total += 1
            if rec.verdict:
                verdicts[rec.verdict] += 1
            if rec.defect_type:
                defect_types[rec.defect_type] += 1
            if rec.component:
                components[rec.component] += 1
            if rec.product:
                products[rec.product] += 1
            if rec.resolution_time_hours > 0:
                resolution_times.append(rec.resolution_time_hours)

        avg_res = sum(resolution_times) / len(resolution_times) if resolution_times else 0.0
        return {
            "total_records": total,
            "vector_count": self._vectors.count(),
            "bm25_docs": len(self._bm25),
            "by_verdict": dict(verdicts.most_common()),
            "by_defect_type": dict(defect_types.most_common()),
            "by_component": dict(components.most_common()),
            "by_product": dict(products.most_common()),
            "avg_resolution_hours": round(avg_res, 2),
        }
