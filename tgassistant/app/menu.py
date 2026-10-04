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
from .cmds import anim

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
    "🔌 <b>Как подключить бота</b>\n\n"
    "1. Обновите Telegram до последней версии.\n"
    "2. Откройте <b>Настройки → Telegram для бизнеса → Чат-боты</b>.\n"
    "3. Введите @username этого бота и выберите, с какими чатами он работает (например, все личные).\n"
    "4. Включите права для бота: <b>отвечать на сообщения</b>, <b>удалять сообщения</b> (нужно для .panic и модерации), "
    "<b>читать сообщения</b>, а для .timeprofile ещё <b>менять имя профиля</b>.\n"
    "5. Вернитесь сюда и нажмите /start — так бот сможет писать вам в личку (напоминания, заметки, удалённые сообщения).\n"
    "6. В любом личном чате отправьте <code>.ping</code> — бот должен ответить «pong». Все команды — <code>.help</code>.\n\n"
    "ℹ️ Telegram Premium для подключения больше не обязателен — по сообщениям Telegram и сервисов, с мая 2026. "
    "Если пункта «Telegram для бизнеса» у вас нет, обновите приложение; на старых версиях он может быть только у Premium.\n"
    "⚠️ Команды работают только в личных чатах и только когда их пишете вы."
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
    if uid in db.MODS:
        return "Ваш тариф: <b>VIP</b> (мини-админ)"
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


def _staff(m: Message) -> bool:
    return bool(m.from_user and db.is_staff(m.from_user.id))


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
    "<b>Подписки</b>\n"
    "<code>/give ID premium|vip [дней]</code> — подарить\n"
    "<code>/revoke ID</code> — снять\n"
    "Можно ответить на пересланное сообщение человека: <code>/give vip 30</code>\n"
    "В личном чате: <code>.premium 30</code>, <code>.vip 30</code>, <code>.give vip 30</code>, <code>.revoke</code>\n\n"
    "<b>Спам</b>: <code>/spammers</code> — кто сейчас спамит, <code>/stopspam ID</code> или <code>/stopspam all</code> — остановить "
    "(пользователь потом сможет запустить снова). В чате: <code>.stopspam ID</code>\n\n"
    "<b>Мини-админы</b> (всё без лимитов, но выдавать подписки нельзя)\n"
    "<code>/addmod ID</code> · <code>/delmod ID</code> · <code>/mods</code>\n"
    "В личном чате: <code>.addmod</code> · <code>.delmod</code> · <code>.mods</code>"
)
STAFF_HELP = (
    "🛡 <b>Мини-админка</b>\n\n"
    "У вас VIP-функции без лимитов. Доступно: просмотр подписок и статистики, остановка чужого спама (<code>/spammers</code>, <code>/stopspam ID</code>).\n"
    "Выдавать и снимать подписки, назначать мини-админов может только главный админ."
)


@router.message(Command("admin"))
async def admin_panel(m: Message):
    if not _staff(m):
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[[_btn("📋 Подписки", "adm:subs"), _btn("📊 Статистика", "adm:stats")], [_btn("🚨 Активный спам", "adm:spam")]])
    await m.answer(ADMIN_HELP if _admin(m) else STAFF_HELP, reply_markup=kb)


@router.callback_query(F.data.startswith("adm:"))
async def admin_cb(cb: CallbackQuery):
    if not db.is_staff(cb.from_user.id):
        return await cb.answer("Только для админов", show_alert=True)
    text = await (_subs_text() if cb.data == "adm:subs" else _stats_text()) if cb.data != "adm:spam" else _spam_text()
    await cb.message.answer(text)
    await cb.answer()


def _spam_text() -> str:
    items = anim.list_active()
    if not items:
        return "🚨 Активного спама сейчас нет"
    return "🚨 <b>Активный спам</b>\n" + "\n".join(
        f"<code>{i['owner']}</code> · чат <code>{i['chat']}</code> · {i['sent']}/{i['total']}" for i in items[:30]
    ) + "\n\nОстановить: <code>/stopspam ID</code> или <code>/stopspam all</code>"


@router.message(Command("spammers"))
async def spammers(m: Message):
    if _staff(m):
        await m.answer(_spam_text())


@router.message(Command("stopspam"))
async def stopspam_cmd(m: Message, bot: Bot):
    if not _staff(m):
        return
    a = (m.text or "").split()[1:]
    if a and a[0].lower() == "all":
        n = len(anim.stop_owner(None))
    elif a and a[0].isdigit():
        n = len(anim.stop_owner(int(a[0])))
    else:
        return await m.answer("Формат: <code>/stopspam ID</code> или <code>/stopspam all</code>. Список: /spammers")
    await m.answer(f"🛑 Остановлено спам-задач: {n}. Пользователь сможет запустить спам снова.")


@router.message(Command("startsave"))
async def startsave_dm(m: Message):
    if await db.get_tier(m.from_user.id) < 1:
        return await m.answer("Сохранение удалённых и изменённых сообщений — на тарифе PREMIUM и выше. Тарифы: /start")
    await db.set_s(m.from_user.id, "save", "1")
    await m.answer("💾 Включено: удалённые для всех и изменённые сообщения собеседников будут приходить сюда. Выключить: /stopsave")


@router.message(Command("stopsave"))
async def stopsave_dm(m: Message):
    await db.set_s(m.from_user.id, "save", "0")
    await m.answer("⏹ Сохранение выключено. Включить: /startsave")


@router.message(Command("addmod"))
async def addmod(m: Message, bot: Bot):
    if not _admin(m):
        return
    uid, _ = _target(m, (m.text or "").split()[1:])
    if uid is None:
        return await m.answer("Формат: <code>/addmod ID</code> или ответом на пересланное сообщение человека")
    await db.add_mod(uid)
    await m.answer(f"🛡 {uid} — мини-админ")
    try:
        await bot.send_message(uid, "🛡 Вам выданы права мини-админа: все функции без лимитов. Выдавать подписки нельзя.")
    except Exception:
        pass


@router.message(Command("delmod"))
async def delmod(m: Message):
    if not _admin(m):
        return
    uid, _ = _target(m, (m.text or "").split()[1:])
    if uid is None:
        return await m.answer("Формат: <code>/delmod ID</code>")
    await db.del_mod(uid)
    await m.answer("✅ Мини-админ снят")


@router.message(Command("mods"))
async def mods(m: Message):
    if _admin(m):
        await m.answer("🛡 <b>Мини-админы</b>\n" + ("\n".join(f"<code>{u}</code>" for u in sorted(db.MODS)) or "пока нет"))


@router.message(Command("id"))
async def my_id(m: Message):
    await m.answer(f"Ваш ID: <code>{m.from_user.id}</code>")


@router.message(Command("subs"))
async def subs(m: Message):
    if _staff(m):
        await m.answer(await _subs_text())


@router.message(Command("stats"))
async def stats(m: Message):
    if _staff(m):
        await m.answer(await _stats_text())
