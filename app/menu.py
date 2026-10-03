import html
import logging
import time
from datetime import datetime

from aiogram import F, Bot, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice, Message, PreCheckoutQuery,
)

from . import config, db
from .registry import CMDS, SECTIONS, TIERS, section_text

log = logging.getLogger(__name__)
router = Router()

HOME = (
    "<b>Добро пожаловать в ассистента 👀</b>\n\n"
    "Максимум возможностей — минимум лишних действий ✨\n"
    "<blockquote>Бот работает через Telegram Business: подключите его к аккаунту и пишите команды с точки "
    "в любом личном чате — анимации, игры, медиа, модерация и многое другое.</blockquote>\n"
    "Используйте кнопки ниже для навигации по разделам 🤔"
)
CONNECT = (
    "🔌 <b>Подключение</b>\n\n"
    "1. Нужен Telegram Premium.\n"
    "2. Настройки → <b>Telegram для бизнеса</b> → <b>Чат-боты</b>.\n"
    "3. Укажите этого бота и выдайте права: отвечать на сообщения, <b>удалять сообщения</b> (для модерации и .panic), "
    "читать сообщения, менять имя профиля (для .timeprofile).\n"
    "4. Напишите в любом личном чате <code>.help</code>."
)
TIER_TEXT = {
    1: "✨ Анимации (.print .glit .love …)\n🎞 Медиа (.sticker .round .removebg .voice …)\n🎲 .xaxa .bomb",
    2: "Всё из PREMIUM +\n🛡 Модерация (.mute .antimat .antispam …)\n👤 Профиль и авто (.panic .autoread .timeprofile …)",
}


def _btn(text, data):
    return InlineKeyboardButton(text=text, callback_data=data)


