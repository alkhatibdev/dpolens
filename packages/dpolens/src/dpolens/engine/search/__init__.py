"""Retrieval: finding the clauses that answer a question."""

from dpolens.engine.search.engine import Expand, SearchResult, search
from dpolens.engine.search.fuse import RRF, Fused, Fusion, convex, fuse, reciprocal_rank
from dpolens.engine.search.keyword import (
    ALTERNATIVES,
    INDEXES,
    SEARCHABLE_LANGUAGES,
    Candidate,
    KeywordIndex,
    UnsupportedLanguage,
    keyword_search,
)
from dpolens.engine.search.language import language_of
from dpolens.engine.search.vector import NoActiveModel, vector_search

__all__ = [
    "ALTERNATIVES",
    "INDEXES",
    "RRF",
    "SEARCHABLE_LANGUAGES",
    "Candidate",
    "Expand",
    "Fused",
    "Fusion",
    "KeywordIndex",
    "NoActiveModel",
    "SearchResult",
    "UnsupportedLanguage",
    "convex",
    "fuse",
    "keyword_search",
    "language_of",
    "reciprocal_rank",
    "search",
    "vector_search",
]
