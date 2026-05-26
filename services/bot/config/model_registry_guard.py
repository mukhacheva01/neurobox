"""Runtime consistency checks for model registry and provider routing."""

from __future__ import annotations


def validate_model_registry() -> list[str]:
    errors: list[str] = []

    from shared.config.text_models import (
        TEXT_CREDIT_PRICES,
        TEXT_FREE_MODELS,
        TEXT_MODELS,
    )
    from shared.providers.openai_text import MODEL_MAX_TOKENS, MODEL_TO_OPENROUTER

    model_ids = [row[1] for row in TEXT_MODELS]
    seen: set[str] = set()
    dupes: list[str] = []
    for mid in model_ids:
        if mid in seen and mid not in dupes:
            dupes.append(mid)
        seen.add(mid)

    if dupes:
        errors.append(f"Duplicate model_id in TEXT_MODELS: {dupes}")

    missing_price = [mid for mid in model_ids if mid not in TEXT_CREDIT_PRICES]
    if missing_price:
        errors.append(f"Missing TEXT_CREDIT_PRICES for: {missing_price}")

    bad_price = [mid for mid in model_ids if int(TEXT_CREDIT_PRICES.get(mid, 0)) <= 0]
    if bad_price:
        errors.append(f"Non-positive price for: {bad_price}")

    missing_router = [mid for mid in model_ids if mid not in MODEL_TO_OPENROUTER]
    if missing_router:
        errors.append(f"Missing MODEL_TO_OPENROUTER mapping for: {missing_router}")

    missing_max_tokens = [mid for mid in model_ids if mid not in MODEL_MAX_TOKENS]
    if missing_max_tokens:
        errors.append(f"Missing MODEL_MAX_TOKENS for: {missing_max_tokens}")

    bad_free = [mid for mid in TEXT_FREE_MODELS if mid not in seen]
    if bad_free:
        errors.append(f"TEXT_FREE_MODELS has unknown ids: {bad_free}")

    return errors


def assert_model_registry_consistency() -> None:
    errors = validate_model_registry()
    if errors:
        raise RuntimeError("Model registry validation failed: " + " | ".join(errors))
