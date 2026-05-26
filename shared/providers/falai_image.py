"""НейроБокс — fal.ai image provider."""
import asyncio

import httpx
import structlog

log = structlog.get_logger()

# Наш model_id -> fal.ai endpoint (text-to-image)
MODEL_MAP = {
    "flux-2-turbo": "fal-ai/flux/dev",
    "flux-2-pro": "fal-ai/flux-pro/v1.1",
    "flux-2-flex": "fal-ai/flux-2-flex",
    "flux-realism": "fal-ai/flux-realism",
    "grok-imagine-image": "xai/grok-imagine-image",
    "kling-image-v3": "fal-ai/kling-image/v3/text-to-image",
    "ideogram-v2": "fal-ai/ideogram/v2",
    "nano-banana": "fal-ai/flux/dev",  # fallback, нет отдельного t2i на fal
    "dall-e-3": "fal-ai/flux/dev",
    "midjourney": "fal-ai/flux-pro/v1.1",
}


# Маппинг размеров: наш ключ -> (image_size для Flux, aspect_ratio для Grok/Kling/Ideogram)
SIZE_MAP = {
    "landscape": ("landscape_4_3", "4:3"),
    "square": ("square_hd", "1:1"),
    "portrait": ("portrait_4_3", "3:4"),
}


def _image_payload(model: str, prompt: str, num_images: int, size: str = "landscape") -> dict:
    """Payload для fal.ai в зависимости от модели."""
    num_images = max(1, min(4, int(num_images)))
    img_size, aspect = SIZE_MAP.get(size, SIZE_MAP["landscape"])
    if model == "grok-imagine-image":
        return {"prompt": prompt, "num_images": num_images, "aspect_ratio": aspect}
    if model == "kling-image-v3":
        return {"prompt": prompt, "num_images": num_images, "aspect_ratio": aspect}
    if model == "ideogram-v2":
        return {"prompt": prompt, "aspect_ratio": aspect}
    # Flux-семейство и fallback
    return {
        "prompt": prompt,
        "image_size": img_size,
        "num_images": num_images,
        "enable_safety_checker": True,
    }


async def generate_image(prompt, model="flux-2-turbo", num_images=1, size="landscape"):
    from shared.config import settings
    if not settings.falai_api_key:
        return {"ok": False, "error": "fal.ai API key not configured"}
    endpoint = MODEL_MAP.get(model, "fal-ai/flux/dev")
    url = f"https://queue.fal.run/{endpoint}"
    headers = {"Authorization": f"Key {settings.falai_api_key}", "Content-Type": "application/json"}
    payload = _image_payload(model, prompt, num_images, size)
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            if "request_id" in data:
                request_id = data["request_id"]
                status_url = f"https://queue.fal.run/{endpoint}/requests/{request_id}/status"
                result_url = f"https://queue.fal.run/{endpoint}/requests/{request_id}"
                for _ in range(60):
                    await asyncio.sleep(2)
                    try:
                        status_resp = await client.get(status_url, headers=headers)
                        status_data = status_resp.json()
                    except Exception as poll_err:
                        log.warning("fal.ai poll error", error=str(poll_err))
                        continue
                    if status_data.get("status") == "COMPLETED":
                        result_resp = await client.get(result_url, headers=headers)
                        data = result_resp.json()
                        break
                    elif status_data.get("status") in ("FAILED", "CANCELLED"):
                        return {"ok": False, "error": "Генерация не удалась"}
                else:
                    return {"ok": False, "error": "Таймаут генерации"}
            images = data.get("images", [])
            if not images:
                return {"ok": False, "error": "Изображение не сгенерировано"}
            urls = [img.get("url", "") for img in images if img.get("url")]
            return {"ok": True, "image_url": urls[0] if urls else "", "image_urls": urls, "model": model}
    except httpx.HTTPStatusError as e:
        log.error("fal.ai HTTP error", status=e.response.status_code)
        return {"ok": False, "error": f"Ошибка генерации (HTTP {e.response.status_code})"}
    except Exception as e:
        log.error("fal.ai error", error=str(e))
        return {"ok": False, "error": "Ошибка генерации. Попробуйте ещё раз."}


STYLE_ENDPOINT = "fal-ai/flux/dev/image-to-image"

# Маппинг image_model -> endpoint для image-to-image
I2I_MODEL_MAP = {
    "flux-2-turbo": "fal-ai/flux/dev/image-to-image",
    "flux-2-pro": "fal-ai/flux-pro/v1.1/image-to-image",
    "flux-2-flex": "fal-ai/flux/dev/image-to-image",
    "flux-realism": "fal-ai/flux/dev/image-to-image",
    "nano-banana": "fal-ai/flux/dev/image-to-image",
    "dall-e-3": "fal-ai/flux/dev/image-to-image",
    "midjourney": "fal-ai/flux-pro/v1.1/image-to-image",
    "grok-imagine-image": "fal-ai/flux/dev/image-to-image",
    "kling-image-v3": "fal-ai/flux/dev/image-to-image",
    "ideogram-v2": "fal-ai/flux/dev/image-to-image",
}


