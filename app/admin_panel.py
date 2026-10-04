import asyncio
import csv
import html
import io
import json
import logging
import time
from datetime import datetime

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.filters import Command, CommandObject
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from . import config, db
from .menu import _admin, _staff, _target, _subs_text, _stats_text, _spam_text
from .registry import REG, TIERS

log = logging.getLogger(__name__)
router = Router()
PENDING: dict[int, str] = {}
TIER_MAP = {"1": 1, "premium": 1, "prem": 1, "2": 2, "vip": 2}

ADMIN_HELP = (
    "👑 <b>Админ-панель</b>\n\n"
    "<b>Подписки</b>: <code>/give ID premium|vip [дней]</code> · <code>/revoke ID</code> · /subs\n"
    "В чате с человеком: <code>.premium 30</code> · <code>.vip 30</code> · <code>.revoke</code>\n"
    "<b>Промокоды</b>: <code>/newpromo КОД premium|vip ДНЕЙ ЛИМИТ</code> · /promos · <code>/delpromo КОД</code>\n"
    "<b>Пользователи</b>: /users · <code>/user ID</code> · /top · <code>/ban ID [причина]</code> · <code>/unban ID</code> · /bans\n"
    "<b>Команды</b>: <code>/disablecmd имя</code> · <code>/enablecmd имя</code> · /disabled · "
    "<code>/blockcmd ID имя</code> · <code>/unblockcmd ID имя</code>\n"
    "<b>Спам</b>: /spammers · <code>/stopspam ID|all</code>\n"
    "<b>Мини-админы</b>: <code>/addmod ID</code> · <code>/delmod ID</code> · /mods\n"
    "<b>Прочее</b>: <code>/broadcast текст</code> · <code>/maintenance on|off</code> · "
    "<code>/setprice premium|vip звёзды</code> · /export · /stats"
)
STAFF_HELP = (
    "🛡 <b>Мини-админка</b>\n\n"
    "У вас VIP-функции без лимитов. Доступно: /subs · /stats · /users · <code>/user ID</code> · /top · "
    "/spammers · <code>/stopspam ID|all</code>.\n"
    "Выдавать подписки, банить, делать рассылки и назначать мини-админов может только главный админ."
)


def _b(text, key):
    return InlineKeyboardButton(text=text, callback_data=f"adm:{key}")


def _kb(admin: bool) -> InlineKeyboardMarkup:
    rows = [[_b("📋 Подписки", "subs"), _b("📊 Статистика", "stats")],
            [_b("👥 Пользователи", "users"), _b("🏆 Топ", "top")],
            [_b("🚨 Спам", "spam")]]
    if admin:
        rows += [[_b("🚫 Баны", "bans"), _b("🎟 Промокоды", "promos")],
                 [_b("📢 Рассылка", "bc"), _b("⚙️ Команды", "cmds")],
                 [_b("🛠 Техработы: " + ("ВКЛ" if db.STATE["maint"] else "выкл"), "maint"), _b("💰 Цены", "prices")],
                 [_b("📤 Экспорт", "export")]]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _args(m: Message):
    return (m.text or "").split()[1:]


def _fmt(ts) -> str:
    return datetime.fromtimestamp(float(ts), config.MSK).strftime("%d.%m.%Y %H:%M")


def _name(r) -> str:
    return html.escape(f"{r['first_name'] or ''} {r['last_name'] or ''}".strip() or "—")


def _cmd_name(raw: str):
    c = REG.get(raw.lower().lstrip("."))
    return c.names[0] if c else None


# ---------- тексты разделов ----------
async def _users_text() -> str:
    total = (await db.fetchone("SELECT COUNT(DISTINCT user_id) c FROM connections"))["c"]
    rows = await db.fetchall(
        "SELECT user_id, first_name, last_name, MAX(ts) ts FROM connections GROUP BY user_id ORDER BY ts DESC LIMIT 30")
    lines = [f"👥 <b>Пользователи</b> ({total}), последние подключения:"]
    for r in rows:
        lines.append(f"<code>{r['user_id']}</code> {_name(r)} · {TIERS[await db.get_tier(r['user_id'])]}")
    return "\n".join(lines) + "\n\nКарточка: <code>/user ID</code>"


