"""Concrete implementations of the pipeline stage interfaces.

Each implementation is a stub at scaffolding time (Task 1) and is filled in by its
designated task. Importing this package must always succeed; calling an unimplemented
method raises NotImplementedError pointing at the task that completes it.
"""

from .description import ClaudeDescriptionSource
from .embedder import TitanEmbedder
from .retriever import BruteForceRetriever, AnnRetriever
from .scorer import BlendedScorer
from .profile import DefaultProfileSelector
from .notifier import SesNotifier
from .repository import DynamoItemRepository

__all__ = [
    "ClaudeDescriptionSource",
    "TitanEmbedder",
    "BruteForceRetriever",
    "AnnRetriever",
    "BlendedScorer",
    "DefaultProfileSelector",
    "SesNotifier",
    "DynamoItemRepository",
]
