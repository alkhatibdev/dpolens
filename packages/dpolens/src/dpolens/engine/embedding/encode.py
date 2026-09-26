"""Running an embedding model on the CPU.

ONNX Runtime with tokenizers, and mean pooling written out here, because the
alternative is PyTorch: 1.0 GB installed against 213 MB, in a tool whose promise
is that one command starts it with nothing to configure.
"""

from __future__ import annotations

from pathlib import Path
from types import TracebackType

import numpy as np
import onnxruntime as ort
from huggingface_hub import hf_hub_download
from tokenizers import Tokenizer

from dpolens.engine.embedding.models import EmbeddingModel

MAX_SEQUENCE = 512


class Embedder:
    """One loaded model, ready to turn text into vectors."""

    def __init__(self, model: EmbeddingModel, cache_dir: Path | None = None) -> None:
        self.model = model
        cache = str(cache_dir) if cache_dir else None

        tokenizer_path = hf_hub_download(model.repo, "tokenizer.json", cache_dir=cache)
        self.tokenizer = Tokenizer.from_file(tokenizer_path)
        self.tokenizer.enable_truncation(max_length=MAX_SEQUENCE)
        self.tokenizer.enable_padding()

        weights = hf_hub_download(model.repo, model.onnx_file, cache_dir=cache)
        options = ort.SessionOptions()
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.session = ort.InferenceSession(weights, options, providers=["CPUExecutionProvider"])
        self._inputs = {value.name for value in self.session.get_inputs()}

    def close(self) -> None:
        """Release the runtime session.

        ONNX Runtime owns a thread pool, and letting the interpreter tear it
        down at exit has been seen to print an alarming libc++ message on
        macOS. Closing it while Python is still running avoids the race.
        """
        session = getattr(self, "session", None)
        if session is not None:
            del self.session

    def __enter__(self) -> Embedder:
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def count_tokens(self, text: str) -> int:
        """Token count without truncation, for the recipe's cap."""
        return len(self.tokenizer.encode(text, add_special_tokens=True).ids)

    def encode_passages(self, texts: list[str]) -> np.ndarray:
        return self._encode([f"{self.model.passage_prefix}{text}" for text in texts])

    def encode_query(self, text: str) -> np.ndarray:
        vector: np.ndarray = self._encode([f"{self.model.query_prefix}{text}"])[0]
        return vector

    def _encode(self, texts: list[str]) -> np.ndarray:
        encoded = self.tokenizer.encode_batch(texts)
        ids = np.array([item.ids for item in encoded], dtype=np.int64)
        mask = np.array([item.attention_mask for item in encoded], dtype=np.int64)

        feed: dict[str, np.ndarray] = {"input_ids": ids, "attention_mask": mask}
        if "token_type_ids" in self._inputs:
            feed["token_type_ids"] = np.zeros_like(ids)

        hidden: np.ndarray = self.session.run(None, feed)[0]
        return _normalise(_mean_pool(hidden, mask))


def _mean_pool(hidden: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Average the token vectors, ignoring padding."""
    weights = mask[..., None].astype(np.float32)
    pooled: np.ndarray = (hidden * weights).sum(axis=1) / np.clip(weights.sum(axis=1), 1e-9, None)
    return pooled


def _normalise(vectors: np.ndarray) -> np.ndarray:
    """Unit length, so cosine distance and dot product agree."""
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    unit: np.ndarray = vectors / np.clip(norms, 1e-12, None)
    return unit
