#!/usr/bin/env python3
"""
НейроБокс — проверка внешних API и платёжных интеграций.
OpenRouter — основной текстовый контур. OpenAI direct — только optional-путь
для TTS/аудио, если такие фичи включены.
"""
import asyncio
import base64
import os


def load_env():
    for d in [os.getcwd(), "/opt/neurobox", os.path.dirname(os.path.abspath(__file__))]:
        env_path = os.path.join(d, ".env")
        if os.path.isfile(env_path):
            with open(env_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, _, v = line.partition("=")
                        k, v = k.strip(), v.strip().strip('"').strip("'")
                        os.environ.setdefault(k, v)
            return env_path
    return None


load_env()

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
FALAI_API_KEY = os.environ.get("FALAI_API_KEY", "")
SERPER_API_KEY = os.environ.get("SERPER_API_KEY", "")
YOOKASSA_SHOP_ID = os.environ.get("YOOKASSA_SHOP_ID", "")
YOOKASSA_SECRET_KEY = os.environ.get("YOOKASSA_SECRET_KEY", "")
CRYPTOBOT_API_TOKEN = os.environ.get("CRYPTOBOT_API_TOKEN", "")
ENABLE_TTS = os.environ.get("ENABLE_TTS", "false").strip().lower() in {"1", "true", "yes", "on"}


async def check_openrouter():
    if not OPENROUTER_API_KEY:
        return "OPENROUTER_API_KEY не задан"
    try:
        import openai

        client = openai.AsyncOpenAI(
            api_key=OPENROUTER_API_KEY,
            base_url="https://openrouter.ai/api/v1",
            default_headers={
                "HTTP-Referer": "https://t.me/ai_b0x_bot",
                "X-Title": "NeuroBox API Check",
            },
        )
        last_error = ""
        for model in ["openai/gpt-5-nano", "google/gemini-2.0-flash-001"]:
            try:
                r = await client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": "Say OK"}],
                    max_tokens=8,
                )
                text = (r.choices[0].message.content or "").strip()
                return f"OK ({model}): {text[:50]}"
            except Exception as e:
                last_error = str(e)
        return f"Ошибка: {last_error or 'ни одна модель OpenRouter не ответила'}"
    except Exception as e:
        return f"Ошибка: {e}"


async def check_openai_optional():
    if not OPENAI_API_KEY:
        suffix = " (не нужен для текста)"
        if ENABLE_TTS:
            suffix = " (но понадобится для direct TTS, если используешь OpenAI TTS)"
        return f"не задан{suffix}"
    try:
        import openai

        client = openai.AsyncOpenAI(api_key=OPENAI_API_KEY)
        r = await client.chat.completions.create(
            model="gpt-4.1-nano",
            messages=[{"role": "user", "content": "Say OK"}],
            max_tokens=8,
        )
        text = (r.choices[0].message.content or "").strip()
        return f"OK: {text[:50]}"
    except Exception as e:
        return f"Ошибка: {e}"


async def check_falai():
    if not FALAI_API_KEY:
        return "FALAI_API_KEY не задан"
    try:
        import httpx

        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                "https://api.fal.ai/v1/models",
                headers={"Authorization": f"Key {FALAI_API_KEY}"},
                params={"limit": 1},
            )
        if r.status_code == 401:
            return "Ошибка: неверный ключ (401)"
        if r.status_code != 200:
            return f"Ошибка: HTTP {r.status_code}"
        return "OK"
    except Exception as e:
        return f"Ошибка: {e}"


async def check_serper():
    if not SERPER_API_KEY:
        return "SERPER_API_KEY не задан"
    try:
        import httpx

        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                "https://google.serper.dev/search",
                headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"},
                json={"q": "test", "num": 1},
            )
        if r.status_code == 401:
            return "Ошибка: неверный ключ (401)"
        if r.status_code != 200:
            return f"Ошибка: HTTP {r.status_code}"
        data = r.json()
        if "organic" in data or "searchInformation" in data:
            return "OK"
        return "Ошибка: неожиданный ответ"
    except Exception as e:
        return f"Ошибка: {e}"


async def check_yookassa():
    if not YOOKASSA_SHOP_ID or not YOOKASSA_SECRET_KEY:
        return "не настроен (YOOKASSA_SHOP_ID / YOOKASSA_SECRET_KEY)"
    try:
        import httpx

        raw = f"{YOOKASSA_SHOP_ID}:{YOOKASSA_SECRET_KEY}"
        auth = "Basic " + base64.b64encode(raw.encode()).decode()
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                "https://api.yookassa.ru/v3/payments?limit=1",
                headers={"Authorization": auth},
            )
        if r.status_code in (200, 201):
            return "OK (ключи валидны)"
        try:
            data = r.json()
            desc = data.get("description") or data.get("code") or r.text[:200]
        except Exception:
            desc = r.text[:200] or f"HTTP {r.status_code}"
        return f"Ошибка: {desc}"
    except Exception as e:
        return f"Ошибка: {e}"


async def check_cryptobot_api():
    if not CRYPTOBOT_API_TOKEN:
        return "CRYPTOBOT_API_TOKEN не задан"
    try:
        import httpx

        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                "https://pay.crypt.bot/api/getMe",
                headers={"Crypto-Pay-API-Token": CRYPTOBOT_API_TOKEN},
            )
        data = r.json()
        if data.get("ok") and data.get("result"):
            return "OK"
        return f"Ошибка: {data.get('error', {}).get('name', r.status_code)}"
    except Exception as e:
        return f"Ошибка: {e}"


async def main():
    print("НейроБокс — проверка API и платежей\n" + "=" * 50)
    checks = [
        ("OpenRouter (text core)", check_openrouter),
        ("OpenAI direct (optional)", check_openai_optional),
        ("fal.ai (media)", check_falai),
        ("Serper (web search)", check_serper),
        ("CryptoBot", check_cryptobot_api),
    ]
    for name, coro in checks:
        try:
            result = await coro()
            status = "✓" if result.startswith("OK") else "✗"
            print(f"{status} {name}: {result}")
        except Exception as e:
            print(f"✗ {name}: {e}")
    try:
        yoo_res = await check_yookassa()
        yoo_ok = "✓" if yoo_res.startswith("OK") else "✗"
        print(f"{yoo_ok} ЮKassa: {yoo_res}")
    except Exception as e:
        print(f"✗ ЮKassa: {e}")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())
