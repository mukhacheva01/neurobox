"""НейроБокс — fal.ai: удаление фона (rmbg)."""
import asyncio
import base64

import httpx
import structlog

log = structlog.get_logger()

REMBG_ENDPOINT = "fal-ai/imageutils/rembg"


async def remove_background(image_url: str = None, image_bytes: bytes = None) -> dict:
    """Удалить фон. image_url или image_bytes (jpg/png).
    Сначала пробуем sync-режим (быстрый), при неудаче — queue с polling."""
    from shared.config import settings
    if not settings.falai_api_key:
        return {"ok": False, "error": "fal.ai не настроен"}

    endpoint = REMBG_ENDPOINT
    headers = {"Authorization": f"Key {settings.falai_api_key}", "Content-Type": "application/json"}

    if image_bytes:
        b64 = base64.b64encode(image_bytes).decode()
        payload = {"image_url": f"data:image/jpeg;base64,{b64}"}
    elif image_url:
        payload = {"image_url": image_url}
    else:
        return {"ok": False, "error": "Нужно фото"}

    # --- Попытка 1: прямой (sync) вызов ---
    try:
        sync_url = f"https://fal.run/{endpoint}"
        async with httpx.AsyncClient(timeout=90) as client:
            resp = await client.post(sync_url, json=payload, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                url = _extract_url(data)
                if url:
                    return {"ok": True, "image_url": url}
            log.info("fal rembg sync failed, trying queue", status=resp.status_code)
    except Exception as e:
        log.info("fal rembg sync error, trying queue", error=str(e))

    # --- Попытка 2: queue с polling ---
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
                for _ in range(45):
                    await asyncio.sleep(3)
                    try:
                        sr = await client.get(status_url, headers=headers)
                        sd = sr.json()
                    except Exception as poll_err:
                        log.warning("fal rembg poll error", error=str(poll_err))
                        continue
                    status = sd.get("status", "")
                    if status == "COMPLETED":
                        rr = await client.get(result_url, headers=headers)
                        data = rr.json()
                        break
                    elif status in ("FAILED", "CANCELLED"):
                        err = sd.get("error", "Удаление фона не удалось")
                        return {"ok": False, "error": str(err)[:200]}
                else:
                    return {"ok": False, "error": "Таймаут удаления фона (2+ мин)"}

            url = _extract_url(data)
            if url:
                return {"ok": True, "image_url": url}
            log.warning("fal rembg unexpected response", data=str(data)[:300])
            return {"ok": False, "error": "Нет результата"}
    except httpx.HTTPStatusError as e:
        log.error("fal rembg HTTP", status=e.response.status_code, body=e.response.text[:200])
        return {"ok": False, "error": f"Ошибка API ({e.response.status_code})"}
    except Exception as e:
        log.error("fal rembg", error=str(e))
        return {"ok": False, "error": "Ошибка обработки фото"}


def _extract_url(data: dict) -> str | None:
    """Извлечь URL результата из разных форматов ответа fal.ai."""
    # {"image": {"url": "..."}}
    image_obj = data.get("image")
    if isinstance(image_obj, dict) and image_obj.get("url"):
        return image_obj["url"]
    # {"output": {"url": "..."}}
    out = data.get("output", {})
    if isinstance(out, dict) and out.get("url"):
        return out["url"]
    # {"images": [{"url": "..."}]}
    images = data.get("images", [])
    if images and isinstance(images[0], dict) and images[0].get("url"):
        return images[0]["url"]
    return None
