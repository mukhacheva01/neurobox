"""НейроБокс — OpenRouter Image generation provider.
Uses /v1/chat/completions with modalities: ["image"] via the existing
OpenRouter client singleton from openai_text.py.

Supports: Flux, GPT Image, Gemini Image — all through a single API.
Also handles image editing, upscale (via re-generation), and background removal.
"""
import base64

import structlog

log = structlog.get_logger()

# Bot model ID → OpenRouter model ID
# ALL image models go through OpenRouter — no direct API calls
MODEL_MAP: dict[str, str] = {
    # --- OpenAI ---
    "gpt-image":          "openai/gpt-5-image",
    "dall-e-3":           "openai/gpt-5-image",        # DALL-E 3 deprecated → GPT-5 Image
    # --- Google Gemini ---
    "nano-banana":        "google/gemini-2.5-flash-image",
    "nano-banana-pro-2k": "google/gemini-3-pro-image-preview",
    "nano-banana-pro-4k": "google/gemini-3-pro-image-preview",
    # --- Flux (Black Forest Labs) ---
    "flux-2-turbo":       "black-forest-labs/flux.2-klein-4b",
    "flux-2-pro":         "black-forest-labs/flux.2-pro",
    "flux-2-flex":        "black-forest-labs/flux.2-flex",
    "flux-realism":       "black-forest-labs/flux.2-max",
    # --- Models without direct OR equivalent → best Flux match ---
    "grok-imagine-image": "black-forest-labs/flux.2-pro",     # Grok Image → Flux Pro
    "kling-image-v3":     "black-forest-labs/flux.2-pro",     # Kling → Flux Pro
    "ideogram-v2":        "black-forest-labs/flux.2-flex",    # Ideogram → Flux Flex
    "midjourney":         "black-forest-labs/flux.2-max",     # Midjourney → Flux Max
}

# Size key → OpenRouter image_config
ASPECT_MAP: dict[str, str] = {
    "landscape": "16:9",
    "square":    "1:1",
    "portrait":  "9:16",
}

# Quality/resolution overrides for premium models
_QUALITY_OVERRIDES: dict[str, dict] = {
    "nano-banana-pro-2k": {"image_size": "2K"},
    "nano-banana-pro-4k": {"image_size": "4K"},
}

# Models that support both text and image output
_TEXT_AND_IMAGE_MODELS = {
    "openai/gpt-5-image",
    "google/gemini-2.5-flash-image",
    "google/gemini-3-pro-image-preview",
}


async def generate_openrouter_image(
    prompt: str,
    model: str,
    num_images: int = 1,
    size: str = "landscape",
) -> dict:
    """Generate image(s) via OpenRouter chat completions API.

    Returns the standard format:
      {"ok": True, "image_url": "data:...", "image_urls": [...], "model": "..."}
    On error:
      {"ok": False, "error": "..."}
    """
    api_model = MODEL_MAP.get(model)
    if not api_model:
        return {"ok": False, "error": f"Модель {model} не поддерживается OpenRouter"}

    from shared.providers.openai_text import _get_openrouter_client
    client = _get_openrouter_client()

    # Build image_config
    image_config: dict = {"aspect_ratio": ASPECT_MAP.get(size, "16:9")}
    if model in _QUALITY_OVERRIDES:
        image_config.update(_QUALITY_OVERRIDES[model])

    # Determine modalities
    if api_model in _TEXT_AND_IMAGE_MODELS:
        modalities = ["image", "text"]
    else:
        modalities = ["image"]

    urls: list[str] = []
    attempts = max(1, min(4, num_images))

    for i in range(attempts):
        try:
            response = await client.chat.completions.create(
                model=api_model,
                messages=[{"role": "user", "content": prompt}],
                extra_body={
                    "modalities": modalities,
                    "image_config": image_config,
                },
            )
            # The images field is non-standard; must use model_dump()
            raw = response.model_dump()
            message = raw.get("choices", [{}])[0].get("message", {})
            images = message.get("images", [])
            for img in images:
                img_url = img.get("image_url", {})
                url = img_url.get("url", "") if isinstance(img_url, dict) else ""
                if url:
                    urls.append(url)

            # If we got enough images, stop early
            if len(urls) >= num_images:
                break

        except Exception as e:
            err_str = str(e)[:200]
            log.error("openrouter_image_error", error=err_str,
                      model=model, api_model=api_model, attempt=i + 1)
            if i == 0:
                # First attempt failed — return error immediately
                return {"ok": False, "error": f"Ошибка OpenRouter: {str(e)[:100]}"}
            # Subsequent attempts: stop and return what we have
            break

    if not urls:
        log.warning("openrouter_image_no_urls", model=model, api_model=api_model)
        return {"ok": False, "error": "Изображение не получено от OpenRouter"}

    log.info("openrouter_image_ok", model=model, api_model=api_model,
             count=len(urls), requested=num_images)
    return {
        "ok": True,
        "image_url": urls[0],
        "image_urls": urls[:num_images],
        "model": model,
    }


# ---------------------------------------------------------------------------
# Image editing via OpenRouter (replaces direct OpenAI edit + fal.ai style)
# ---------------------------------------------------------------------------
_EDIT_MODEL = "openai/gpt-5-image"  # best for editing — understands vision + generates images


