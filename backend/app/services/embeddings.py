"""Embedding functions for the example index."""
from __future__ import annotations

import hashlib
import math
import re

_STOP = {"the", "a", "an", "of", "in", "on", "for", "to", "and", "or", "is", "are", "was", "were", "by", "with",
         "me", "show", "list", "what", "which", "how", "many", "much", "do", "we", "have", "our", "all", "each", "per"}


def _stem(w: str) -> str:
    for suf, rep in (("ies", "y"), ("ses", "s"), ("es", ""), ("s", "")):
        if w.endswith(suf) and len(w) > len(suf) + 2:
            return w[: -len(suf)] + rep
    return w


class HashingEmbeddingFunction:
    """Dependency-free, deterministic bag-of-words(+bigrams) embedding. No model download; works offline.

    Used for tests and as an offline fallback (EMBEDDING_BACKEND=hashing). Quality is lexical, not semantic.
    """

    def __init__(self, dim: int = 512):
        self.dim = dim

    def name(self) -> str:
        return f"hashing-{self.dim}"

    def _embed(self, text: str) -> list[float]:
        toks = [_stem(t) for t in re.findall(r"[a-z0-9_]+", text.lower()) if t not in _STOP]
        feats = toks + [f"{a}_{b}" for a, b in zip(toks, toks[1:])]
        vec = [0.0] * self.dim
        for f in feats:
            h = int.from_bytes(hashlib.md5(f.encode()).digest()[:8], "big")
            vec[h % self.dim] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def __call__(self, input: list[str]) -> list[list[float]]:  # noqa: A002 - chroma's signature
        return [self._embed(t) for t in input]


def create_embedding_function(backend: str):
    """'default' = Chroma's bundled MiniLM (ONNX, downloads once); 'hashing' = offline fallback."""
    if backend == "hashing":
        return HashingEmbeddingFunction()
    from chromadb.utils.embedding_functions import DefaultEmbeddingFunction
    return DefaultEmbeddingFunction()
