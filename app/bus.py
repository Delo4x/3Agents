"""Tiny pub/sub so the website gets live updates (Server-Sent Events)."""
import asyncio

from . import db

_subscribers: set[asyncio.Queue] = set()

# Live status of each agent, shown on the dashboard cards.
status: dict[str, dict] = {
    "scout": {"state": "idle", "activity": "Väntar på första rundan"},
    "hunter": {"state": "idle", "activity": "Väntar på första rundan"},
    "analyst": {"state": "idle", "activity": "Väntar på första rundan"},
    "system": {"state": "idle", "activity": "Startar"},
}


def subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=500)
    _subscribers.add(q)
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    _subscribers.discard(q)


def _broadcast(msg: dict) -> None:
    for q in list(_subscribers):
        try:
            q.put_nowait(msg)
        except asyncio.QueueFull:
            pass


def emit(agent: str, kind: str, text: str, data: dict | None = None) -> None:
    """Save an event and push it to everyone watching the site."""
    ev = db.add_event(agent, kind, text, data)
    _broadcast({"type": "event", "event": ev})


_warned: dict[str, float] = {}


def warn_once(agent: str, text: str, every_s: int = 3600) -> None:
    """Same warning at most once per hour, so the live feed is not spammed."""
    import time
    key = f"{agent}:{text[:80]}"
    if time.time() - _warned.get(key, 0) < every_s:
        return
    _warned[key] = time.time()
    emit(agent, "warn", text)


def set_status(agent: str, state: str, activity: str) -> None:
    status[agent] = {"state": state, "activity": activity}
    _broadcast({"type": "status", "agent": agent, "status": status[agent]})


def push(msg: dict) -> None:
    _broadcast(msg)
