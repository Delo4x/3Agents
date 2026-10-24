"""Reads X (Twitter) with the session cookies of a separate X account.

Needs X_AUTH_TOKEN and X_CT0. If they are missing, X is simply skipped and
the agents work on news feeds only.
"""
import time
from datetime import datetime

from .. import config

_client = None
_user_ids: dict[str, str] = {}
_blocked_until = 0.0


def enabled() -> bool:
    return bool(config.X_AUTH_TOKEN and config.X_CT0)


def _get():
    global _client
    if _client is None:
        from twikit import Client
        _client = Client("en-US")
        _client.set_cookies({"auth_token": config.X_AUTH_TOKEN, "ct0": config.X_CT0})
    return _client


def _ts(tweet) -> float:
    for attr in ("created_at_datetime",):
        v = getattr(tweet, attr, None)
        if isinstance(v, datetime):
            return v.timestamp()
    try:
        return datetime.strptime(tweet.created_at, "%a %b %d %H:%M:%S %z %Y").timestamp()
    except Exception:  # noqa: BLE001
        return time.time()


def _to_item(tweet, handle: str | None = None) -> dict:
    user = getattr(tweet, "user", None)
    name = handle or (getattr(user, "screen_name", None) or "X")
    return {"id": f"x:{tweet.id}", "source": f"@{name}", "text": (tweet.text or "")[:500],
            "ts": _ts(tweet), "url": f"https://x.com/{name}/status/{tweet.id}"}


def _backoff(e: Exception) -> str:
    global _blocked_until
    msg = str(e)
    if "429" in msg or "Rate" in type(e).__name__:
        _blocked_until = time.time() + 15 * 60
        return "X: för många anrop, pausar X i 15 min"
    if "401" in msg or "403" in msg or "Unauthorized" in type(e).__name__:
        _blocked_until = time.time() + 60 * 60
        return "X: cookies fungerar inte (utloggad?). Byt X_AUTH_TOKEN/X_CT0."
    return f"X-fel: {msg[:150]}"


async def user_tweets(handles: list[str], per_user: int = 10, max_age_h: float = 3):
    if not enabled() or time.time() < _blocked_until:
        return [], []
    items, errors = [], []
    cutoff = time.time() - max_age_h * 3600
    c = _get()
    for h in handles:
        try:
            if h not in _user_ids:
                _user_ids[h] = (await c.get_user_by_screen_name(h)).id
            tweets = await c.get_user_tweets(_user_ids[h], "Tweets", count=per_user)
            for t in tweets:
                it = _to_item(t, h)
                if it["ts"] >= cutoff:
                    items.append(it)
        except Exception as e:  # noqa: BLE001
            errors.append(_backoff(e))
            if time.time() < _blocked_until:
                break
    return items, errors


async def search(queries: list[str], per_query: int = 15, max_age_h: float = 2):
    if not enabled() or time.time() < _blocked_until:
        return [], []
    items, errors = [], []
    cutoff = time.time() - max_age_h * 3600
    c = _get()
    for q in queries:
        try:
            tweets = await c.search_tweet(f"{q} lang:en -filter:replies", "Latest", count=per_query)
            for t in tweets:
                it = _to_item(t)
                if it["ts"] >= cutoff:
                    items.append(it)
        except Exception as e:  # noqa: BLE001
            errors.append(_backoff(e))
            if time.time() < _blocked_until:
                break
    return items, errors
