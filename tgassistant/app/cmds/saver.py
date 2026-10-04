import html
import logging
import time

from .. import db
from ..registry import command

log = logging.getLogger(__name__)
KINDS = ("photo", "video", "voice", "video_note", "audio", "animation", "sticker", "document")
NO_CAPTION = {"video_note", "sticker"}


async def enabled(owner_id: int) -> bool:
    return await db.get_s(owner_id, "save", "0") == "1" and await db.get_tier(owner_id) >= 1


def _extract(m):
    for k in KINDS:
        v = getattr(m, k, None)
        if v:
            return k, (v[-1].file_id if k == "photo" else v.file_id)
    return "text", ""


async def remember(m, conn_id: str):
    """Запомнить сообщение собеседника (текст и file_id, сами файлы не скачиваются)."""
    if m.has_protected_content:  # отправитель запретил пересылку/сохранение — уважаем
        return
    kind, fid = _extract(m)
    text = m.text or m.caption or ""
    if not text and not fid:
        return
    await db.execute(
        "INSERT OR REPLACE INTO saved VALUES(?,?,?,?,?,?,?,?,?)",
        (conn_id, m.chat.id, m.message_id, m.from_user.id if m.from_user else 0,
         m.chat.full_name or "", kind, text, fid, time.time()),
    )


async def get(conn_id, chat_id, message_id):
    return await db.fetchone("SELECT * FROM saved WHERE conn_id=? AND chat_id=? AND message_id=?", (conn_id, chat_id, message_id))


async def _deliver(bot, owner_id, row, header):
    name = html.escape(row["from_name"] or "?")
    cap = f"{header} · <b>{name}</b>" + (f"\n{html.escape(row['text'])}" if row["text"] else "")
    cap = cap[:1000]
    kind, fid = row["kind"], row["file_id"]
    if kind == "text" or not fid:
        return await bot.send_message(owner_id, cap)
    send = getattr(bot, f"send_{kind}")
    try:
        if kind in NO_CAPTION:
            await bot.send_message(owner_id, cap)
            await send(owner_id, fid)
        else:
            await send(owner_id, fid, caption=cap)
    except Exception as e:
        log.warning("saver deliver: %s", e)
        await bot.send_message(owner_id, cap + "\n<i>(файл больше недоступен)</i>")


async def notify_deleted(bot, owner_id, row):
    await _deliver(bot, owner_id, row, "🗑 Удалено для всех")


async def notify_edited(bot, owner_id, row, new_text):
    name = html.escape(row["from_name"] or "?")
    await bot.send_message(
        owner_id,
        f"✏️ <b>{name}</b> изменил(а) сообщение\n<b>Было:</b> {html.escape(row['text'] or '—')[:1500]}\n<b>Стало:</b> {html.escape(new_text or '—')[:1500]}",
    )


@command("startsave", section="manage", tier=1, help="присылать вам в бота удалённые и изменённые сообщения собеседников")
async def startsave(ctx):
    await db.set_s(ctx.owner_id, "save", "1")
    await ctx.edit("💾 Сохранение включено. Удалённые и изменённые сообщения собеседников будут приходить вам в личку с ботом (нужно один раз нажать /start в боте).")


@command("stopsave", section="manage", tier=1, help="выключить сохранение удалённых/изменённых сообщений")
async def stopsave(ctx):
    await db.set_s(ctx.owner_id, "save", "0")
    await ctx.edit("⏹ Сохранение выключено")


@command("clearsave", section="manage", tier=1, help="стереть всё сохранённое по этому чату")
async def clearsave(ctx):
    await db.execute("DELETE FROM saved WHERE conn_id=? AND chat_id=?", (ctx.conn_id, ctx.chat_id))
    await ctx.edit("🧹 Сохранённое по этому чату стёрто")