async def _top_text() -> str:
    rows = await db.fetchall(
        "SELECT c.user_id uid, COUNT(*) n FROM msgs m JOIN connections c ON c.conn_id = m.conn_id GROUP BY c.user_id ORDER BY n DESC LIMIT 10")
    cmds = await db.fetchall("SELECT cmd, SUM(n) n FROM cmdstat GROUP BY cmd ORDER BY n DESC LIMIT 10")
    out = ["🏆 <b>Самые активные</b> (сообщений за 30 дней)"]
    out += [f"{i}. <code>{r['uid']}</code> — {r['n']}" for i, r in enumerate(rows, 1)] or ["пока пусто"]
    out += ["", "🔥 <b>Популярные команды</b>"]
    out += [f"{i}. .{r['cmd']} — {r['n']}" for i, r in enumerate(cmds, 1)] or ["пока пусто"]
    return "\n".join(out)


async def _bans_text() -> str:
    rows = await db.fetchall("SELECT * FROM banned ORDER BY ts DESC LIMIT 40")
    if not rows:
        return "🚫 Банов нет"
    return "🚫 <b>Баны</b>\n" + "\n".join(
        f"<code>{r['user_id']}</code> · {_fmt(r['ts'])} · {html.escape(r['reason'] or '—')}" for r in rows) + "\n\nСнять: <code>/unban ID</code>"


async def _promos_text() -> str:
    rows = await db.fetchall("SELECT * FROM promos ORDER BY code")
    head = "🎟 <b>Промокоды</b>\n"
    body = "\n".join(f"<code>{r['code']}</code> · {TIERS[r['tier']]} {r['days']} дн. · осталось {r['uses_left']}" for r in rows) or "пока нет"
    return head + body + "\n\nСоздать: <code>/newpromo КОД premium 30 10</code>\nУдалить: <code>/delpromo КОД</code>\nПользователи активируют: <code>/promo КОД</code>"


def _cmds_text() -> str:
    dis = ", ".join(f".{c}" for c in sorted(db.DISABLED)) or "нет"
    return (f"⚙️ <b>Команды</b>\nОтключены глобально: {dis}\n\n"
            "<code>/disablecmd spam</code> — отключить для всех (кроме админов)\n<code>/enablecmd spam</code> — включить\n"
            "<code>/blockcmd ID spam</code> — отключить только одному пользователю\n<code>/unblockcmd ID spam</code> — вернуть")


def _prices_text() -> str:
    return (f"💰 <b>Цены</b> ({config.SUB_DAYS} дн.)\nPREMIUM: {config.PRICES[1]}⭐\nVIP: {config.PRICES[2]}⭐\n\n"
            "Изменить: <code>/setprice premium 200</code>")


async def _export(msg: Message):
    rows = await db.fetchall("SELECT user_id, first_name, last_name, MAX(ts) ts FROM connections GROUP BY user_id")
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["user_id", "name", "tier", "sub_until", "banned", "mod", "last_seen"])
    for r in rows:
        uid = r["user_id"]
        sub = await db.get_sub(uid)
        seen = await db.get_s(uid, "last_seen")
        w.writerow([uid, f"{r['first_name']} {r['last_name']}".strip(), TIERS[await db.get_tier(uid)],
                    _fmt(sub["until"]) if sub else "", int(uid in db.BANNED), int(uid in db.MODS), _fmt(seen) if seen else ""])
    await msg.answer_document(BufferedInputFile(buf.getvalue().encode("utf-8-sig"), "users.csv"), caption=f"👥 Пользователей: {len(rows)}")


# ---------- панель ----------
@router.message(Command("admin", "adminhelp"))
async def admin_panel(m: Message):
    if not _staff(m):
        return
    await m.answer(f"ℹ️ Версия: <code>{config.VERSION}</code>\n\n" + (ADMIN_HELP if _admin(m) else STAFF_HELP), reply_markup=_kb(_admin(m)))


ADMIN_ONLY = {"bans", "promos", "bc", "cmds", "maint", "prices", "export"}


@router.callback_query(F.data.startswith("adm:"))
async def admin_cb(cb: CallbackQuery):
    key, uid = cb.data[4:], cb.from_user.id
    if not db.is_staff(uid):
        return await cb.answer("Только для админов", show_alert=True)
    if key in ADMIN_ONLY and uid != config.ADMIN_ID:
        return await cb.answer("Только для главного админа", show_alert=True)
    if key == "export":
        await _export(cb.message)
        return await cb.answer()
    if key == "maint":
        await db.set_maint(not db.STATE["maint"])
        text = "🛠 Режим техработ <b>включён</b>: команды у обычных пользователей не работают." if db.STATE["maint"] else "✅ Режим техработ выключен."
    elif key == "bc":
        text = "📢 <b>Рассылка</b>\nНапишите <code>/broadcast текст</code> — покажу предпросмотр и спрошу подтверждение."
    else:
        text = {"subs": _subs_text, "stats": _stats_text, "users": _users_text, "top": _top_text, "bans": _bans_text,
                "promos": _promos_text}.get(key, lambda: None)()
        if asyncio.iscoroutine(text):
            text = await text
        if key == "spam":
            text = _spam_text()
        elif key == "cmds":
            text = _cmds_text()
        elif key == "prices":
            text = _prices_text()
    await cb.message.answer(text or "—")
    await cb.answer()


