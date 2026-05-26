"""НейроБокс — Edge TTS (free)."""
import os
import tempfile

import edge_tts
import structlog

log = structlog.get_logger()

async def generate_speech(text, voice_id="ru-RU-SvetlanaNeural"):
    if len(text) > 3000:
        text = text[:3000]
    tmp_path = None
    try:
        comm = edge_tts.Communicate(text, voice_id)
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            tmp_path = f.name
        await comm.save(tmp_path)
        with open(tmp_path, "rb") as f:
            audio_bytes = f.read()
        return {"ok": True, "audio_bytes": audio_bytes, "format": "mp3"}
    except Exception as e:
        log.error("Edge TTS error", error=str(e))
        return {"ok": False, "error": f"Ошибка синтеза: {str(e)[:100]}"}
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)
