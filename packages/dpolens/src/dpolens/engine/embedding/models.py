"""The embedding models DPOLens can use.

An embedding model turns text into numbers. It writes nothing, invents nothing
and needs no API key, which is why search works in an instance with no LLM
configured at all.

Every entry is multilingual, because Arabic is a first-class language here and a
model chosen on English alone would fail the first PDPL question.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EmbeddingModel:
    """One candidate, and everything needed to run it."""

    name: str
    repo: str
    onnx_file: str
    dimensions: int
    query_prefix: str = ""
    passage_prefix: str = ""
    note: str = ""

    @property
    def cache_key(self) -> str:
        return self.name


# e5 models are trained with these prefixes and lose real accuracy without them,
# silently: nothing errors, the numbers are simply worse. Granite is trained
# without them.
E5_QUERY = "query: "
E5_PASSAGE = "passage: "

MODELS: dict[str, EmbeddingModel] = {
    "e5-small": EmbeddingModel(
        name="e5-small",
        repo="intfloat/multilingual-e5-small",
        onnx_file="onnx/model.onnx",
        dimensions=384,
        query_prefix=E5_QUERY,
        passage_prefix=E5_PASSAGE,
    ),
    "e5-small-int8": EmbeddingModel(
        name="e5-small-int8",
        repo="intfloat/multilingual-e5-small",
        onnx_file="onnx/model_qint8_avx512_vnni.onnx",
        dimensions=384,
        query_prefix=E5_QUERY,
        passage_prefix=E5_PASSAGE,
        note="Quantised for AVX512-VNNI. Runs anywhere, fastest on that hardware.",
    ),
    "e5-base": EmbeddingModel(
        name="e5-base",
        repo="intfloat/multilingual-e5-base",
        onnx_file="onnx/model.onnx",
        dimensions=768,
        query_prefix=E5_QUERY,
        passage_prefix=E5_PASSAGE,
    ),
    "granite-97m-int8": EmbeddingModel(
        name="granite-97m-int8",
        repo="ibm-granite/granite-embedding-97m-multilingual-r2",
        onnx_file="onnx/model_quint8_avx2.onnx",
        dimensions=384,
        note="Quantised for AVX2. Takes no prefixes.",
    ),
}

DEFAULT_MODEL = "e5-small"
"""Provisional. The evals choose the default, and the comparison is published."""


def get_model(name: str) -> EmbeddingModel:
    model = MODELS.get(name)
    if model is None:
        raise KeyError(f"unknown embedding model {name!r}: expected one of {sorted(MODELS)}")
    return model
