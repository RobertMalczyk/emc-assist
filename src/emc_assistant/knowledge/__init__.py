"""Loader for rules and metadata from ``knowledge/seed/``."""

from emc_assistant.knowledge.loader import (
    KnowledgeBase,
    ParasiticRule,
    EmcRule,
    load_default_knowledge,
)

__all__ = [
    "KnowledgeBase",
    "ParasiticRule",
    "EmcRule",
    "load_default_knowledge",
]
