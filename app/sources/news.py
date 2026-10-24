"""RSS news feeds (news sites + Trump's Truth Social mirror)."""
import asyncio
import calendar
import html
import re
import time

import feedparser
import httpx

UA = {"User-Agent": "Mozilla/5.0 (3Agents market monitor)"}


def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


async def fetch_feed(url: str, source: str | None = None, max_age_h: float = 3) -> list[dict]:
    try:
        async with httpx.AsyncClient(timeout=15, headers=UA, follow_redirects=True) as c:
            r = await c.get(url)
            r.raise_for_status()
        parsed = await asyncio.to_thread(feedparser.parse, r.content)
    except Exception as e:  # noqa: BLE001
        return [{"error": f"{url}: {e}"}]

    cutoff = time.time() - max_age_h * 3600
    name = source or (parsed.feed.get("title") or url.split("/")[2])
    items = []
    for e in parsed.entries[:40]:
        t = e.get("published_parsed") or e.get("updated_parsed")
        ts = calendar.timegm(t) if t else time.time()
        if ts < cutoff:
            continue
        title = _clean(e.get("title", ""))
        summary = _clean(e.get("summary", ""))[:300]
        items.append({
            "id": e.get("id") or e.get("link") or title,
            "source": name[:40],
            "text": title if not summary or summary.startswith(title[:30]) else f"{title} — {summary}",
            "ts": ts,
            "url": e.get("link", ""),
        })
    return items


async def fetch_many(urls: list[str], max_age_h: float = 3) -> tuple[list[dict], list[str]]:
    results = await asyncio.gather(*(fetch_feed(u, max_age_h=max_age_h) for u in urls))
    items, errors = [], []
    for res in results:
        for it in res:
            (errors if "error" in it else items).append(it["error"] if "error" in it else it)
    items.sort(key=lambda x: x["ts"], reverse=True)
    return items, errors
