"""НейроБокс — fal.ai video provider (universal queue)."""
import asyncio

import httpx
import structlog

log = structlog.get_logger()

async def generate_video(prompt, endpoint, image_url=None):
    from shared.config import settings
    if not settings.falai_api_key:
        return {"ok": False, "error": "fal.ai API key not configured"}

    url = f"https://queue.fal.run/{endpoint}"
    headers = {
        "Authorization": f"Key {settings.falai_api_key}",
        "Content-Type": "application/json",
    }

    payload = {"prompt": prompt}

    # Модели с разными полями
    if "kling" in endpoint:
        payload["duration"] = "5"
        payload["aspect_ratio"] = "16:9"
        if image_url:
            payload["image_url"] = image_url
    elif "minimax" in endpoint or "hailuo" in endpoint:
        payload["prompt_optimizer"] = True
        if image_url:
            payload["first_frame_image"] = image_url
    elif "runway" in endpoint:
        if image_url:
            payload["image_url"] = image_url
            payload["duration"] = 5
        else:
            return {"ok": False, "error": "Runway требует картинку. Отправь фото с подписью /video промпт"}
    elif "seedance" in endpoint:
        if image_url:
            payload["image_url"] = image_url
    elif "wan" in endpoint:
        payload["image_size"] = "landscape_16_9"
        if image_url:
            payload["image_url"] = image_url
    elif "sora" in endpoint:
        payload["aspect_ratio"] = "16:9"
        payload["duration"] = 8
        if image_url:
            # Переключаем на image-to-video endpoint
            endpoint = "fal-ai/sora-2/image-to-video/pro"
            url = f"https://queue.fal.run/{endpoint}"
            payload["image_url"] = image_url
    elif "veo" in endpoint:
        payload["aspect_ratio"] = "16:9"
        payload["duration"] = "8s"
        payload["resolution"] = "720p"
        payload["generate_audio"] = True
        if image_url:
            # Переключаем на reference-to-video endpoint
            endpoint = "fal-ai/veo3.1/reference-to-video"
            url = f"https://queue.fal.run/{endpoint}"
            payload["image_url"] = image_url
    elif "luma" in endpoint:
        if image_url:
            payload["image_url"] = image_url
        payload["aspect_ratio"] = "16:9"
    elif "ltx" in endpoint:
        payload["num_frames"] = 121
        if image_url:
            payload["image_url"] = image_url

    try:
        async with httpx.AsyncClient(timeout=300) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

            if "request_id" in data:
                rid = data["request_id"]
                base = f"https://queue.fal.run/{endpoint}/requests"
                for i in range(120):
                    await asyncio.sleep(3)
                    try:
                        sr = await client.get(f"{base}/{rid}/status", headers=headers)
                        sd = sr.json()
                    except Exception as poll_err:
                        log.warning("fal.ai video poll error", error=str(poll_err))
                        continue
                    status = sd.get("status", "")
                    if status == "COMPLETED":
                        rr = await client.get(f"{base}/{rid}", headers=headers)
                        data = rr.json()
                        break
                    elif status in ("FAILED", "CANCELLED"):
                        err = sd.get("error", "Генерация не удалась")
                        return {"ok": False, "error": str(err)[:200]}
                else:
                    return {"ok": False, "error": "Таймаут генерации (6 мин)"}

            # Ищем видео URL в разных форматах ответа
            video_url = ""
            if "video" in data and isinstance(data["video"], dict):
                video_url = data["video"].get("url", "")
            elif "video_url" in data:
                video_url = data["video_url"]
            elif "output" in data and isinstance(data["output"], dict):
                video_url = data["output"].get("video", {}).get("url", "")
            elif "video" in data and isinstance(data["video"], str):
                video_url = data["video"]

            if not video_url:
                log.warning("No video URL in response", keys=list(data.keys()))
                return {"ok": False, "error": "Видео не найдено в ответе"}

            return {"ok": True, "video_url": video_url}

    except httpx.HTTPStatusError as e:
        body = e.response.text[:500] if e.response else ""
        log.error("fal.ai video HTTP error", status=e.response.status_code, body=body)
        # 403 часто = исчерпан баланс fal.ai
        try:
            data = e.response.json()
            detail = data.get("detail", "") or data.get("error", "") or data.get("message", "")
            if detail and ("balance" in detail.lower() or "locked" in detail.lower() or "top up" in detail.lower()):
                return {"ok": False, "error": f"fal.ai: {detail[:200]}"}
        except Exception:
            pass
        return {"ok": False, "error": f"Ошибка API (HTTP {e.response.status_code})"}
    except Exception as e:
        log.error("fal.ai video error", error=str(e))
        return {"ok": False, "error": "Ошибка генерации видео"}
