"""НейроБокс — Google Veo: прямой API (generativelanguage.googleapis.com)."""
import asyncio

import httpx
import structlog

log = structlog.get_logger()

BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

# model_id бота → Google API model name
VEO_MODELS = {
    "veo-3.1":       "veo-3.1-generate-preview",
    "veo-3.1-audio": "veo-3.1-generate-preview",
    "veo-3.1-fast":  "veo-3.1-fast-generate-preview",
}


async def generate_veo_video(prompt: str, model: str = "veo-3.1",
                              image_base64: str = None, image_mime: str = "image/jpeg") -> dict:
    """Генерация видео через Google Veo API.
    prompt — текстовый промпт.
    image_base64 — base64 картинки (без data: prefix) для image-to-video.
    Возвращает {ok, video_url} или {ok: False, error}.
    """
    from shared.config import settings
    api_key = settings.google_ai_api_key
    if not api_key:
        return {"ok": False, "error": "Google AI API key не настроен"}

    api_model = VEO_MODELS.get(model, "veo-3.1-generate-preview")
    url = f"{BASE_URL}/models/{api_model}:predictLongRunning"

    # Собираем instance
    instance = {"prompt": prompt}
    if image_base64:
        instance["image"] = {
            "bytesBase64Encoded": image_base64,
            "mimeType": image_mime,
        }

    params = {
        "aspectRatio": "16:9",
        "durationSeconds": 8,
        "personGeneration": "allow_all",
    }
    if model == "veo-3.1-audio":
        params["generateAudio"] = True
    payload = {"instances": [instance], "parameters": params}
    headers = {
        "x-goog-api-key": api_key,
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code != 200:
                body = resp.text[:300]
                log.error("Veo API submit error", status=resp.status_code, body=body)
                return {"ok": False, "error": f"Google Veo API ошибка ({resp.status_code})"}
            data = resp.json()
            operation_name = data.get("name")
            if not operation_name:
                return {"ok": False, "error": "Не получен operation name от Google"}

        # Polling — ждём завершения (до 6 мин)
        poll_url = f"{BASE_URL}/{operation_name}"
        async with httpx.AsyncClient(timeout=30) as client:
            for i in range(72):  # 72 * 5с = 360с = 6 мин
                await asyncio.sleep(5)
                try:
                    sr = await client.get(poll_url, headers=headers)
                    sd = sr.json()
                except Exception as e:
                    log.warning("Veo poll error", error=str(e))
                    continue

                if sd.get("done"):
                    # Извлекаем URL/байты видео (Gemini API может возвращать разную структуру)
                    response = sd.get("response", {})
                    video_uri = ""
                    video_b64 = ""
                    # Путь 1: generateVideoResponse.generatedSamples
                    gen_resp = response.get("generateVideoResponse", {})
                    samples = gen_resp.get("generatedSamples", []) or gen_resp.get("generated_videos", [])
                    if samples:
                        v0 = samples[0] if isinstance(samples[0], dict) else {}
                        vid_obj = v0.get("video", v0) if isinstance(v0.get("video"), dict) else v0
                        video_uri = (vid_obj or {}).get("uri", "")
                        video_b64 = (vid_obj or {}).get("bytesBase64Encoded", "")
                    # Путь 2: response.generated_videos
                    if not video_uri and not video_b64:
                        gv = response.get("generated_videos", response.get("generatedVideos", []))
                        if gv:
                            v0 = gv[0] if isinstance(gv[0], dict) else {}
                            video_uri = v0.get("uri", v0.get("video", {}).get("uri", "") if isinstance(v0.get("video"), dict) else "")
                            video_b64 = v0.get("bytesBase64Encoded", v0.get("video", {}).get("bytesBase64Encoded", "") if isinstance(v0.get("video"), dict) else "")
                    if video_b64:
                        import base64
                        try:
                            video_bytes = base64.b64decode(video_b64)
                            if len(video_bytes) > 1000:
                                return {"ok": True, "video_bytes": video_bytes}
                        except Exception as e:
                            log.warning("Veo base64 decode error", error=str(e))
                    if video_uri:
                        dl_url = f"{video_uri}&key={api_key}" if "?" in video_uri else f"{video_uri}?key={api_key}"
                        if video_uri.startswith("gs://"):
                            log.warning("Veo returned gs:// URI — Telegram не может загрузить, пробуем альтернативу", uri=video_uri[:80])
                            return {"ok": False, "error": "Видео сохранено в GCS. Попробуй модель без аудио (Veo 3.1) или другую модель."}
                        # Скачиваем и возвращаем байты — надёжнее для Telegram
                        try:
                            async with httpx.AsyncClient(timeout=120) as hc:
                                r = await hc.get(dl_url)
                                if r.status_code == 200 and len(r.content) > 1000:
                                    return {"ok": True, "video_bytes": r.content}
                        except Exception as e:
                            log.warning("Veo download error", error=str(e))
                        return {"ok": True, "video_url": dl_url}
                    log.warning("Veo unexpected response", keys=list(sd.keys()), resp_keys=list(response.keys()))
                    return {"ok": False, "error": "Видео сгенерировано, но не удалось извлечь файл"}

                error = sd.get("error")
                if error:
                    msg = error.get("message", str(error))[:200]
                    log.error("Veo generation error", error=msg)
                    return {"ok": False, "error": f"Ошибка генерации: {msg}"}

            return {"ok": False, "error": "Таймаут генерации видео (6 мин)"}

    except httpx.HTTPStatusError as e:
        log.error("Veo HTTP error", status=e.response.status_code)
        return {"ok": False, "error": f"Google Veo ошибка (HTTP {e.response.status_code})"}
    except Exception as e:
        log.error("Veo error", error=str(e))
        return {"ok": False, "error": f"Ошибка Google Veo: {str(e)[:100]}"}
