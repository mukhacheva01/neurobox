"""НейроБокс — роутер музыкальных провайдеров."""

from shared.providers.falai_song import generate_song as _generate_song
from shared.providers.musicgen import generate_music as _generate_musicgen


async def generate_music(prompt: str, model: str = "musicgen", duration: int | None = None) -> dict:
    """Маршрутизирует генерацию музыки по выбранной модели."""
    model = (model or "musicgen").strip().lower()
    if model == "musicgen":
        return await _generate_musicgen(prompt, duration=duration or 15)
    if model == "suno-v4":
        # Пока используем song-capable fal.ai endpoint (конфигурируется через FAL_SONG_ENDPOINT).
        return await _generate_song(prompt, model=model, duration=duration or 30)
    return {"ok": False, "error": f"Модель музыки не поддерживается: {model}"}
