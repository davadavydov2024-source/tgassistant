import json
import time
from datetime import datetime

import aiosqlite

from . import config

_db: aiosqlite.Connection | None = None
MODS: set[int] = set()  # мини-админы (кэш)
BANNED: set[int] = set()
DISABLED: set[str] = set()  # глобально отключённые команды
STATE = {"maint": False}  # режим техработ

SCHEMA = """
CREATE TABLE IF NOT EXISTS connections(conn_id TEXT PRIMARY KEY, user_id INTEGER, first_name TEXT, last_name TEXT, ts REAL, username TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS subs(user_id INTEGER PRIMARY KEY, tier INTEGER, until REAL);
CREATE TABLE IF NOT EXISTS settings(user_id INTEGER, key TEXT, value TEXT, PRIMARY KEY(user_id, key));
CREATE TABLE IF NOT EXISTS chatset(conn_id TEXT, chat_id INTEGER, key TEXT, value TEXT, PRIMARY KEY(conn_id, chat_id, key));
CREATE TABLE IF NOT EXISTS msgs(conn_id TEXT, chat_id INTEGER, message_id INTEGER, from_id INTEGER, ts REAL);
CREATE TABLE IF NOT EXISTS reminders(id INTEGER PRIMARY KEY AUTOINCREMENT, owner_id INTEGER, due REAL, text TEXT);
CREATE TABLE IF NOT EXISTS saved(conn_id TEXT, chat_id INTEGER, message_id INTEGER, from_id INTEGER, from_name TEXT, kind TEXT, text TEXT, file_id TEXT, ts REAL, username TEXT DEFAULT '', hist TEXT DEFAULT '[]', PRIMARY KEY(conn_id, chat_id, message_id));
CREATE TABLE IF NOT EXISTS mods(user_id INTEGER PRIMARY KEY);
CREATE TABLE IF NOT EXISTS cmdstat(day TEXT, cmd TEXT, n INTEGER, PRIMARY KEY(day, cmd));
CREATE TABLE IF NOT EXISTS promos(code TEXT PRIMARY KEY, tier INTEGER, days INTEGER, uses_left INTEGER);
CREATE TABLE IF NOT EXISTS promo_used(code TEXT, user_id INTEGER, PRIMARY KEY(code, user_id));
CREATE TABLE IF NOT EXISTS banned(user_id INTEGER PRIMARY KEY, reason TEXT, ts REAL);
CREATE INDEX IF NOT EXISTS msgs_idx ON msgs(conn_id, chat_id);
"""


async def init(path: str):
    global _db
    _db = await aiosqlite.connect(path)
    _db.row_factory = aiosqlite.Row
    await _db.executescript(SCHEMA)
    for sql in ("ALTER TABLE connections ADD COLUMN username TEXT DEFAULT ''",
                "ALTER TABLE saved ADD COLUMN username TEXT DEFAULT ''",
                "ALTER TABLE saved ADD COLUMN hist TEXT DEFAULT '[]'"):
        try:  # миграция старых баз: колонка уже есть — это нормально
            await _db.execute(sql)
        except Exception:
            pass
    await _db.execute("DELETE FROM msgs WHERE ts < ?", (time.time() - 30 * 86400,))
    await _db.execute("DELETE FROM saved WHERE ts < ?", (time.time() - 7 * 86400,))
    await _db.commit()
    MODS.clear()
    MODS.update(r["user_id"] for r in await fetchall("SELECT user_id FROM mods"))
    await load_global()


async def load_global():
    raw = await get_s(0, "disabled_cmds")
    DISABLED.clear()
    DISABLED.update(json.loads(raw) if raw else [])
    STATE["maint"] = (await get_s(0, "maint", "0")) == "1"
    BANNED.clear()
    BANNED.update(r["user_id"] for r in await fetchall("SELECT user_id FROM banned"))
    for t in (1, 2):
        v = await get_s(0, f"price_{t}")
        if v and v.isdigit():
            config.PRICES[t] = int(v)


async def ban(user_id: int, reason: str = ""):
    await execute("INSERT OR REPLACE INTO banned VALUES(?,?,?)", (user_id, reason, time.time()))
    BANNED.add(user_id)


async def unban(user_id: int):
    await execute("DELETE FROM banned WHERE user_id=?", (user_id,))
    BANNED.discard(user_id)


async def set_disabled(name: str, on: bool):
    DISABLED.add(name) if on else DISABLED.discard(name)
    await set_s(0, "disabled_cmds", json.dumps(sorted(DISABLED)))


async def set_maint(on: bool):
    STATE["maint"] = on
    await set_s(0, "maint", "1" if on else "0")


async def log_cmd(name: str):
    day = datetime.now(config.MSK).strftime("%Y-%m-%d")
    await execute("INSERT INTO cmdstat(day,cmd,n) VALUES(?,?,1) ON CONFLICT(day,cmd) DO UPDATE SET n=n+1", (day, name))


async def touch_seen(user_id: int):
    await set_s(user_id, "last_seen", time.time())


