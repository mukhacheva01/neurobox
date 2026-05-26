"""НейроБокс — сервис генерации видео (вызов провайдеров без привязки к хендлеру)."""
import asyncio

import structlog

from shared.domain.credits import VIDEO_MODELS

log = structlog.get_logger()

DEFAULT_TIMEOUT = 400  # секунд


async def run_video_generation(
    prompt: str,
    model: str,
    image_base64: str | None = None,
    image_url: str | None = None,
    timeout_sec: int = DEFAULT_TIMEOUT,
) -> dict:
    """
    Запустить генерацию видео по промпту и модели.
    Возвращает {"ok": True, "video_url": "...", "video_bytes": b"..."} или {"ok": False, "error": "..."}.
    """
    info = VIDEO_MODELS.get(model)
    if not info:
        return {"ok": False, "error": "Модель не найдена"}

    endpoint = info.get("endpoint", "")

    async def _run():
        # Все видео → fal.ai (единый API)
        from shared.providers.falai_video import generate_video
        return await generate_video(prompt, endpoint, image_url=image_url)

    try:
        result = await asyncio.wait_for(_run(), timeout=timeout_sec)
        return result
    except asyncio.TimeoutError:
        log.warning("video generation timeout", model=model, user_prompt_len=len(prompt or ""))
        return {"ok": False, "error": "Превышено время ожидания генерации"}
    except Exception as e:
        log.exception("video_service run_video_generation error", model=model, error=str(e))
        return {"ok": False, "error": str(e)[:200]}
