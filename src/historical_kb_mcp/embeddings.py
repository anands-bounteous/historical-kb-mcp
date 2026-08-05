"""Embedding backends — identical adapter pattern to log-intelligence-mcp so
vectors are produced with the same model and are directly comparable.

``auto`` tries sentence-transformers first, falling back to the deterministic
hashing-TF-IDF embedder that needs only numpy.
"""
from __future__ import annotations

import hashlib
import math
from abc import ABC, abstractmethod
from typing import Optional

import numpy as np

from .config import get_config
from .logging_setup import get_logger

logger = get_logger(__name__)


class Embedder(ABC):
    @property
    @abstractmethod
    def dim(self) -> int: ...

    @abstractmethod
    def embed(self, texts: list[str]) -> np.ndarray: ...

    @property
    @abstractmethod
    def name(self) -> str: ...


# --------------------------------------------------------------------------- #
# Sentence-transformers backend
# --------------------------------------------------------------------------- #
class SentenceTransformerEmbedder(Embedder):
    def __init__(self, model_name: str):
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(model_name)
        self._dim = self._model.get_sentence_embedding_dimension()
        logger.info("Embedding backend: sentence-transformers '%s' (dim=%d)", model_name, self._dim)

    @property
    def dim(self) -> int:
        return self._dim

    @property
    def name(self) -> str:
        return "sentence-transformers"

    def embed(self, texts: list[str]) -> np.ndarray:
        vecs = self._model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return np.array(vecs, dtype=np.float32)


# --------------------------------------------------------------------------- #
# Hashing-TF-IDF fallback (no downloads, deterministic, real vectors)
# --------------------------------------------------------------------------- #
class HashingEmbedder(Embedder):
    """Deterministic hashed-ngram TF-IDF embedder using only numpy.

    Produces real, normalised vectors that support cosine similarity — a genuine
    fallback, not a mock.
    """

    def __init__(self, dim: int = 512, ngram_range: tuple[int, int] = (2, 4)):
        self._dim = dim
        self._ng_lo, self._ng_hi = ngram_range
        logger.info("Embedding backend: hashing-tfidf (dim=%d, offline)", dim)

    @property
    def dim(self) -> int:
        return self._dim

    @property
    def name(self) -> str:
        return "hashing-tfidf"

    def _char_ngrams(self, text: str) -> list[str]:
        t = text.lower().strip()
        grams: list[str] = []
        for n in range(self._ng_lo, self._ng_hi + 1):
            for i in range(len(t) - n + 1):
                grams.append(t[i : i + n])
        return grams

    def _hash_index(self, gram: str) -> int:
        h = int(hashlib.md5(gram.encode("utf-8")).hexdigest(), 16)
        return h % self._dim

    def _hash_sign(self, gram: str) -> float:
        h = int(hashlib.sha1(gram.encode("utf-8")).hexdigest(), 16)
        return 1.0 if h % 2 == 0 else -1.0

    def embed(self, texts: list[str]) -> np.ndarray:
        vecs = np.zeros((len(texts), self._dim), dtype=np.float32)
        for i, text in enumerate(texts):
            grams = self._char_ngrams(text)
            for g in grams:
                idx = self._hash_index(g)
                sign = self._hash_sign(g)
                tf = 1.0 + math.log1p(1)
                vecs[i, idx] += sign * tf
            norm = np.linalg.norm(vecs[i])
            if norm > 0:
                vecs[i] /= norm
        return vecs


# --------------------------------------------------------------------------- #
# Factory
# --------------------------------------------------------------------------- #
def create_embedder(
    backend: Optional[str] = None,
    model: Optional[str] = None,
    dim_fallback: Optional[int] = None,
) -> Embedder:
    cfg = get_config()
    backend = backend or cfg.embed_backend
    model = model or cfg.embed_model
    dim_fb = dim_fallback or cfg.embed_dim_fallback

    if backend == "auto":
        try:
            return SentenceTransformerEmbedder(model)
        except Exception:
            logger.info("sentence-transformers not available; using hashing fallback")
            return HashingEmbedder(dim=dim_fb)
    elif backend == "sentence-transformers":
        return SentenceTransformerEmbedder(model)
    elif backend == "hashing":
        return HashingEmbedder(dim=dim_fb)
    else:
        raise ValueError(f"Unknown embed backend: {backend!r}")