# ---------- пользователи ----------
@router.message(Command("users"))
async def users(m: Message):
    if _staff(m):
        await m.answer(await _users_text())


@router.message(Command("top"))
async def top(m: Message):
    if _staff(m):
        await m.answer(await _top_text())


@router.message(Command("user"))
async def user_card(m: Message):
    if not _staff(m):
        return
    uid, _ = _target(m, _args(m))
    if uid is None:
        return await m.answer("Формат: <code>/user ID</code> или ответом на пересланное сообщение")
    t, sub = await db.get_tier(uid), await db.get_sub(uid)
    conns = (await db.fetchone("SELECT COUNT(*) c FROM connections WHERE user_id=?", (uid,)))["c"]
    msgs = (await db.fetchone("SELECT COUNT(*) c FROM msgs m JOIN connections c ON c.conn_id=m.conn_id WHERE c.user_id=?", (uid,)))["c"]
    refs = (await db.fetchone("SELECT COUNT(*) c FROM settings WHERE key='ref' AND value=?", (str(uid),)))["c"]
    seen = await db.get_s(uid, "last_seen")
    flags = [x for x, on in (("👑 админ", uid == config.ADMIN_ID), ("🛡 мини-админ", uid in db.MODS), ("🚫 забанен", uid in db.BANNED)) if on]
    blocked = json.loads(await db.get_s(uid, "blocked_cmds", "[]"))
    await m.answer(
        f"👤 <b>{uid}</b> {' '.join(flags)}\nТариф: {TIERS[t]}" + (f" до {_fmt(sub['until'])}" if sub and sub['until'] > time.time() else "") +
        f"\nПодключений: {conns} · сообщений в журнале: {msgs}\nПриглашено друзей: {refs}\n"
        f"Последняя команда: {_fmt(seen) if seen else '—'}\nСпам: {'отключён' if 'spam' in blocked else 'доступен'}" +
        (f"\nОтключённые команды: {', '.join('.' + c for c in blocked)}" if blocked else ""))


# ---------- баны ----------
@router.message(Command("ban"))
async def ban(m: Message, bot: Bot):
    if not _admin(m):
        return
    uid, a = _target(m, _args(m))
    if uid is None:
        return await m.answer("Формат: <code>/ban ID [причина]</code>")
    if db.is_staff(uid):
        return await m.answer("Админов банить нельзя")
    await db.ban(uid, " ".join(a))
    await m.answer(f"🚫 {uid} заблокирован. Команды бота у него больше не работают.")
    try:
        await bot.send_message(uid, "⛔ Вы заблокированы администратором." + (f"\nПричина: {html.escape(' '.join(a))}" if a else ""))
    except Exception:
        pass


@router.message(Command("unban"))
async def unban(m: Message):
    if not _admin(m):
        return
    uid, _ = _target(m, _args(m))
    if uid is None:
        return await m.answer("Формат: <code>/unban ID</code>")
    await db.unban(uid)
    await m.answer(f"✅ {uid} разблокирован")


@router.message(Command("bans"))
async def bans(m: Message):
    if _admin(m):
        await m.answer(await _bans_text())


# ---------- команды: глобально и точечно ----------
@router.message(Command("disablecmd", "enablecmd"))
async def toggle_cmd(m: Message, command: CommandObject):
    if not _admin(m):
        return
    name = _cmd_name((command.args or "").strip())
    if not name:
        return await m.answer("Такой команды нет. Формат: <code>/disablecmd spam</code>")
    on = command.command == "disablecmd"
    await db.set_disabled(name, on)
    await m.answer(f"{'⛔ Отключена' if on else '✅ Включена'} для всех: <code>.{name}</code>")


@router.message(Command("disabled"))
async def disabled(m: Message):
    if _admin(m):
        await m.answer(_cmds_text())


@router.message(Command("blockcmd", "unblockcmd"))
async def block_cmd(m: Message, command: CommandObject):
    if not _admin(m):
        return
    uid, a = _target(m, _args(m))
    name = _cmd_name(a[0]) if a else None
    if uid is None or not name:
        return await m.answer("Формат: <code>/blockcmd ID spam</code>")
    blocked = set(json.loads(await db.get_s(uid, "blocked_cmds", "[]")))
    on = command.command == "blockcmd"
    blocked.add(name) if on else blocked.discard(name)
    await db.set_s(uid, "blocked_cmds", json.dumps(sorted(blocked)))
    await m.answer(f"{'⛔ Отключена' if on else '✅ Возвращена'} для {uid}: <code>.{name}</code>")


