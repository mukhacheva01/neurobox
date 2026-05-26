"""НейроБокс — единый реестр текстовых моделей (single source of truth).

Все остальные модули должны импортировать модели/цены отсюда
(или через config.text_models-wrapper).
"""

# (display_name, model_id, price_str, is_free, category)
# category: fast | smart | powerful | elite
TEXT_MODELS = [
    # --- Fast (1-2 CR) ---
    ("GPT-5 nano", "gpt-5-nano", "⚡ 1 CR", True, "fast"),
    ("GPT-4.1 nano", "gpt-4.1-nano", "⚡ 1 CR", True, "fast"),
    ("Gemini 2.0 Flash", "gemini-2.0-flash", "⚡ 1 CR", True, "fast"),
    ("DeepSeek Chat", "deepseek-chat", "1 CR", False, "fast"),
    ("Grok 3 mini", "grok-3-mini", "1 CR", False, "fast"),
    ("GPT-5 mini", "gpt-5-mini", "2 CR", False, "fast"),
    ("GPT-4.1 mini", "gpt-4.1-mini", "2 CR", False, "fast"),
    ("Gemini 2.5 Flash", "gemini-2.5-flash", "2 CR", False, "fast"),
    ("DeepSeek Reasoner", "deepseek-reasoner", "2 CR", False, "fast"),
    ("Grok 4 Fast", "grok-4-1-fast-non-reasoning", "2 CR", False, "fast"),

    # --- Smart (5-10 CR) ---
    ("Claude Haiku 4.5", "claude-haiku-4-5-20251001", "5 CR", False, "smart"),
    ("Grok 4 Fast Reasoning", "grok-4-1-fast-reasoning", "5 CR", False, "smart"),
    ("GPT-4.1", "gpt-4.1", "⭐ 10 CR", False, "smart"),
    ("Gemini 2.5 Pro", "gemini-2.5-pro", "⭐ 10 CR", False, "smart"),
    ("Grok 2", "grok-2", "⭐ 10 CR", False, "smart"),
    ("Grok 3", "grok-3", "⭐ 10 CR", False, "smart"),
    ("Grok 4", "grok-4", "⭐ 10 CR", False, "smart"),
    ("Claude Sonnet 4.5", "claude-sonnet-4-5-20250929", "10 CR", False, "smart"),
    ("Gemini 3 Flash", "gemini-3-flash-preview", "10 CR", False, "smart"),

    # --- Powerful (15 CR) ---
    ("Claude Sonnet 4", "claude-sonnet-4-20250514", "🔥 15 CR", False, "powerful"),
    ("GPT-5", "gpt-5", "🔥 15 CR", False, "powerful"),
    ("GPT-5.1", "gpt-5.1", "🔥 15 CR", False, "powerful"),
    ("Gemini 3 Pro", "gemini-3-pro-preview", "15 CR", False, "powerful"),

    # --- Elite (25 CR) ---
    ("GPT-5.2", "gpt-5.2", "💎 25 CR", False, "elite"),
    ("GPT-5.2 Pro", "gpt-5.2-pro", "💎 25 CR", False, "elite"),
    ("Claude Opus 4.6", "claude-opus-4-6", "💎 25 CR", False, "elite"),
    ("Claude Opus 4.1", "claude-opus-4-1-20250805", "💎 25 CR", False, "elite"),
]

TEXT_MODEL_IDS = {m[1] for m in TEXT_MODELS}

TEXT_CREDIT_PRICES = {
    # Fast
    "gpt-5-nano": 1,
    "gpt-4.1-nano": 1,
    "gemini-2.0-flash": 1,
    "deepseek-chat": 1,
    "grok-3-mini": 1,
    "gpt-5-mini": 2,
    "gpt-4.1-mini": 2,
    "gemini-2.5-flash": 2,
    "deepseek-reasoner": 2,
    "grok-4-1-fast-non-reasoning": 2,

    # Smart
    "claude-haiku-4-5-20251001": 5,
    "grok-4-1-fast-reasoning": 5,
    "gpt-4.1": 10,
    "gemini-2.5-pro": 10,
    "grok-2": 10,
    "grok-3": 10,
    "grok-4": 10,
    "claude-sonnet-4-5-20250929": 10,
    "gemini-3-flash-preview": 10,

    # Powerful
    "claude-sonnet-4-20250514": 15,
    "gpt-5": 15,
    "gpt-5.1": 15,
    "gemini-3-pro-preview": 15,

    # Elite
    "gpt-5.2": 25,
    "gpt-5.2-pro": 25,
    "claude-opus-4-6": 25,
    "claude-opus-4-1-20250805": 25,
}

TEXT_FREE_MODELS = {
    "gpt-5-nano",
    "gpt-4.1-nano",
    "gemini-2.0-flash",
}

MODEL_CATEGORIES = {
    "fast": {"emoji": "⚡", "title": "Быстрые", "subtitle": "1-2 CR"},
    "smart": {"emoji": "⭐", "title": "Умные", "subtitle": "5-10 CR"},
    "powerful": {"emoji": "🔥", "title": "Мощные", "subtitle": "15 CR"},
    "elite": {"emoji": "💎", "title": "Элитные", "subtitle": "25 CR"},
}

RECOMMENDED_MODEL = "gpt-5-nano"


def get_models_by_category(category: str) -> list[tuple]:
    return [m for m in TEXT_MODELS if len(m) >= 5 and m[4] == category]


def get_model_category(model_id: str) -> str:
    for row in TEXT_MODELS:
        if row[1] == model_id:
            return row[4] if len(row) >= 5 else "fast"
    return "fast"


def get_model_price(model_id: str) -> int:
    return int(TEXT_CREDIT_PRICES.get(model_id, 1))


def is_free_model(model_id: str) -> bool:
    return model_id in TEXT_FREE_MODELS
