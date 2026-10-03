import html
from dataclasses import dataclass
from typing import Callable

TIERS = {0: "FREE", 1: "PREMIUM", 2: "VIP"}

SECTIONS = {
    "info": ("ℹ️", "Основные"),
    "utils": ("🧰", "Утилиты"),
    "fun": ("🎲", "Развлечения"),
    "games": ("🎮", "Игры"),
    "anim": ("✨", "Анимации"),
    "media": ("🎞", "Медиа"),
    "series": ("🔥", "Серии"),
    "mod": ("🛡", "Модерация"),
    "profile": ("👤", "Профиль и авто"),
    "manage": ("⚙️", "Управление"),
}


@dataclass
class Cmd:
    names: tuple
    fn: Callable
    tier: int
    section: str
    usage: str
    help: str
    hidden: bool = False


REG: dict[str, Cmd] = {}
CMDS: list[Cmd] = []


def command(*names, tier=0, section="info", usage="", help="", hidden=False):
    def deco(fn):
        c = Cmd(names, fn, tier, section, usage, help, hidden)
        CMDS.append(c)
        for n in names:
            REG[n.lower()] = c
        return fn
    return deco


def section_cmds(sec):
    return [c for c in CMDS if c.section == sec and not c.hidden]


def section_text(sec: str) -> str:
    icon, title = SECTIONS[sec]
    cmds = section_cmds(sec)
    lines = [f"{icon} <b>{title}</b>", ""]
    for c in cmds:
        usage = f" {html.escape(c.usage)}" if c.usage else ""
        alias = "".join(f" / <code>.{n}</code>" for n in c.names[1:])
        lines.append(f"<code>.{c.names[0]}{usage}</code>{alias} — {html.escape(c.help)}")
    top = max((c.tier for c in cmds), default=0)
    if top:
        lines += ["", f"🔒 Нужен тариф {TIERS[top]}"]
    return "\n".join(lines)
