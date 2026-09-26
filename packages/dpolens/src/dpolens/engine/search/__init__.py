"""Retrieval: finding the clauses that answer a question."""

from dpolens.engine.search.engine import Expand, SearchResult, search
from dpolens.engine.search.fuse import RRF, Fused, Fusion, convex, fuse, reciprocal_rank
from dpolens.engine.search.keyword import Candidate, UnsupportedLanguage, keyword_search
from dpolens.engine.search.vector import NoActiveModel, vector_search

__all__ = [
    "RRF",
    "Candidate",
    "Expand",
    "Fused",
    "Fusion",
    "NoActiveModel",
    "SearchResult",
    "UnsupportedLanguage",
    "convex",
    "fuse",
    "keyword_search",
    "reciprocal_rank",
    "search",
    "vector_search",
]