async def edit_openrouter_image(image_bytes: bytes, prompt: str, model: str = "gpt-image") -> dict:
    """Edit an image via OpenRouter multimodal chat (vision → image generation).

    Sends the original image as a base64 image_url in the user message,
    plus the editing prompt. The model outputs a modified image.

    Returns: {"ok": True, "image_url": "data:...", "model": "..."}
    """
    from shared.providers.openai_text import _get_openrouter_client
    client = _get_openrouter_client()

    # Encode the source image as data URI
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    data_uri = f"data:image/jpeg;base64,{b64}"

    # Use the model from MODEL_MAP if available, otherwise default to GPT-5-Image
    api_model = MODEL_MAP.get(model, _EDIT_MODEL)
    # For editing, prefer models that support vision + image output
    if api_model not in _TEXT_AND_IMAGE_MODELS:
        api_model = _EDIT_MODEL

    edit_prompt = (
        "Same photo, same person and scene. Only apply this change, "
        "keep everything else identical: " + prompt.strip()
    )

    try:
        response = await client.chat.completions.create(
            model=api_model,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_uri}},
                    {"type": "text", "text": edit_prompt},
                ],
            }],
            extra_body={
                "modalities": ["image", "text"],
                "image_config": {"aspect_ratio": "1:1"},
            },
        )
        raw = response.model_dump()
        message = raw.get("choices", [{}])[0].get("message", {})
        images = message.get("images", [])
        for img in images:
            img_url = img.get("image_url", {})
            url = img_url.get("url", "") if isinstance(img_url, dict) else ""
            if url:
                log.info("openrouter_edit_ok", model=model, api_model=api_model)
                return {"ok": True, "image_url": url, "model": model}

        log.warning("openrouter_edit_no_images", model=model, api_model=api_model)
        return {"ok": False, "error": "Отредактированное изображение не получено"}

    except Exception as e:
        log.error("openrouter_edit_error", error=str(e)[:200], model=model)
        return {"ok": False, "error": f"Ошибка редактирования: {str(e)[:100]}"}


# ---------------------------------------------------------------------------
# Upscale via OpenRouter (re-generate at higher quality)
# ---------------------------------------------------------------------------
_UPSCALE_MODEL = "google/gemini-3-pro-image-preview"  # supports high-res output
UPSCALE_CR = 5  # credit cost (same as fal.ai)


async def upscale_openrouter_image(image_url: str) -> dict:
    """Upscale / enhance image via OpenRouter.

    Sends the image to a high-quality model with instruction to enhance it.
    For base64 data URIs — passes directly; for http URLs — passes as-is.

    Returns: {"ok": True, "image_url": "data:..."}
    """
    from shared.providers.openai_text import _get_openrouter_client
    client = _get_openrouter_client()

    # If image_url is a regular URL, we pass it directly as image_url
    # If it's a data URI, it also works in the content
    content = [
        {"type": "image_url", "image_url": {"url": image_url}},
        {"type": "text", "text": (
            "Enhance and upscale this image to the highest quality possible. "
            "Make it sharper, increase detail and resolution. "
            "Keep the exact same content, composition, and style. "
            "Output only the enhanced image."
        )},
    ]

    try:
        response = await client.chat.completions.create(
            model=_UPSCALE_MODEL,
            messages=[{"role": "user", "content": content}],
            extra_body={
                "modalities": ["image", "text"],
                "image_config": {"image_size": "4K"},
            },
        )
        raw = response.model_dump()
        message = raw.get("choices", [{}])[0].get("message", {})
        images = message.get("images", [])
        for img in images:
            img_url_obj = img.get("image_url", {})
            url = img_url_obj.get("url", "") if isinstance(img_url_obj, dict) else ""
            if url:
                log.info("openrouter_upscale_ok")
                return {"ok": True, "image_url": url}

        log.warning("openrouter_upscale_no_images")
        return {"ok": False, "error": "Улучшенное изображение не получено"}

    except Exception as e:
        log.error("openrouter_upscale_error", error=str(e)[:200])
        return {"ok": False, "error": f"Ошибка апскейла: {str(e)[:100]}"}


# ---------------------------------------------------------------------------
# Background removal via OpenRouter
# ---------------------------------------------------------------------------
_RMBG_MODEL = "openai/gpt-5-image"  # GPT Image handles rmbg well


async def remove_background_openrouter(image_url: str = None, image_bytes: bytes = None) -> dict:
    """Remove background from image via OpenRouter.

    Sends image to a vision+image model with instruction to remove the background.

    Returns: {"ok": True, "image_url": "data:..."}
    """
    from shared.providers.openai_text import _get_openrouter_client
    client = _get_openrouter_client()

    if image_bytes:
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        src_url = f"data:image/jpeg;base64,{b64}"
    elif image_url:
        src_url = image_url
    else:
        return {"ok": False, "error": "Нужно фото"}

    content = [
        {"type": "image_url", "image_url": {"url": src_url}},
        {"type": "text", "text": (
            "Remove the background from this image completely. "
            "Keep only the main subject/object. Replace the background with "
            "a clean transparent or white background. "
            "Output only the resulting image with the background removed."
        )},
    ]

    try:
        response = await client.chat.completions.create(
            model=_RMBG_MODEL,
            messages=[{"role": "user", "content": content}],
            extra_body={
                "modalities": ["image", "text"],
                "image_config": {"aspect_ratio": "1:1"},
            },
        )
        raw = response.model_dump()
        message = raw.get("choices", [{}])[0].get("message", {})
        images = message.get("images", [])
        for img in images:
            img_url_obj = img.get("image_url", {})
            url = img_url_obj.get("url", "") if isinstance(img_url_obj, dict) else ""
            if url:
                log.info("openrouter_rmbg_ok")
                return {"ok": True, "image_url": url}

        log.warning("openrouter_rmbg_no_images")
        return {"ok": False, "error": "Изображение без фона не получено"}

    except Exception as e:
        log.error("openrouter_rmbg_error", error=str(e)[:200])
        return {"ok": False, "error": f"Ошибка удаления фона: {str(e)[:100]}"}