async def style_image(image_url: str, prompt: str, model: str = None, strength: float = None) -> dict:
    """Стилизация/редактирование фото (fal image-to-image). image_url может быть data URI.
    strength: 0.95 по умолчанию в API; для правки цвета/деталей лучше 0.98–0.99, чтобы сохранить сцену."""
    from shared.config import settings
    if not settings.falai_api_key:
        return {"ok": False, "error": "fal.ai API key не настроен"}
    endpoint = I2I_MODEL_MAP.get(model, STYLE_ENDPOINT) if model else STYLE_ENDPOINT
    headers = {"Authorization": f"Key {settings.falai_api_key}", "Content-Type": "application/json"}
    payload = {"image_url": image_url, "prompt": prompt, "num_images": 1, "enable_safety_checker": True}
    if strength is not None:
        payload["strength"] = max(0.7, min(1.0, strength))

    # Попытка 1: sync endpoint (быстрее, поддерживает base64)
    try:
        sync_url = f"https://fal.run/{endpoint}"
        async with httpx.AsyncClient(timeout=90) as client:
            resp = await client.post(sync_url, json=payload, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                images = data.get("images", [])
                if images and images[0].get("url"):
                    return {"ok": True, "image_url": images[0]["url"]}
            log.info("fal style sync failed, trying queue", status=resp.status_code)
    except Exception as e:
        log.info("fal style sync error, trying queue", error=str(e))

    # Попытка 2: queue endpoint
    try:
        queue_url = f"https://queue.fal.run/{endpoint}"
        async with httpx.AsyncClient(timeout=180) as client:
            resp = await client.post(queue_url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            if "request_id" in data:
                request_id = data["request_id"]
                status_url = f"https://queue.fal.run/{endpoint}/requests/{request_id}/status"
                result_url = f"https://queue.fal.run/{endpoint}/requests/{request_id}"
                for _ in range(60):
                    await asyncio.sleep(3)
                    try:
                        sr = await client.get(status_url, headers=headers)
                        sd = sr.json()
                    except Exception:
                        continue
                    if sd.get("status") == "COMPLETED":
                        rr = await client.get(result_url, headers=headers)
                        data = rr.json()
                        break
                    elif sd.get("status") in ("FAILED", "CANCELLED"):
                        return {"ok": False, "error": "Стилизация не удалась"}
                else:
                    return {"ok": False, "error": "Таймаут стилизации"}
            images = data.get("images", [])
            if not images:
                return {"ok": False, "error": "Изображение не получено"}
            return {"ok": True, "image_url": images[0].get("url", "")}
    except httpx.HTTPStatusError as e:
        body = e.response.text[:200] if e.response else ""
        log.error("fal.ai style HTTP error", status=e.response.status_code, body=body)
        return {"ok": False, "error": f"Ошибка ({e.response.status_code})"}
    except Exception as e:
        log.error("fal.ai style error", error=str(e))
        return {"ok": False, "error": "Ошибка стилизации. Попробуйте ещё раз."}


UPSCALE_ENDPOINT = "fal-ai/esrgan"
UPSCALE_CR = 5


async def upscale_image(image_url: str) -> dict:
    """Апскейл изображения по URL (fal esrgan)."""
    from shared.config import settings
    if not settings.falai_api_key:
        return {"ok": False, "error": "fal.ai API key не настроен"}
    url = f"https://queue.fal.run/{UPSCALE_ENDPOINT}"
    headers = {"Authorization": f"Key {settings.falai_api_key}", "Content-Type": "application/json"}
    payload = {"image_url": image_url}
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            if "request_id" in data:
                request_id = data["request_id"]
                status_url = f"https://queue.fal.run/{UPSCALE_ENDPOINT}/requests/{request_id}/status"
                result_url = f"https://queue.fal.run/{UPSCALE_ENDPOINT}/requests/{request_id}"
                for _ in range(60):
                    await asyncio.sleep(2)
                    status_resp = await client.get(status_url, headers=headers)
                    status_data = status_resp.json()
                    if status_data.get("status") == "COMPLETED":
                        result_resp = await client.get(result_url, headers=headers)
                        data = result_resp.json()
                        break
                    elif status_data.get("status") in ("FAILED", "CANCELLED"):
                        return {"ok": False, "error": "Апскейл не удался"}
                else:
                    return {"ok": False, "error": "Таймаут апскейла"}
            images = data.get("images", [])
            if not images:
                return {"ok": False, "error": "Результат не получен"}
            out_url = images[0].get("url", "")
            return {"ok": True, "image_url": out_url}
    except httpx.HTTPStatusError as e:
        log.error("fal.ai upscale HTTP error", status=e.response.status_code)
        return {"ok": False, "error": f"Ошибка (HTTP {e.response.status_code})"}
    except Exception as e:
        log.error("fal.ai upscale error", error=str(e))
        return {"ok": False, "error": "Ошибка апскейла. Попробуйте ещё раз."}
