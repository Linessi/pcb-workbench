"""Small Chinese BGE embedding model; loaded only when retrieval is first used."""

from typing import Protocol

import numpy as np


MODEL_NAME = "BAAI/bge-small-zh-v1.5"
QUERY_INSTRUCTION = "为这个句子生成表示以用于检索相关文章："


class EmbeddingBackend(Protocol):
    def encode_documents(self, texts: list[str]) -> np.ndarray: ...

    def encode_queries(self, texts: list[str]) -> np.ndarray: ...


class BGEEmbedder:
    def __init__(self, model_name: str = MODEL_NAME) -> None:
        # BAAI model card documents SentenceTransformer and normalized vectors.
        from sentence_transformers import SentenceTransformer

        try:
            self.model = SentenceTransformer(model_name, device="cpu", local_files_only=True)
        except (OSError, ValueError):
            # First run: fetch the public model; later runs work from the cache.
            self.model = SentenceTransformer(model_name, device="cpu")

    def _encode(self, texts: list[str]) -> np.ndarray:
        vectors = self.model.encode(
            texts,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        matrix = np.ascontiguousarray(vectors, dtype=np.float32)
        if matrix.ndim != 2 or matrix.shape[0] != len(texts) or not np.isfinite(matrix).all():
            raise ValueError("BGE returned invalid embedding vectors")
        return matrix

    def encode_documents(self, texts: list[str]) -> np.ndarray:
        return self._encode(texts)

    def encode_queries(self, texts: list[str]) -> np.ndarray:
        return self._encode([QUERY_INSTRUCTION + text for text in texts])
