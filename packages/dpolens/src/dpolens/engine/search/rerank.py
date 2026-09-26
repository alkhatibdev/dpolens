"""Rescoring the top candidates with a cross-encoder.

Retrieval scores a question and a clause separately and compares the results. A
cross-encoder reads both together, which is more accurate and far more
expensive, so it only ever sees the top of the fused list.

It is not an LLM: it takes a pair of texts and returns one number. No API key,
no generation, nothing to configure.

Whether it ships is an empirical question. It has to beat the fused baseline by
more than the confidence interval on the held-out set, or it is weight in the
image for nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import TracebackType

import numpy as np
import onnxruntime as ort
from huggingface_hub import hf_hub_download
from tokenizers import Tokenizer

from dpolens.engine.search.fuse import Fused

MAX_SEQUENCE = 512
DEFAULT_DEPTH = 25
"""How many candidates get rescored. Deeper is more accurate and slower, and the
evals report the curve rather than assuming a number."""


@dataclass(frozen=True)
class RerankerModel:
    name: str
    repo: str
    onnx_file: str
    note: str = ""


RERANKERS: dict[str, RerankerModel] = {
    "jina-v2-multilingual": RerankerModel(
        name="jina-v2-multilingual",
        repo="jinaai/jina-reranker-v2-base-multilingual",
        onnx_file="onnx/model.onnx",
        note="The only multilingual cross-encoder with an ONNX build in the candidate set.",
    ),
    "jina-v2-multilingual-fp16": RerankerModel(
        name="jina-v2-multilingual-fp16",
        repo="jinaai/jina-reranker-v2-base-multilingual",
        onnx_file="onnx/model_fp16.onnx",
        note="Half the size on disk.",
    ),
}


class Reranker:
    """One loaded cross-encoder, ready to rescore query and clause pairs."""

    def __init__(self, model: RerankerModel, cache_dir: Path | None = None) -> None:
        self.model = model
        cache = str(cache_dir) if cache_dir else None

        self.tokenizer = Tokenizer.from_file(
            hf_hub_download(model.repo, "tokenizer.json", cache_dir=cache)
        )
        self.tokenizer.enable_truncation(max_length=MAX_SEQUENCE)
        self.tokenizer.enable_padding()

        weights = hf_hub_download(model.repo, model.onnx_file, cache_dir=cache)
        options = ort.SessionOptions()
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.session = ort.InferenceSession(weights, options, providers=["CPUExecutionProvider"])
        self._inputs = {value.name for value in self.session.get_inputs()}

    def close(self) -> None:
        if getattr(self, "session", None) is not None:
            del self.session

    def __enter__(self) -> Reranker:
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def scores(self, query: str, passages: list[str]) -> list[float]:
        """One relevance score per passage, read against the query."""
        if not passages:
            return []

        encoded = self.tokenizer.encode_batch([(query, passage) for passage in passages])
        ids = np.array([item.ids for item in encoded], dtype=np.int64)
        mask = np.array([item.attention_mask for item in encoded], dtype=np.int64)

        feed: dict[str, np.ndarray] = {"input_ids": ids, "attention_mask": mask}
        if "token_type_ids" in self._inputs:
            feed["token_type_ids"] = np.array([item.type_ids for item in encoded], dtype=np.int64)

        logits = self.session.run(None, feed)[0]
        return [float(value) for value in np.asarray(logits).reshape(len(passages), -1)[:, 0]]


def rerank(
    reranker: Reranker,
    query: str,
    candidates: list[Fused],
    texts: dict[str, str],
    depth: int = DEFAULT_DEPTH,
) -> list[Fused]:
    """Rescore the top candidates, leaving the tail in its fused order."""
    head, tail = candidates[:depth], candidates[depth:]
    if not head:
        return candidates

    scored = reranker.scores(query, [texts.get(candidate.key, "") for candidate in head])
    rescored = [
        Fused(key=candidate.key, lang=candidate.lang, score=score, ranks=candidate.ranks)
        for candidate, score in zip(head, scored, strict=True)
    ]
    rescored.sort(key=lambda item: (-item.score, item.key))
    return rescored + tail
