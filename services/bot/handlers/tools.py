"""НейроБокс — /search, /summary, /code (поиск, резюме URL, AI-разбор кода)."""

from __future__ import annotations

import re

import httpx
from aiogram import Router, types
from aiogram.filters import Command

from services.bot.utils.paywall import smart_paywall_message
from shared.config import settings
from shared.domain.credits import (
    get_or_create_user,
    refund_spend_credits,
    spend_credits,
)
from shared.providers.openai_text import generate_text

router = Router()

SEARCH_CR = 2
SUMMARY_CR = 2
CODE_CR = 2


def _arg_from_command(text: str) -> str:
    parts = (text or "").split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


async def _search_serper(query: str, api_key: str) -> str:
    """Поиск через Serper (Google). Возвращает текст для контекста AI."""
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            json={"q": query, "num": 8},
        )
        if r.status_code != 200:
            return ""
        data = r.json()

    snippets = []
    for o in data.get("organic", [])[:8]:
        title = (o.get("title") or "").strip()
        snippet = (o.get("snippet") or "").strip()
        link = (o.get("link") or "").strip()
        snippets.append(f"[{title}]\n{snippet}\n{link}")
    return "\n\n".join(snippets)


def _strip_html(raw: str) -> str:
    text = re.sub(r"<script[\\s\\S]*?</script>", " ", raw, flags=re.IGNORECASE)
    text = re.sub(r"<style[\\s\\S]*?</style>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\\s+", " ", text)
    return text.strip()


@router.message(Command("search"))
async def cmd_search(message: types.Message):
    user_id = message.from_user.id
    await get_or_create_user(user_id, message.from_user.username, message.from_user.first_name)

    if not (settings.serper_api_key or "").strip():
        await message.answer("❌ Веб-поиск временно недоступен. Используй /summary или /code.")
        return

    query = _arg_from_command(message.text or "")
    if not query:
        await message.answer("🔎 Пример: <code>/search лучшие ноутбуки 2026</code>")
        return

    spend = await spend_credits(user_id, "gpt-5-nano", f"search: {query[:50]}", cost_override=SEARCH_CR)
    if not spend.get("ok"):
        if spend.get("message"):
            await message.answer(spend["message"])
            return
        text, kb = await smart_paywall_message("Веб-поиск", SEARCH_CR, user_id)
        await message.answer(text, reply_markup=kb)
        return

    status = await message.answer("🔎 Ищу в интернете...")
    snippets = await _search_serper(query, settings.serper_api_key)
    if not snippets:
        await refund_spend_credits(user_id, spend, "search без результата")
        await status.edit_text("❌ Не удалось получить результаты поиска.\n\n💚 Кредиты возвращены.")
        return

    prompt = (
        "Ниже результаты веб-поиска. Составь краткий, практичный ответ на запрос пользователя. "
        "Структурируй по пунктам и добавь блок 'Источники' со ссылками.\n\n"
        f"Запрос: {query}\n\nРезультаты:\n{snippets[:12000]}"
    )
    result = await generate_text(prompt, "gpt-5-nano", history=None)
    if not result.get("ok"):
        await refund_spend_credits(user_id, spend, "ошибка search")
        await status.edit_text(f"❌ {result.get('error', 'Ошибка')}\n\n💚 Кредиты возвращены.")
        return

    remaining = spend.get("bought", 0) + spend.get("free", 0)
    await status.edit_text(
        f"🔎 <b>Результаты поиска</b>\n\n{result['text'][:3800]}\n\n"
        f"<i>−{SEARCH_CR} CR | Остаток: {remaining} CR</i>"
    )


@router.message(Command("summary"))
async def cmd_summary(message: types.Message):
    user_id = message.from_user.id
    await get_or_create_user(user_id, message.from_user.username, message.from_user.first_name)

    url = _arg_from_command(message.text or "")
    if not url or not re.match(r"^https?://", url, flags=re.IGNORECASE):
        await message.answer("📰 Пример: <code>/summary https://example.com/article</code>")
        return

    spend = await spend_credits(user_id, "gpt-5-nano", f"summary: {url[:80]}", cost_override=SUMMARY_CR)
    if not spend.get("ok"):
        if spend.get("message"):
            await message.answer(spend["message"])
            return
        text, kb = await smart_paywall_message("Резюме статьи", SUMMARY_CR, user_id)
        await message.answer(text, reply_markup=kb)
        return

    status = await message.answer("📰 Читаю страницу...")
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            resp = await client.get(
                url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; NeuroBoxBot/1.0)"},
            )
        if resp.status_code >= 400:
            raise RuntimeError(f"HTTP {resp.status_code}")
        article_text = _strip_html(resp.text)
    except Exception:
        await refund_spend_credits(user_id, spend, "ошибка загрузки URL")
        await status.edit_text("❌ Не удалось загрузить страницу.\n\n💚 Кредиты возвращены.")
        return

    if len(article_text) < 200:
        await refund_spend_credits(user_id, spend, "слишком мало текста")
        await status.edit_text("❌ На странице слишком мало текста для резюме.\n\n💚 Кредиты возвращены.")
        return

    prompt = (
        "Сделай сжатое резюме статьи на русском: 5-8 ключевых тезисов, затем блок 'Практическая польза'. "
        "Без воды и длинного вступления.\n\n"
        f"URL: {url}\n\nТекст:\n{article_text[:15000]}"
    )
    result = await generate_text(prompt, "gpt-5-nano", history=None)
    if not result.get("ok"):
        await refund_spend_credits(user_id, spend, "ошибка summary")
        await status.edit_text(f"❌ {result.get('error', 'Ошибка')}\n\n💚 Кредиты возвращены.")
        return

    remaining = spend.get("bought", 0) + spend.get("free", 0)
    await status.edit_text(
        f"📰 <b>Резюме статьи</b>\n\n{result['text'][:3800]}\n\n"
        f"<i>−{SUMMARY_CR} CR | Остаток: {remaining} CR</i>"
    )


@router.message(Command("code"))
async def cmd_code(message: types.Message):
    user_id = message.from_user.id
    await get_or_create_user(user_id, message.from_user.username, message.from_user.first_name)

    code_text = _arg_from_command(message.text or "")
    if not code_text:
        await message.answer(
            "💻 Пример: <code>/code for i in range(3): print(i)</code>\n"
            "Я разберу код, укажу ошибки и предложу улучшение."
        )
        return

    spend = await spend_credits(user_id, "gpt-5-nano", "code review", cost_override=CODE_CR)
    if not spend.get("ok"):
        if spend.get("message"):
            await message.answer(spend["message"])
            return
        text, kb = await smart_paywall_message("Разбор кода", CODE_CR, user_id)
        await message.answer(text, reply_markup=kb)
        return

    status = await message.answer("💻 Анализирую код...")
    prompt = (
        "Проанализируй код. Ответ структурируй так: 1) Что делает код, 2) Возможные ошибки, "
        "3) Как улучшить, 4) Исправленный вариант.\n\n"
        f"Код:\n```\n{code_text[:8000]}\n```"
    )
    result = await generate_text(prompt, "gpt-5-nano", history=None)
    if not result.get("ok"):
        await refund_spend_credits(user_id, spend, "ошибка code")
        await status.edit_text(f"❌ {result.get('error', 'Ошибка')}\n\n💚 Кредиты возвращены.")
        return

    remaining = spend.get("bought", 0) + spend.get("free", 0)
    await status.edit_text(
        f"💻 <b>Разбор кода</b>\n\n{result['text'][:3800]}\n\n"
        f"<i>−{CODE_CR} CR | Остаток: {remaining} CR</i>"
    )
