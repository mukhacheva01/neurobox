"""НейроБокс — Music generation via fal.ai."""
import asyncio

import httpx
import structlog

log = structlog.get_logger()

async def generate_music(prompt, duration=15):
    from shared.config import settings
    if not settings.falai_api_key:
        return {"ok": False, "error": "fal.ai API key not configured"}
    url = "https://queue.fal.run/fal-ai/stable-audio"
    headers = {"Authorization": f"Key {settings.falai_api_key}", "Content-Type": "application/json"}
    payload = {"prompt": prompt, "seconds_total": min(duration, 30), "steps": 100}
    try:
        async with httpx.AsyncClient(timeout=180) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            if "request_id" in data:
                rid = data["request_id"]
                base = "https://queue.fal.run/fal-ai/stable-audio/requests"
                for _ in range(90):
                    await asyncio.sleep(2)
                    sr = await client.get(f"{base}/{rid}/status", headers=headers)
                    sd = sr.json()
                    if sd.get("status") == "COMPLETED":
                        rr = await client.get(f"{base}/{rid}", headers=headers)
                        data = rr.json()
                        break
                    elif sd.get("status") in ("FAILED", "CANCELLED"):
                        return {"ok": False, "error": "Генерация не удалась"}
                else:
                    return {"ok": False, "error": "Таймаут генерации"}
            audio_url = (data.get("audio_file") or data.get("audio") or {}).get("url", "")
            if not audio_url:
                return {"ok": False, "error": "Аудио не сгенерировано"}
            return {"ok": True, "audio_url": audio_url}
    except httpx.HTTPStatusError as e:
        log.error("MusicGen HTTP error", status=e.response.status_code)
        return {"ok": False, "error": f"Ошибка (HTTP {e.response.status_code})"}
    except Exception as e:
        log.error("MusicGen error", error=str(e))
        return {"ok": False, "error": "Ошибка генерации музыки"}
