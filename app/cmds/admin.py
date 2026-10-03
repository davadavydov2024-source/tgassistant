from datetime import datetime

from .. import config, db
from ..registry import command, TIERS

TIER_MAP = {"0": 0, "free": 0, "1": 1, "premium": 1, "prem": 1, "2": 2, "vip": 2}


def _parse(ctx):
    """.give [user_id] premium|vip [дней] — без user_id подарок уходит собеседнику в текущем чате."""
    a = ctx.args.split()
    uid = ctx.chat_id
    if a and a[0].isdigit() and len(a[0]) > 5:
        uid, a = int(a[0]), a[1:]
    return uid, a


@command("give", section="manage", hidden=True, help="(админ) подарить подписку")
async def give(ctx):
    if not ctx.is_admin:
        return
    uid, a = _parse(ctx)
    tier = TIER_MAP.get(a[0].lower()) if a else None
    if tier is None:
        return await ctx.edit("Формат: <code>.give premium|vip [дней]</code> (в чате с человеком)\nили <code>.give user_id vip 30</code>")
    days = int(a[1]) if len(a) > 1 and a[1].isdigit() else config.SUB_DAYS
    await db.grant(uid, tier, days)
    await ctx.edit(f"🎁 <code>{uid}</code>: <b>{TIERS[tier]}</b> на {days} дн.")
    try:
        await ctx.bot.send_message(uid, f"🎁 Вам выдан тариф <b>{TIERS[tier]}</b> на {days} дн.")
    except Exception:
        pass


@command("revoke", section="manage", hidden=True, help="(админ) снять подписку")
async def revoke(ctx):
    if not ctx.is_admin:
        return
    uid, _ = _parse(ctx)
    await db.revoke(uid)
    await ctx.edit(f"🗑 Подписка <code>{uid}</code> снята")


@command("subs", section="manage", hidden=True, help="(админ) список подписок")
async def subs(ctx):
    if not ctx.is_admin:
        return
    import time
    rows = await db.fetchall("SELECT * FROM subs WHERE until > ? ORDER BY until DESC", (time.time(),))
    if not rows:
        return await ctx.edit("Активных подписок нет")
    await ctx.edit("<b>Подписки</b>\n" + "\n".join(
        f"<code>{r['user_id']}</code> — {TIERS[r['tier']]} до {datetime.fromtimestamp(r['until'], config.MSK):%d.%m.%Y}" for r in rows[:40]))