def home_kb() -> InlineKeyboardMarkup:
    secs = [(sid, v) for sid, v in SECTIONS.items() if any(c.section == sid for c in CMDS)]
    btns = [_btn(f"{icon} {title}", f"m:{sid}") for sid, (icon, title) in secs]
    rows = [btns[i:i + 2] for i in range(0, len(btns), 2)]
    rows.append([_btn("🔌 Подключение", "m:connect")])
    rows.append([_btn("⭐ PREMIUM", "buy:1"), _btn("👑 VIP", "buy:2")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def back_kb(extra=None) -> InlineKeyboardMarkup:
    rows = [extra] if extra else []
    rows.append([_btn("⬅️ В меню", "m:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def price(tier):
    return config.PREMIUM_STARS if tier == 1 else config.VIP_STARS


async def sub_line(uid) -> str:
    t = await db.get_tier(uid)
    if uid == config.ADMIN_ID:
        return "Ваш тариф: <b>VIP</b> (админ)"
    row = await db.get_sub(uid)
    if t and row:
        return f"Ваш тариф: <b>{TIERS[t]}</b> до {datetime.fromtimestamp(row['until'], config.MSK):%d.%m.%Y}"
    return "Ваш тариф: <b>FREE</b>"


async def sub_text(uid) -> str:
    return (
        f"💳 <b>Тарифы</b>\n{await sub_line(uid)}\n\n"
        f"⭐ <b>PREMIUM</b> — {config.PREMIUM_STARS}⭐ / {config.SUB_DAYS} дн.\n{TIER_TEXT[1]}\n\n"
        f"👑 <b>VIP</b> — {config.VIP_STARS}⭐ / {config.SUB_DAYS} дн.\n{TIER_TEXT[2]}"
    )


def sub_kb():
    return back_kb([_btn(f"⭐ PREMIUM · {config.PREMIUM_STARS}⭐", "pay:1"), _btn(f"👑 VIP · {config.VIP_STARS}⭐", "pay:2")])


@router.message(CommandStart())
@router.message(Command("menu", "help"))
async def start(m: Message):
    await m.answer(HOME + f"\n\n{await sub_line(m.from_user.id)}", reply_markup=home_kb())


@router.callback_query(F.data.startswith("m:"))
async def on_menu(cb: CallbackQuery):
    key = cb.data[2:]
    kb = back_kb()
    if key == "home":
        text, kb = HOME + f"\n\n{await sub_line(cb.from_user.id)}", home_kb()
    elif key == "connect":
        text = CONNECT
    elif key in SECTIONS:
        text = section_text(key)
    else:
        return await cb.answer()
    try:
        await cb.message.edit_text(text, reply_markup=kb)
    except TelegramBadRequest:
        pass
    await cb.answer()


@router.callback_query(F.data.startswith("buy:"))
async def on_buy_page(cb: CallbackQuery):
    try:
        await cb.message.edit_text(await sub_text(cb.from_user.id), reply_markup=sub_kb())
    except TelegramBadRequest:
        pass
    await cb.answer()


@router.callback_query(F.data.startswith("pay:"))
async def on_pay(cb: CallbackQuery):
    tier = int(cb.data[4:])
    await cb.message.answer_invoice(
        title=f"{TIERS[tier]} на {config.SUB_DAYS} дн.",
        description=TIER_TEXT[tier].replace("\n", ", "),
        payload=f"sub:{tier}",
        currency="XTR",
        prices=[LabeledPrice(label=TIERS[tier], amount=price(tier))],
    )
    await cb.answer()


@router.pre_checkout_query()
async def pre_checkout(q: PreCheckoutQuery):
    await q.answer(ok=True)


@router.message(F.successful_payment)
async def paid(m: Message):
    p = m.successful_payment
    tier = int(p.invoice_payload.split(":")[1])
    await db.grant(m.from_user.id, tier, config.SUB_DAYS)
    log.info("оплата: user=%s tier=%s charge=%s", m.from_user.id, tier, p.telegram_payment_charge_id)
    await m.answer(f"🎉 Тариф <b>{TIERS[tier]}</b> активирован на {config.SUB_DAYS} дн.!\n{await sub_line(m.from_user.id)}")


# ---------- админка ----------
def _admin(m: Message) -> bool:
    return bool(m.from_user and m.from_user.id == config.ADMIN_ID)


def _tier_arg(s: str):
    return {"0": 0, "free": 0, "1": 1, "premium": 1, "prem": 1, "2": 2, "vip": 2}.get(s.lower())


def _target(m: Message, a: list):
    """user_id из аргумента, из пересланного сообщения или из ответа на него."""
    if a and a[0].isdigit() and len(a[0]) > 5:
        return int(a[0]), a[1:]
    r = m.reply_to_message
    if r:
        fo = getattr(r, "forward_origin", None)
        u = getattr(fo, "sender_user", None) or (r.from_user if r.from_user and r.from_user.id != config.ADMIN_ID else None)
        if u:
            return u.id, a
    return None, a


@router.message(Command("give", "gift"))
async def give(m: Message, bot: Bot):
    if not _admin(m):
        return
    uid, a = _target(m, (m.text or "").split()[1:])
    if uid is None or not a or _tier_arg(a[0]) is None:
        return await m.answer("Формат: <code>/give user_id premium|vip [дней]</code>\nили ответом на пересланное сообщение человека: <code>/give vip 30</code>")
    tier = _tier_arg(a[0])
    days = int(a[1]) if len(a) > 1 and a[1].isdigit() else config.SUB_DAYS
    await db.grant(uid, tier, days)
    await m.answer(f"✅ {uid}: {TIERS[tier]} на {days} дн.")
    try:
        await bot.send_message(uid, f"🎁 Вам выдан тариф <b>{TIERS[tier]}</b> на {days} дн.")
    except Exception:
        pass


@router.message(Command("revoke"))
async def revoke(m: Message):
    if not _admin(m):
        return
    uid, _ = _target(m, (m.text or "").split()[1:])
    if uid is None:
        return await m.answer("Формат: <code>/revoke user_id</code> или ответом на пересланное сообщение")
    await db.revoke(uid)
    await m.answer("✅ Подписка снята")


async def _subs_text() -> str:
    rows = await db.fetchall("SELECT * FROM subs WHERE until > ? ORDER BY until DESC", (time.time(),))
    if not rows:
        return "Активных подписок нет"
    return "<b>Подписки</b>\n" + "\n".join(
        f"<code>{r['user_id']}</code> — {TIERS[r['tier']]} до {datetime.fromtimestamp(r['until'], config.MSK):%d.%m.%Y}" for r in rows[:50]
    )


async def _stats_text() -> str:
    users = (await db.fetchone("SELECT COUNT(DISTINCT user_id) c FROM connections"))["c"]
    active = (await db.fetchone("SELECT COUNT(*) c FROM subs WHERE until > ?", (time.time(),)))["c"]
    msgs = (await db.fetchone("SELECT COUNT(*) c FROM msgs"))["c"]
    return f"📊 Подключённых аккаунтов: {users}\nАктивных подписок: {active}\nСообщений в журнале: {msgs}"


ADMIN_HELP = (
    "👑 <b>Админ-панель</b>\n\n"
    "<code>/give ID premium|vip [дней]</code> — подарить подписку\n"
    "Можно ответить на пересланное сообщение человека: <code>/give vip 30</code>\n"
    "<code>/revoke ID</code> — снять подписку\n"
    "В любом личном чате: <code>.give vip 30</code> — подарить собеседнику"
)


@router.message(Command("admin"))
async def admin_panel(m: Message):
    if not _admin(m):
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[[_btn("📋 Подписки", "adm:subs"), _btn("📊 Статистика", "adm:stats")]])
    await m.answer(ADMIN_HELP, reply_markup=kb)


@router.callback_query(F.data.startswith("adm:"))
async def admin_cb(cb: CallbackQuery):
    if cb.from_user.id != config.ADMIN_ID:
        return await cb.answer("Только для админа", show_alert=True)
    text = await (_subs_text() if cb.data == "adm:subs" else _stats_text())
    await cb.message.answer(text)
    await cb.answer()


@router.message(Command("subs"))
async def subs(m: Message):
    if _admin(m):
        await m.answer(await _subs_text())


@router.message(Command("stats"))
async def stats(m: Message):
    if _admin(m):
        await m.answer(await _stats_text())
