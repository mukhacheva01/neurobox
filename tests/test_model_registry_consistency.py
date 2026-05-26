"""Consistency tests for text model registry and OpenRouter routing."""


def test_model_registry_guard_passes():
    from services.bot.config.model_registry_guard import validate_model_registry

    assert validate_model_registry() == []


def test_config_wrapper_points_to_canonical_registry():
    import services.bot.config.text_models as canonical
    import shared.config.text_models as cfg_models

    assert cfg_models.TEXT_MODELS == canonical.TEXT_MODELS
    assert cfg_models.TEXT_CREDIT_PRICES == canonical.TEXT_CREDIT_PRICES
    assert cfg_models.TEXT_FREE_MODELS == canonical.TEXT_FREE_MODELS


def test_each_text_model_has_openrouter_route_and_token_cap():
    from shared.config.text_models import TEXT_MODELS
    from shared.providers.openai_text import MODEL_MAX_TOKENS, MODEL_TO_OPENROUTER

    for row in TEXT_MODELS:
        model_id = row[1]
        assert model_id in MODEL_TO_OPENROUTER, f"No route for {model_id}"
        assert model_id in MODEL_MAX_TOKENS, f"No max_tokens cap for {model_id}"
