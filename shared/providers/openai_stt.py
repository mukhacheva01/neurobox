"""STT через OpenRouter с fallback по аудио-моделям."""

import base64
import os
import subprocess
import tempfile
from typing import Any

import structlog

log = structlog.get_logger()

# Audio-capable OpenRouter models ordered by price/performance.
_STT_MODELS = (
    "google/gemini-3.1-flash-lite-preview",
    "google/gemini-2.0-flash-001",
)

_TEXT_PROMPT = (
    "Транскрибируй эту аудиозапись. "
    "Верни только распознанный текст, без пояснений. "
    "Если речь на русском, пиши на русском."
)

_DIRECT_AUDIO_FORMATS = {
    "ogg": "ogg",
    "oga": "ogg",
    "mp3": "mp3",
    "wav": "wav",
    "m4a": "m4a",
    "aac": "aac",
    "flac": "flac",
    "webm": "webm",
}

_TRANSCODE_EXTENSIONS = {
    "mp4",
    "m4v",
    "mov",
    "mkv",
    "avi",
}


def _get_client():
    from shared.providers.openai_text import _get_openrouter_client

    return _get_openrouter_client()


def _guess_extension(filename: str) -> str:
    name = (filename or "").rsplit("/", 1)[-1]
    if "." not in name:
        return "ogg"
    return name.rsplit(".", 1)[-1].lower()


def _extract_transcript_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()

    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                item_type = item.get("type")
                text = item.get("text")
            else:
                item_type = getattr(item, "type", None)
                text = getattr(item, "text", None)
            if item_type in {"text", "output_text"} and text:
                parts.append(str(text).strip())
        return "\n".join(part for part in parts if part).strip()

    return str(content or "").strip()


def _transcode_to_wav(file_bytes: bytes, input_ext: str) -> tuple[bytes, str]:
    with tempfile.NamedTemporaryFile(suffix=f'.{input_ext or "bin"}', delete=False) as src:
        src.write(file_bytes)
        src_path = src.name
    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as dst:
        dst_path = dst.name

    try:
        proc = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                src_path,
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                dst_path,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            stderr = (proc.stderr or "").strip()
            raise RuntimeError(stderr[:200] or "ffmpeg failed")
        with open(dst_path, "rb") as fh:
            return fh.read(), "wav"
    finally:
        for path in (src_path, dst_path):
            try:
                os.remove(path)
            except OSError:
                pass


def _prepare_audio_payload(file_bytes: bytes, filename: str) -> tuple[bytes, str]:
    ext = _guess_extension(filename)
    if ext in _DIRECT_AUDIO_FORMATS:
        return file_bytes, _DIRECT_AUDIO_FORMATS[ext]
    if ext in _TRANSCODE_EXTENSIONS:
        return _transcode_to_wav(file_bytes, ext)
    return _transcode_to_wav(file_bytes, ext)


async def transcribe_audio(file_bytes: bytes, filename: str = "voice.ogg") -> dict[str, Any]:
    """Распознать речь через OpenRouter audio input."""
    client = _get_client()
    prepared_bytes, audio_format = _prepare_audio_payload(file_bytes, filename)
    b64_audio = base64.b64encode(prepared_bytes).decode("utf-8")

    last_error = ""
    for model in _STT_MODELS:
        try:
            response = await client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_audio",
                                "input_audio": {
                                    "data": b64_audio,
                                    "format": audio_format,
                                },
                            },
                            {
                                "type": "text",
                                "text": _TEXT_PROMPT,
                            },
                        ],
                    }
                ],
                max_tokens=1024,
            )
            text = _extract_transcript_text(response.choices[0].message.content)
            if not text:
                return {"ok": False, "error": "Не удалось распознать речь"}
            log.info("stt_openrouter_ok", chars=len(text), model=model, format=audio_format)
            return {"ok": True, "text": text, "model": model}
        except Exception as exc:
            last_error = str(exc)
            log.warning("stt_openrouter_model_failed", model=model, error=last_error[:200])

    log.error("stt_openrouter_error", error=last_error[:200], format=audio_format)
    return {"ok": False, "error": f"Ошибка распознавания: {last_error[:100]}"}
