"""Plain technical facts the Analyst reads: trend, momentum, volatility, levels."""


def ema(values: list[float], n: int) -> list[float]:
    k = 2 / (n + 1)
    out, prev = [], values[0]
    for v in values:
        prev = v * k + prev * (1 - k)
        out.append(prev)
    return out


def rsi(closes: list[float], n: int = 14) -> float:
    if len(closes) <= n:
        return 50.0
    gains, losses = 0.0, 0.0
    for i in range(1, n + 1):
        d = closes[i] - closes[i - 1]
        gains += max(d, 0)
        losses += max(-d, 0)
    ag, al = gains / n, losses / n
    for i in range(n + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        ag = (ag * (n - 1) + max(d, 0)) / n
        al = (al * (n - 1) + max(-d, 0)) / n
    return 100.0 if al == 0 else 100 - 100 / (1 + ag / al)


def atr(c: list[dict], n: int = 14) -> float:
    trs = []
    for i in range(1, len(c)):
        trs.append(max(c[i]["h"] - c[i]["l"], abs(c[i]["h"] - c[i - 1]["c"]), abs(c[i]["l"] - c[i - 1]["c"])))
    if not trs:
        return 0.0
    val = sum(trs[:n]) / min(n, len(trs))
    for tr in trs[n:]:
        val = (val * (n - 1) + tr) / n
    return val


def swings(c: list[dict], look: int = 3) -> tuple[list[float], list[float]]:
    highs, lows = [], []
    for i in range(look, len(c) - look):
        if all(c[i]["h"] >= c[j]["h"] for j in range(i - look, i + look + 1)):
            highs.append(c[i]["h"])
        if all(c[i]["l"] <= c[j]["l"] for j in range(i - look, i + look + 1)):
            lows.append(c[i]["l"])
    return highs, lows


def structure(c: list[dict]) -> str:
    highs, lows = swings(c)
    if len(highs) < 2 or len(lows) < 2:
        return "oklar"
    hh, hl = highs[-1] > highs[-2], lows[-1] > lows[-2]
    if hh and hl:
        return "upptrend (högre toppar och bottnar)"
    if not hh and not hl:
        return "nedtrend (lägre toppar och bottnar)"
    return "sidled/blandad"


def summarize(c: list[dict], label: str) -> dict:
    closes = [x["c"] for x in c]
    e20, e50 = ema(closes, 20)[-1], ema(closes, 50)[-1]
    highs, lows = swings(c)
    last = closes[-1]
    day = c[-min(len(c), 24 if label == "1h" else 96):]
    return {
        "timeframe": label,
        "last": round(last, 3),
        "ema20": round(e20, 3),
        "ema50": round(e50, 3),
        "rsi14": round(rsi(closes), 1),
        "atr14": round(atr(c), 3),
        "structure": structure(c),
        "change_last_10_bars_pct": round((last / closes[-11] - 1) * 100, 3) if len(closes) > 11 else 0,
        "recent_swing_high": round(highs[-1], 3) if highs else None,
        "recent_swing_low": round(lows[-1], 3) if lows else None,
        "range_high": round(max(x["h"] for x in day), 3),
        "range_low": round(min(x["l"] for x in day), 3),
        "last_5_candles": [{k: round(v, 3) if isinstance(v, float) else v for k, v in x.items()} for x in c[-5:]],
    }
