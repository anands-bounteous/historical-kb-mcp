"""Environment-driven configuration for the Historical KB MCP.

Shares ``SI_DATA_DIR`` with the Jira/Confluence and Log Intelligence MCPs so
all three coordinate through a single directory tree.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from .logging_setup import get_logger

logger = get_logger(__name__)


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("Env %s=%r not int; using %d", name, raw, default)
        return default


def _float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("Env %s=%r not float; using %s", name, raw, default)
        return default


@dataclass
class Config:
    # Shared data directory — same SI_DATA_DIR the other MCPs use.
    data_dir: Path = field(
        default_factory=lambda: Path(os.getenv("SI_DATA_DIR", "./si_data")).expanduser()
    )

    # ---- Embeddings (mirrors log-intelligence-mcp so vectors are compatible) ----
    embed_backend: str = field(
        default_factory=lambda: os.getenv("EMBED_BACKEND", "auto")
    )
    embed_model: str = field(
        default_factory=lambda: os.getenv(
            "EMBED_MODEL", "sentence-transformers/all-mpnet-base-v2"
        )
    )
    embed_dim_fallback: int = field(
        default_factory=lambda: _int("EMBED_DIM_FALLBACK", 512)
    )

    # ---- Vector store ----
    vector_backend: str = field(
        default_factory=lambda: os.getenv("VECTOR_BACKEND", "auto")
    )

    # ---- Retrieval ----
    rrf_k: int = field(default_factory=lambda: _int("RRF_K", 60))
    dense_weight: float = field(default_factory=lambda: _float("DENSE_WEIGHT", 1.0))
    sparse_weight: float = field(default_factory=lambda: _float("SPARSE_WEIGHT", 1.0))
    default_top_k: int = field(default_factory=lambda: _int("DEFAULT_TOP_K", 10))
    candidate_pool: int = field(default_factory=lambda: _int("CANDIDATE_POOL", 40))

    # ---- Chunking (for long analyses — simpler than log chunking) ----
    chars_per_token: float = field(
        default_factory=lambda: _float("CHARS_PER_TOKEN", 3.5)
    )

    # ---- HTTP transport ----
    http_host: str = field(
        default_factory=lambda: os.getenv("MCP_HTTP_HOST", "127.0.0.1")
    )
    http_port: int = field(default_factory=lambda: _int("MCP_HTTP_PORT", 8082))

    # ---- Derived paths ----
    @property
    def kb_dir(self) -> Path:
        return self.data_dir / "kb"

    @property
    def kb_vector_dir(self) -> Path:
        return self.kb_dir / "vectors"

    @property
    def kb_records_dir(self) -> Path:
        return self.kb_dir / "records"

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.kb_dir, self.kb_vector_dir, self.kb_records_dir):
            d.mkdir(parents=True, exist_ok=True)
        logger.debug("Ensured KB directories under %s", self.kb_dir)

    def log_summary(self) -> None:
        logger.info(
            "Config: data_dir=%s kb_dir=%s embed=%s vector=%s rrf_k=%d top_k=%d",
            self.data_dir, self.kb_dir, self.embed_backend, self.vector_backend,
            self.rrf_k, self.default_top_k,
        )


_config: Config | None = None


def get_config() -> Config:
    global _config
    if _config is None:
        _config = Config()
        _config.log_summary()
    return _config
