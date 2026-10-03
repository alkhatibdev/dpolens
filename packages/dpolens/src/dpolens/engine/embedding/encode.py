"""Running an embedding model on the CPU.

ONNX Runtime with tokenizers, and mean pooling written out here, because the
alternative is PyTorch: 1.0 GB installed against 213 MB, in a tool whose promise
is that one command starts it with nothing to configure.
"""

from __future__ import annotations

import threading
from pathlib import Path
from types import TracebackType

import numpy as np
import onnxruntime as ort
from huggingface_hub import hf_hub_download, try_to_load_from_cache
from tokenizers import Tokenizer

from dpolens.engine.embedding.models import EmbeddingModel

MAX_SEQUENCE = 512


class ModelNotCached(Exception):
    """The model is not on this machine, and this process will not fetch it."""


def ensure_cached(model: EmbeddingModel, cache_dir: Path | None = None) -> None:
    """Refuse to continue unless the model is already here.

    A server reaching for the network on its first request breaks the promise
    that the container runs offline, and makes one developer's first search take
    a minute for reasons they cannot see. Better to say so at startup.
    """
    cache = str(cache_dir) if cache_dir else None
    missing = [
        name
        for name in ("tokenizer.json", model.onnx_file)
        if not isinstance(try_to_load_from_cache(model.repo, name, cache_dir=cache), str)
    ]
    if missing:
        where = cache or "the default Hugging Face cache"
        raise ModelNotCached(
            f"{model.repo} is not in {where}, missing {', '.join(missing)}. Run "
            "`dpolens model fetch` once on a machine with a network, bake the model into "
            "the image, or mount the cache."
        )


def fetch(model: EmbeddingModel, cache_dir: Path | None = None) -> list[Path]:
    """Download the files a model needs, and return where they landed.

    The one moment DPOLens reaches the network. Run it while building an image or
    once on a machine that has a network, and every search afterwards is local.
    """
    cache = str(cache_dir) if cache_dir else None
    return [
        Path(hf_hub_download(model.repo, name, cache_dir=cache))
        for name in ("tokenizer.json", model.onnx_file)
    ]


class Embedder:
    """One loaded model, ready to turn text into vectors."""

    def __init__(
        self,
        model: EmbeddingModel,
        cache_dir: Path | None = None,
        intra_op_num_threads: int | None = None,
    ) -> None:
        self.model = model
        cache = str(cache_dir) if cache_dir else None

        # The session is shared across threads, which ONNX Runtime supports. The
        # tokenizer is not: the Rust object raises "Already borrowed" when two
        # threads reach it at once, on every build except the free-threaded one.
        # It is small, so each thread gets its own from the same file.
        self._tokenizer_path = hf_hub_download(model.repo, "tokenizer.json", cache_dir=cache)
        self._local = threading.local()

        weights = hf_hub_download(model.repo, model.onnx_file, cache_dir=cache)
        options = ort.SessionOptions()
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        if intra_op_num_threads is not None:
            # Left alone, ONNX Runtime claims every core, and several concurrent
            # requests each claiming every core is slower than one at a time.
            options.intra_op_num_threads = intra_op_num_threads
        self.session = ort.InferenceSession(weights, options, providers=["CPUExecutionProvider"])
        self._inputs = {value.name for value in self.session.get_inputs()}

    @property
    def tokenizer(self) -> Tokenizer:
        """This thread's tokenizer, built on first use and kept for the thread."""
        existing = getattr(self._local, "tokenizer", None)
        if existing is None:
            existing = Tokenizer.from_file(self._tokenizer_path)
            existing.enable_truncation(max_length=MAX_SEQUENCE)
            existing.enable_padding()
            self._local.tokenizer = existing
        return existing

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
