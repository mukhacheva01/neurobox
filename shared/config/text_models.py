"""Compatibility wrapper around the canonical text model registry.

Single source of truth: bot.config.text_models
"""

from services.bot.config.text_models import (
    MODEL_CATEGORIES,
    RECOMMENDED_MODEL,
    TEXT_CREDIT_PRICES,
    TEXT_FREE_MODELS,
    TEXT_MODEL_IDS,
    TEXT_MODELS,
    get_model_category,
    get_model_price,
    get_models_by_category,
    is_free_model,
)

__all__ = [
    "TEXT_MODELS",
    "TEXT_MODEL_IDS",
    "TEXT_CREDIT_PRICES",
    "TEXT_FREE_MODELS",
    "MODEL_CATEGORIES",
    "RECOMMENDED_MODEL",
    "get_models_by_category",
    "get_model_category",
    "get_model_price",
    "is_free_model",
]
