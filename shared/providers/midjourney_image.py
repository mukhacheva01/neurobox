"""НейроБокс — Midjourney через прямой API (MidAPI: api.midapi.ai). Асинхронная генерация + опрос статуса."""
import asyncio

import httpx
import structlog

log = structlog.get_logger()

BASE_URL = "https://api.midapi.ai/api/v1/mj"
# Наш size -> aspectRatio Midjourney
ASPECT_MAP = {
    "landscape": "16:9",
    "square": "1:1",
    "portrait": "9:16",
}


async def generate_midjourney_image(
    prompt: str,
    model: str = "midjourney",
    num_images: int = 1,
    size: str = "landscape",
) -> dict:
    """
    Генерация картинки через Midjourney API (MidAPI).
    Отправляет задачу mj_txt2img, опрашивает record-info до готовности (или таймаут 300 с).
    Возвращает {ok, image_url, image_urls, model}.
    """
    from shared.config import settings
    api_key = getattr(settings, "midjourney_api_key", None) or ""
    if not api_key.strip():
        return {"ok": False, "error": "Midjourney API key не настроен (midjourney_api_key)"}

    aspect = ASPECT_MAP.get(size, "16:9")
    headers = {
        "Authorization": f"Bearer {api_key.strip()}",
        "Content-Type": "application/json",
    }
    payload = {
        "taskType": "mj_txt2img",
        "prompt": prompt[:2000],
        "aspectRatio": aspect,
        "version": "7",
        "speed": "fast",
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(f"{BASE_URL}/generate", json=payload, headers=headers)
            data = resp.json() if resp.content else {}
            if resp.status_code != 200 or data.get("code") != 200:
                msg = data.get("msg", resp.text or "Ошибка Midjourney API")[:200]
                log.warning("Midjourney generate failed", status=resp.status_code, msg=msg)
                return {"ok": False, "error": f"Midjourney: {msg}"}
            task_id = (data.get("data") or {}).get("taskId")
            if not task_id:
                return {"ok": False, "error": "Нет taskId в ответе Midjourney"}

        # Опрос до готовности (до ~132 с, раз в 12 с — в пределах таймаута обработчика 150 с)
        for _ in range(11):
            await asyncio.sleep(12)
            async with httpx.AsyncClient(timeout=15) as client:
                status_resp = await client.get(
                    f"{BASE_URL}/record-info",
                    params={"taskId": task_id},
                    headers={"Authorization": f"Bearer {api_key.strip()}"},
                )
            status_data = status_resp.json() if status_resp.content else {}
            if status_resp.status_code != 200 or status_data.get("code") != 200:
                continue
            task_data = status_data.get("data") or {}
            flag = task_data.get("successFlag", -1)
            if flag == 1:
                # Успех
                result_info = task_data.get("resultInfoJson") or {}
                urls = []
                for item in (result_info.get("resultUrls") or []):
                    u = item.get("resultUrl") if isinstance(item, dict) else item
                    if u:
                        urls.append(u)
                if not urls:
                    return {"ok": False, "error": "Midjourney: нет URL в результате"}
                return {"ok": True, "image_url": urls[0], "image_urls": urls, "model": model}
            if flag in (2, 3):
                err = (task_data.get("errorMessage") or "Генерация не удалась")[:150]
                return {"ok": False, "error": f"Midjourney: {err}"}

        return {"ok": False, "error": "Midjourney: таймаут ожидания результата"}
    except httpx.HTTPError as e:
        log.error("Midjourney HTTP error", error=str(e))
        return {"ok": False, "error": f"Ошибка Midjourney: {str(e)[:100]}"}
    except Exception as e:
        log.error("Midjourney error", error=str(e))
        return {"ok": False, "error": f"Ошибка Midjourney: {str(e)[:100]}"}
