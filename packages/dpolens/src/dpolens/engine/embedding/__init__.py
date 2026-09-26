"""Turning clause text into vectors, on the CPU, with no API key."""

from dpolens.engine.embedding.encode import Embedder
from dpolens.engine.embedding.models import DEFAULT_MODEL, MODELS, EmbeddingModel, get_model
from dpolens.engine.embedding.recipe import RECIPE_VERSION, RecipeInput, build

__all__ = [
    "DEFAULT_MODEL",
    "MODELS",
    "RECIPE_VERSION",
    "Embedder",
    "EmbeddingModel",
    "RecipeInput",
    "build",
    "get_model",
]