# ---------- промокоды ----------
@router.message(Command("newpromo"))
async def newpromo(m: Message):
    if not _admin(m):
        return
    a = _args(m)
    if len(a) < 4 or a[1].lower() not in TIER_MAP or not a[2].isdigit() or not a[3].isdigit():
        return await m.answer("Формат: <code>/newpromo КОД premium|vip ДНЕЙ ЛИМИТ</code>")
    code = a[0].upper()
    await db.execute("INSERT OR REPLACE INTO promos VALUES(?,?,?,?)", (code, TIER_MAP[a[1].lower()], int(a[2]), int(a[3])))
    await db.execute("DELETE FROM promo_used WHERE code=?", (code,))
    await m.answer(f"🎟 Промокод <code>{code}</code>: {TIERS[TIER_MAP[a[1].lower()]]} на {a[2]} дн., активаций {a[3]}\nПользователи вводят: <code>/promo {code}</code>")


@router.message(Command("promos"))
async def promos(m: Message):
    if _admin(m):
        await m.answer(await _promos_text())


@router.message(Command("delpromo"))
async def delpromo(m: Message, command: CommandObject):
    if not _admin(m):
        return
    code = (command.args or "").strip().upper()
    await db.execute("DELETE FROM promos WHERE code=?", (code,))
    await m.answer(f"🗑 Промокод {html.escape(code)} удалён")


# ---------- прочее ----------
@router.message(Command("maintenance"))
async def maintenance(m: Message, command: CommandObject):
    if not _admin(m):
        return
    a = (command.args or "").strip().lower()
    if a not in ("on", "off"):
        return await m.answer(f"Сейчас: {'включены' if db.STATE['maint'] else 'выключены'}. Формат: <code>/maintenance on|off</code>")
    await db.set_maint(a == "on")
    await m.answer("🛠 Режим техработ " + ("включён: обычные пользователи не могут пользоваться командами" if a == "on" else "выключен"))


@router.message(Command("setprice"))
async def setprice(m: Message):
    if not _admin(m):
        return
    a = _args(m)
    if len(a) < 2 or a[0].lower() not in TIER_MAP or not a[1].isdigit() or int(a[1]) < 1:
        return await m.answer("Формат: <code>/setprice premium 200</code>")
    t = TIER_MAP[a[0].lower()]
    config.PRICES[t] = int(a[1])
    await db.set_s(0, f"price_{t}", a[1])
    await m.answer(f"💰 {TIERS[t]}: {a[1]}⭐")


@router.message(Command("export"))
async def export(m: Message):
    if _admin(m):
        await _export(m)


async def _recipients():
    rows = await db.fetchall("SELECT user_id FROM connections UNION SELECT user_id FROM settings WHERE key='started' AND user_id != 0")
    return [r["user_id"] for r in rows if r["user_id"] not in db.BANNED]


@router.message(Command("broadcast"))
async def broadcast(m: Message, command: CommandObject):
    if not _admin(m):
        return
    text = (command.args or "").strip()
    if not text:
        return await m.answer("Формат: <code>/broadcast текст рассылки</code> (можно HTML-разметку)")
    PENDING[m.from_user.id] = text
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=f"✅ Отправить ({len(await _recipients())})", callback_data="bc:ok"),
        InlineKeyboardButton(text="✖ Отмена", callback_data="bc:no")]])
    try:
        await m.answer(f"📢 <b>Предпросмотр</b>\n\n{text}", reply_markup=kb)
    except TelegramBadRequest:
        PENDING[m.from_user.id] = html.escape(text)
        await m.answer(f"📢 <b>Предпросмотр</b>\n\n{html.escape(text)}", reply_markup=kb)


@router.callback_query(F.data.startswith("bc:"))
async def broadcast_cb(cb: CallbackQuery, bot: Bot):
    if cb.from_user.id != config.ADMIN_ID:
        return await cb.answer("Только для главного админа", show_alert=True)
    text = PENDING.pop(cb.from_user.id, None)
    if cb.data == "bc:no" or not text:
        await cb.message.edit_reply_markup(reply_markup=None)
        return await cb.answer("Отменено")
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.answer("Отправляю…")
    sent = failed = 0
    for uid in await _recipients():
        try:
            try:
                await bot.send_message(uid, text)
            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after + 1)
                await bot.send_message(uid, text)
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)
    await cb.message.answer(f"📢 Рассылка завершена: доставлено {sent}, не доставлено {failed}")
