"""Пользовательские команды в личке с ботом: промокоды и реферальная ссылка."""
import html

from aiogram import Bot, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from . import config, db
from .registry import TIERS

router = Router()


@router.message(Command("promo", "activate"))
async def promo(m: Message, command: CommandObject):
    uid = m.from_user.id
    if uid in db.BANNED:
        return await m.answer("⛔ Вы заблокированы администратором.")
    code = (command.args or "").strip().upper()
    if not code:
        return await m.answer("Введите промокод: <code>/promo КОД</code>")
    row = await db.fetchone("SELECT * FROM promos WHERE code=?", (code,))
    if not row or row["uses_left"] <= 0:
        return await m.answer("❌ Промокод не найден или закончился")
    if await db.fetchone("SELECT 1 FROM promo_used WHERE code=? AND user_id=?", (code, uid)):
        return await m.answer("Вы уже активировали этот промокод")
    await db.execute("INSERT INTO promo_used VALUES(?,?)", (code, uid))
    await db.execute("UPDATE promos SET uses_left = uses_left - 1 WHERE code=?", (code,))
    await db.apply_sub(uid, row["tier"], row["days"])
    await m.answer(f"🎉 Промокод активирован: <b>{TIERS[row['tier']]}</b> на {row['days']} дн.!")


@router.message(Command("ref", "invite"))
async def ref(m: Message, bot: Bot):
    uid = m.from_user.id
    me = await bot.me()
    n = (await db.fetchone("SELECT COUNT(*) c FROM settings WHERE key='ref' AND value=?", (str(uid),)))["c"]
    await m.answer(
        f"👥 <b>Пригласи друга</b>\nЗа каждого друга, который подключит бота, вы получаете +{config.REF_DAYS} дн. PREMIUM.\n\n"
        f"Ваша ссылка:\n<code>https://t.me/{me.username}?start=ref_{uid}</code>\n\nПриглашено (перешли по ссылке): {n}"
    )
