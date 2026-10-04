import time
from datetime import datetime

from .. import config, db
from ..registry import command, TIERS

TIER_MAP = {"0": 0, "free": 0, "1": 1, "premium": 1, "prem": 1, "2": 2, "vip": 2}


def _uid(ctx, a):
    """Если первым аргументом длинный ID — берём его, иначе собеседника в текущем чате."""
    if a and a[0].isdigit() and len(a[0]) > 5:
        return int(a[0]), a[1:]
    return ctx.chat_id, a


async def _dm(ctx, uid, text):
    try:
        await ctx.bot.send_message(uid, text)
    except Exception:
        pass


async def _gift(ctx, uid, tier, days):
    await db.grant(uid, tier, days)
    await ctx.edit(f"🎁 <code>{uid}</code>: <b>{TIERS[tier]}</b> на {days} дн.")
    await _dm(ctx, uid, f"🎁 Вам выдан тариф <b>{TIERS[tier]}</b> на {days} дн.")


@command("give", section="manage", hidden=True, help="(админ) подарить подписку")
async def give(ctx):
    if not ctx.is_admin:
        return
    uid, a = _uid(ctx, ctx.args.split())
    tier = TIER_MAP.get(a[0].lower()) if a else None
    if tier is None:
        return await ctx.edit("Формат: <code>.give premium|vip [дней]</code> (в чате с человеком)\nили <code>.give user_id vip 30</code>")
    days = int(a[1]) if len(a) > 1 and a[1].isdigit() else config.SUB_DAYS
    await _gift(ctx, uid, tier, days)


@command("premium", section="manage", hidden=True, help="(админ) выдать PREMIUM собеседнику")
async def premium(ctx):
    if not ctx.is_admin:
        return
    uid, a = _uid(ctx, ctx.args.split())
    await _gift(ctx, uid, 1, int(a[0]) if a and a[0].isdigit() else config.SUB_DAYS)


@command("vip", section="manage", hidden=True, help="(админ) выдать VIP собеседнику")
async def vip(ctx):
    if not ctx.is_admin:
        return
    uid, a = _uid(ctx, ctx.args.split())
    await _gift(ctx, uid, 2, int(a[0]) if a and a[0].isdigit() else config.SUB_DAYS)


@command("revoke", section="manage", hidden=True, help="(админ) снять подписку")
async def revoke(ctx):
    if not ctx.is_admin:
        return
    uid, _ = _uid(ctx, ctx.args.split())
    await db.revoke(uid)
    await ctx.edit(f"🗑 Подписка <code>{uid}</code> снята")


@command("addmod", section="manage", hidden=True, help="(админ) назначить мини-админа")
async def addmod(ctx):
    if not ctx.is_admin:
        return
    uid, _ = _uid(ctx, ctx.args.split())
    await db.add_mod(uid)
    await ctx.edit(f"🛡 <code>{uid}</code> — мини-админ: без лимитов, VIP-функции, но без выдачи подписок")
    await _dm(ctx, uid, "🛡 Вам выданы права мини-админа: все функции без лимитов. Выдавать подписки нельзя.")


@command("delmod", section="manage", hidden=True, help="(админ) снять мини-админа")
async def delmod(ctx):
    if not ctx.is_admin:
        return
    uid, _ = _uid(ctx, ctx.args.split())
    await db.del_mod(uid)
    await ctx.edit(f"✅ <code>{uid}</code> больше не мини-админ")


@command("mods", section="manage", hidden=True, help="(админ) список мини-админов")
async def mods(ctx):
    if not ctx.is_admin:
        return
    await ctx.edit("🛡 <b>Мини-админы</b>\n" + ("\n".join(f"<code>{u}</code>" for u in sorted(db.MODS)) or "пока нет"))


@command("subs", section="manage", hidden=True, help="(админ/мини-админ) список подписок")
async def subs(ctx):
    if not ctx.is_staff:
        return
    rows = await db.fetchall("SELECT * FROM subs WHERE until > ? ORDER BY until DESC", (time.time(),))
    if not rows:
        return await ctx.edit("Активных подписок нет")
    await ctx.edit("<b>Подписки</b>\n" + "\n".join(
        f"<code>{r['user_id']}</code> — {TIERS[r['tier']]} до {datetime.fromtimestamp(r['until'], config.MSK):%d.%m.%Y}" for r in rows[:40]))
