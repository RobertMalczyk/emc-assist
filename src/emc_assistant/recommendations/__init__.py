"""Recommendation generator matching ``recommendation.schema.json``."""

from emc_assistant.recommendations.engine import (
    Recommendation,
    build_baseline_recommendations,
)

__all__ = ["Recommendation", "build_baseline_recommendations"]
