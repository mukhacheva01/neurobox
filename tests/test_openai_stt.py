import asyncio
from types import SimpleNamespace


def test_extract_transcript_text_from_string():
    from shared.providers.openai_stt import _extract_transcript_text

    assert _extract_transcript_text("  привет  ") == "привет"


def test_extract_transcript_text_from_parts():
    from shared.providers.openai_stt import _extract_transcript_text

    content = [
        {"type": "text", "text": "первая строка"},
        {"type": "output_text", "text": "вторая строка"},
        {"type": "ignored", "text": "skip"},
    ]

    assert _extract_transcript_text(content) == "первая строка\nвторая строка"


def test_transcribe_audio_falls_back_to_next_model(monkeypatch):
    from shared.providers import openai_stt

    calls = []

    class FakeCompletions:
        async def create(self, **kwargs):
            calls.append(kwargs["model"])
            if len(calls) == 1:
                raise RuntimeError("No endpoints found that support input audio")
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="распознанный текст"))]
            )

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    monkeypatch.setattr(openai_stt, "_get_client", lambda: fake_client)

    out = asyncio.run(openai_stt.transcribe_audio(b"fake-bytes", "voice.ogg"))

    assert out["ok"] is True
    assert out["text"] == "распознанный текст"
    assert calls == list(openai_stt._STT_MODELS)
