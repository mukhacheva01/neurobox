"""НейроБокс — xAI (Grok) Image: прямой API (grok-imagine-image)."""
import structlog

from shared.config import settings

log = structlog.get_logger()

# Размеры: наш ключ -> aspect_ratio xAI
ASPECT_MAP = {
    "landscape": "4:3",
    "square": "1:1",
    "portrait": "3:4",
}


async def generate_xai_image(
    prompt: str,
    model: str = "grok-imagine-image",
    num_images: int = 1,
    size: str = "landscape",
) -> dict:
    """Генерация картинки через xAI Images API (прямой)."""
    if not settings.grok_api_key:
        return {"ok": False, "error": "xAI (Grok) API key не настроен"}

    try:
        import openai
        client = openai.AsyncOpenAI(
            api_key=settings.grok_api_key,
            base_url="https://api.x.ai/v1",
        )
        aspect = ASPECT_MAP.get(size, "4:3")
        n = max(1, min(10, num_images))
        resp = await client.images.generate(
            model="grok-imagine-image",
            prompt=prompt,
            n=n,
            aspect_ratio=aspect,
        )
        images = getattr(resp, "data", []) or []
        if not images:
            return {"ok": False, "error": "Изображение не сгенерировано"}
        urls = []
        for img in images:
            url = getattr(img, "url", None)
            if url:
                urls.append(url)
            b64 = getattr(img, "b64_json", None)
            if b64:
                urls.append(f"data:image/png;base64,{b64}")
        if not urls:
            return {"ok": False, "error": "Нет URL в ответе xAI"}
        return {"ok": True, "image_url": urls[0], "image_urls": urls, "model": model}
    except Exception as e:
        log.error("xAI image error", error=str(e))
        return {"ok": False, "error": f"Ошибка xAI: {str(e)[:100]}"}
