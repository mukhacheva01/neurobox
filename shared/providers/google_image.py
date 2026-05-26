"""НейроБокс — Google Gemini Image: прямой API (Nano Banana = gemini-2.5-flash-image)."""

import httpx
import structlog

log = structlog.get_logger()

BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


async def generate_gemini_image(prompt: str, model: str = "nano-banana") -> dict:
    """Генерация картинки через Google Gemini API (gemini-2.5-flash-image).
    Возвращает {ok, image_url (base64 data URI), image_urls}.
    """
    from shared.config import settings
    api_key = settings.google_ai_api_key
    if not api_key:
        return {"ok": False, "error": "Google AI API key не настроен"}

    api_model = "gemini-2.0-flash-preview-image-generation"
    url = f"{BASE_URL}/models/{api_model}:generateContent?key={api_key}"

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseModalities": ["IMAGE", "TEXT"],
        },
    }

    headers = {"Content-Type": "application/json"}

    try:
        async with httpx.AsyncClient(timeout=90) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

            # Извлекаем изображения из ответа
            candidates = data.get("candidates", [])
            urls = []
            for cand in candidates:
                parts = cand.get("content", {}).get("parts", [])
                for part in parts:
                    inline = part.get("inlineData")
                    if inline and inline.get("data"):
                        mime = inline.get("mimeType", "image/png")
                        b64 = inline["data"]
                        urls.append(f"data:{mime};base64,{b64}")

            if not urls:
                log.warning("Gemini image: no images in response", keys=list(data.keys()))
                return {"ok": False, "error": "Изображение не сгенерировано"}

            return {"ok": True, "image_url": urls[0], "image_urls": urls, "model": model}

    except httpx.HTTPStatusError as e:
        body = e.response.text[:300] if e.response else ""
        log.error("Gemini image HTTP error", status=e.response.status_code, body=body)
        return {"ok": False, "error": f"Google Gemini ошибка ({e.response.status_code})"}
    except Exception as e:
        log.error("Gemini image error", error=str(e))
        return {"ok": False, "error": f"Ошибка Gemini: {str(e)[:100]}"}
