"""Price candles from Twelve Data (free plan: 800 calls/day, 8/min).

Budget: 5min candles for 2 symbols every 5 min (~576/day) + 1h candles
once per hour (~48/day) = about 620 calls/day.
"""
import math
import random
import time

import httpx

from .. import config

_cache: dict[tuple[str, str], tuple[float, list[dict]]] = {}
TTL = {"5min": 4 * 60, "1h": 55 * 60}


async def candles(key: str, interval: str, size: int = 150) -> list[dict]:
    """Oldest -> newest list of {t, o, h, l, c}."""
    ck = (key, interval)
    hit = _cache.get(ck)
    if hit and time.time() - hit[0] < TTL.get(interval, 240):
        return hit[1]
    if config.demo_prices():
        data = _demo(key, interval, size)
    else:
        data = await _twelvedata(config.SYMBOLS[key], interval, size)
    _cache[ck] = (time.time(), data)
    return data


async def _twelvedata(symbol: str, interval: str, size: int) -> list[dict]:
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get("https://api.twelvedata.com/time_series", params={
            "symbol": symbol, "interval": interval, "outputsize": size,
            "apikey": config.TWELVEDATA_API_KEY, "timezone": "UTC",
        })
        j = r.json()
    if j.get("status") == "error" or "values" not in j:
        raise RuntimeError(f"Twelve Data {symbol} {interval}: {j.get('message', j)}")
    out = [{"t": v["datetime"], "o": float(v["open"]), "h": float(v["high"]),
            "l": float(v["low"]), "c": float(v["close"])} for v in j["values"]]
    return list(reversed(out))


# --- Demo random walk ---------------------------------------------------
_demo_state: dict[str, float] = {"XAUUSD": 4000.0, "OIL": 65.0}


def _demo(key: str, interval: str, size: int) -> list[dict]:
    step = 300 if interval == "5min" else 3600
    vol = 0.0012 if interval == "5min" else 0.004
    now = int(time.time() // step * step)
    _demo_state[key] *= 1 + random.gauss(0, vol)
    price = _demo_state[key]
    rng = random.Random(f"{key}{interval}{now // 86400}")
    series, p = [], price
    for i in range(size):
        o = p
        c = o * (1 + rng.gauss(0, vol)) + math.sin(i / 9) * o * vol * 0.3
        h, l = max(o, c) * (1 + abs(rng.gauss(0, vol / 2))), min(o, c) * (1 - abs(rng.gauss(0, vol / 2)))
        series.append({"t": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(now - (size - i) * step)),
                       "o": o, "h": h, "l": l, "c": c})
        p = c
    # shift so the last close equals current demo price
    shift = price - series[-1]["c"]
    for s in series:
        for k in "ohlc":
            s[k] += shift
    return series
