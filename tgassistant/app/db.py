import json
import time

import aiosqlite

from . import config

_db: aiosqlite.Connection | None = None
MODS: set[int] = set()  # мини-админы (кэш)

SCHEMA = """
CREATE TABLE IF NOT EXISTS connections(conn_id TEXT PRIMARY KEY, user_id INTEGER, first_name TEXT, last_name TEXT, ts REAL);
CREATE TABLE IF NOT EXISTS subs(user_id INTEGER PRIMARY KEY, tier INTEGER, until REAL);
CREATE TABLE IF NOT EXISTS settings(user_id INTEGER, key TEXT, value TEXT, PRIMARY KEY(user_id, key));
CREATE TABLE IF NOT EXISTS chatset(conn_id TEXT, chat_id INTEGER, key TEXT, value TEXT, PRIMARY KEY(conn_id, chat_id, key));
CREATE TABLE IF NOT EXISTS msgs(conn_id TEXT, chat_id INTEGER, message_id INTEGER, from_id INTEGER, ts REAL);
CREATE TABLE IF NOT EXISTS reminders(id INTEGER PRIMARY KEY AUTOINCREMENT, owner_id INTEGER, due REAL, text TEXT);
CREATE TABLE IF NOT EXISTS saved(conn_id TEXT, chat_id INTEGER, message_id INTEGER, from_id INTEGER, from_name TEXT, kind TEXT, text TEXT, file_id TEXT, ts REAL, PRIMARY KEY(conn_id, chat_id, message_id));
CREATE TABLE IF NOT EXISTS mods(user_id INTEGER PRIMARY KEY);
CREATE INDEX IF NOT EXISTS msgs_idx ON msgs(conn_id, chat_id);
"""


async def init(path: str):
    global _db
    _db = await aiosqlite.connect(path)
    _db.row_factory = aiosqlite.Row
    await _db.executescript(SCHEMA)
    await _db.execute("DELETE FROM msgs WHERE ts < ?", (time.time() - 30 * 86400,))
    await _db.execute("DELETE FROM saved WHERE ts < ?", (time.time() - 7 * 86400,))
    await _db.commit()
    MODS.clear()
    MODS.update(r["user_id"] for r in await fetchall("SELECT user_id FROM mods"))


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
async def save_conn(conn_id, user_id, first, last):
    await execute("INSERT OR REPLACE INTO connections VALUES(?,?,?,?,?)", (conn_id, user_id, first or "", last or "", time.time()))


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
