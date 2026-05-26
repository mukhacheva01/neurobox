"""НейроБокс — fal.ai provider для генерации песен (lyrics/song)."""

import asyncio

import httpx
import structlog

log = structlog.get_logger()

DEFAULT_SONG_ENDPOINT = "fal-ai/diffrhythm"


def _resolve_song_endpoint(model: str) -> str:
    from shared.config import settings

    override = (getattr(settings, "fal_song_endpoint", "") or "").strip()
    if override:
        return override
    return DEFAULT_SONG_ENDPOINT


def _payload_candidates(prompt: str, endpoint: str, duration: int) -> list[dict]:
    prompt = (prompt or "").strip()[:2000]
    duration = max(10, min(int(duration or 30), 180))
    base_prompt = {"prompt": prompt}
    base_lyrics = {"lyrics": prompt}

    if any(x in endpoint for x in ("minimax", "ace-step", "elevenlabs", "sonauto")):
        return [
            {**base_prompt, "duration": duration},
            {**base_lyrics, "duration": duration},
            base_prompt,
            base_lyrics,
        ]

    return [base_prompt, base_lyrics]


def _looks_like_audio_url(url: str) -> bool:
    u = (url or "").lower()
    return any(x in u for x in (".mp3", ".wav", ".m4a", ".ogg", ".flac", "/audio", "fal.media"))


def _find_audio_url(obj) -> str:
    if isinstance(obj, dict):
        val = obj.get("audio_url")
        if isinstance(val, str) and val:
            return val
        for key in ("audio", "audio_file", "music", "song", "output", "result", "data"):
            url = _find_audio_url(obj.get(key))
            if url:
                return url
        val = obj.get("url")
        if isinstance(val, str) and _looks_like_audio_url(val):
            return val
        for v in obj.values():
            url = _find_audio_url(v)
            if url:
                return url
        return ""
    if isinstance(obj, list):
        for item in obj:
            url = _find_audio_url(item)
            if url:
                return url
        return ""
    if isinstance(obj, str) and _looks_like_audio_url(obj):
        return obj
    return ""


def _extract_error_message(data: dict) -> str:
    if not isinstance(data, dict):
        return ""
    for key in ("error", "detail", "message"):
        val = data.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    err = data.get("error")
    if isinstance(err, dict):
        for key in ("message", "detail"):
            val = err.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
    return ""


async def generate_song(prompt: str, model: str = "suno-v4", duration: int = 30) -> dict:
    from shared.config import settings

    if not settings.falai_api_key:
        return {"ok": False, "error": "fal.ai API key не настроен"}

    endpoint = _resolve_song_endpoint(model)
    url = f"https://queue.fal.run/{endpoint}"
    headers = {
        "Authorization": f"Key {settings.falai_api_key}",
        "Content-Type": "application/json",
    }

    timeout_sec = int(getattr(settings, "fal_song_timeout_sec", 420) or 420)
    poll_sleep = 3
    submit_error = ""
    data = None

    try:
        async with httpx.AsyncClient(timeout=timeout_sec) as client:
            for payload in _payload_candidates(prompt, endpoint, duration):
                try:
                    resp = await client.post(url, json=payload, headers=headers)
                    resp.raise_for_status()
                    data = resp.json()
                    break
                except httpx.HTTPStatusError as e:
                    status = e.response.status_code if e.response else 0
                    body = (e.response.text if e.response else "")[:500]
                    submit_error = body or f"HTTP {status}"
                    if status in (400, 422):
                        continue
                    if status == 401:
                        log.error("fal.ai song unauthorized", endpoint=endpoint, body=body)
                        return {"ok": False, "error": "fal.ai отклонил ключ (HTTP 401). Проверь FALAI_API_KEY."}
                    if status == 403:
                        log.error("fal.ai song forbidden", endpoint=endpoint, body=body)
                        return {"ok": False, "error": "fal.ai отказал в доступе (HTTP 403). Проверь баланс/доступ к модели."}
                    log.error("fal.ai song submit HTTP error", endpoint=endpoint, status=status, body=body)
                    return {"ok": False, "error": f"Ошибка API (HTTP {status})"}

            if data is None:
                msg = submit_error or "fal.ai endpoint не принял payload (prompt/lyrics)"
                log.error("fal.ai song payload rejected", endpoint=endpoint, error=msg)
                return {"ok": False, "error": "Песенная модель временно недоступна (payload schema mismatch). Нужна настройка endpoint."}

            if "request_id" in data:
                rid = data["request_id"]
                base = f"https://queue.fal.run/{endpoint}/requests"
                polls = max(1, timeout_sec // poll_sleep)
                for _ in range(polls):
                    await asyncio.sleep(poll_sleep)
                    try:
                        sr = await client.get(f"{base}/{rid}/status", headers=headers)
                        sr.raise_for_status()
                        sd = sr.json()
                    except Exception as poll_err:
                        log.warning("fal.ai song poll error", endpoint=endpoint, error=str(poll_err))
                        continue

                    status = str(sd.get("status", "")).upper()
                    if status == "COMPLETED":
                        rr = await client.get(f"{base}/{rid}", headers=headers)
                        rr.raise_for_status()
                        data = rr.json()
                        break
                    if status in {"FAILED", "CANCELLED"}:
                        err = _extract_error_message(sd) or "Генерация песни не удалась"
                        return {"ok": False, "error": err[:200]}
                else:
                    return {"ok": False, "error": "Таймаут генерации песни"}

            audio_url = _find_audio_url(data)
            if not audio_url:
                keys = list(data.keys()) if isinstance(data, dict) else []
                log.warning("fal.ai song no audio URL", endpoint=endpoint, keys=keys)
                return {"ok": False, "error": "Песня не найдена в ответе модели"}

            return {"ok": True, "audio_url": audio_url, "endpoint": endpoint}

    except httpx.HTTPStatusError as e:
        status = e.response.status_code if e.response else 0
        body = (e.response.text if e.response else "")[:500]
        log.error("fal.ai song HTTP error", endpoint=endpoint, status=status, body=body)
        if status == 401:
            return {"ok": False, "error": "fal.ai отклонил ключ (HTTP 401). Проверь FALAI_API_KEY."}
        return {"ok": False, "error": f"Ошибка API (HTTP {status})"}
    except Exception as e:
        log.error("fal.ai song error", endpoint=endpoint, error=str(e))
        return {"ok": False, "error": "Ошибка генерации песни"}