async def apply_sub(user_id: int, tier: int, days: int):
    """Выдать/продлить, не понижая более высокий активный тариф."""
    row = await get_sub(user_id)
    if row and row["until"] > time.time() and row["tier"] > tier:
        await execute("UPDATE subs SET until=until+? WHERE user_id=?", (days * 86400, user_id))
    else:
        await grant(user_id, tier, days)


def is_staff(user_id: int) -> bool:
    return user_id == config.ADMIN_ID or user_id in MODS


async def add_mod(user_id: int):
    await execute("INSERT OR IGNORE INTO mods VALUES(?)", (user_id,))
    MODS.add(user_id)


async def del_mod(user_id: int):
    await execute("DELETE FROM mods WHERE user_id=?", (user_id,))
    MODS.discard(user_id)


async def fetchall(sql, args=()):
    async with _db.execute(sql, args) as cur:
        return await cur.fetchall()


async def fetchone(sql, args=()):
    async with _db.execute(sql, args) as cur:
        return await cur.fetchone()


async def execute(sql, args=()):
    await _db.execute(sql, args)
    await _db.commit()


# ---- подключения ----
async def save_conn(conn_id, user_id, first, last, username=""):
    await execute(
        "INSERT OR REPLACE INTO connections(conn_id,user_id,first_name,last_name,ts,username) VALUES(?,?,?,?,?,?)",
        (conn_id, user_id, first or "", last or "", time.time(), username or ""),
    )


async def touch_username(user_id, username):
    await execute("UPDATE connections SET username=? WHERE user_id=? AND COALESCE(username,'') != ?", (username or "", user_id, username or ""))


async def get_conn(conn_id):
    return await fetchone("SELECT * FROM connections WHERE conn_id=?", (conn_id,))


async def latest_conn(user_id):
    return await fetchone("SELECT * FROM connections WHERE user_id=? ORDER BY ts DESC LIMIT 1", (user_id,))


# ---- подписки ----
async def get_sub(user_id):
    return await fetchone("SELECT * FROM subs WHERE user_id=?", (user_id,))


async def get_tier(user_id) -> int:
    if is_staff(user_id):
        return 2
    row = await get_sub(user_id)
    if row and row["until"] > time.time():
        return row["tier"]
    return 0


async def grant(user_id, tier, days):
    row = await get_sub(user_id)
    base = time.time()
    if row and row["tier"] == tier and row["until"] > base:
        base = row["until"]
    await execute("INSERT OR REPLACE INTO subs VALUES(?,?,?)", (user_id, tier, base + days * 86400))


async def revoke(user_id):
    await execute("DELETE FROM subs WHERE user_id=?", (user_id,))


# ---- настройки пользователя ----
async def get_s(user_id, key, default=None):
    row = await fetchone("SELECT value FROM settings WHERE user_id=? AND key=?", (user_id, key))
    return row["value"] if row else default


async def set_s(user_id, key, value):
    await execute("INSERT OR REPLACE INTO settings VALUES(?,?,?)", (user_id, key, str(value)))


async def del_s(user_id, key):
    await execute("DELETE FROM settings WHERE user_id=? AND key=?", (user_id, key))


async def get_all_s(user_id) -> dict:
    rows = await fetchall("SELECT key,value FROM settings WHERE user_id=?", (user_id,))
    return {r["key"]: r["value"] for r in rows}


# ---- настройки чата ----
async def get_c(conn_id, chat_id, key, default=None):
    row = await fetchone("SELECT value FROM chatset WHERE conn_id=? AND chat_id=? AND key=?", (conn_id, chat_id, key))
    return row["value"] if row else default


async def set_c(conn_id, chat_id, key, value):
    await execute("INSERT OR REPLACE INTO chatset VALUES(?,?,?,?)", (conn_id, chat_id, key, str(value)))


async def del_c(conn_id, chat_id, key):
    await execute("DELETE FROM chatset WHERE conn_id=? AND chat_id=? AND key=?", (conn_id, chat_id, key))


async def get_all_c(conn_id, chat_id) -> dict:
    rows = await fetchall("SELECT key,value FROM chatset WHERE conn_id=? AND chat_id=?", (conn_id, chat_id))
    return {r["key"]: r["value"] for r in rows}


async def get_cj(conn_id, chat_id, key):
    v = await get_c(conn_id, chat_id, key)
    return json.loads(v) if v else None


async def set_cj(conn_id, chat_id, key, obj):
    await set_c(conn_id, chat_id, key, json.dumps(obj, ensure_ascii=False))


# ---- журнал id сообщений (для .panic и .status) ----
async def log_msg(conn_id, chat_id, message_id, from_id):
    await execute("INSERT INTO msgs VALUES(?,?,?,?,?)", (conn_id, chat_id, message_id, from_id, time.time()))


async def chat_msg_ids(conn_id, chat_id):
    rows = await fetchall("SELECT message_id FROM msgs WHERE conn_id=? AND chat_id=?", (conn_id, chat_id))
    return [r["message_id"] for r in rows]


async def clear_chat_msgs(conn_id, chat_id):
    await execute("DELETE FROM msgs WHERE conn_id=? AND chat_id=?", (conn_id, chat_id))
