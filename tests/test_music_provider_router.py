import asyncio


def test_music_router_routes_musicgen(monkeypatch):
    from shared.providers import music_router

    calls = []

    async def fake_musicgen(prompt, duration=15):
        calls.append(("musicgen", prompt, duration))
        return {"ok": True, "audio_url": "https://example.test/a.mp3"}

    async def fake_song(prompt, model="suno-v4", duration=30):
        calls.append(("song", prompt, model, duration))
        return {"ok": True, "audio_url": "https://example.test/b.mp3"}

    monkeypatch.setattr(music_router, "_generate_musicgen", fake_musicgen)
    monkeypatch.setattr(music_router, "_generate_song", fake_song)

    out = asyncio.run(music_router.generate_music("beat", model="musicgen"))
    assert out["ok"] is True
    assert calls == [("musicgen", "beat", 15)]


def test_music_router_routes_song_model(monkeypatch):
    from shared.providers import music_router

    calls = []

    async def fake_musicgen(prompt, duration=15):
        calls.append(("musicgen", prompt, duration))
        return {"ok": True}

    async def fake_song(prompt, model="suno-v4", duration=30):
        calls.append(("song", prompt, model, duration))
        return {"ok": True, "audio_url": "https://example.test/song.mp3"}

    monkeypatch.setattr(music_router, "_generate_musicgen", fake_musicgen)
    monkeypatch.setattr(music_router, "_generate_song", fake_song)

    out = asyncio.run(music_router.generate_music("куплет припев", model="suno-v4"))
    assert out["ok"] is True
    assert calls == [("song", "куплет припев", "suno-v4", 30)]


def test_music_router_rejects_unknown_model():
    from shared.providers import music_router

    out = asyncio.run(music_router.generate_music("x", model="unknown-model"))
    assert out["ok"] is False
    assert "не поддерживается" in out["error"]
