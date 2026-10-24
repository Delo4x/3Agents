"""Consensus + paper trading (test money, no real orders)."""
import calendar
import time

from . import bus, config, db
from .agents import SYMS


def balance() -> float:
    row = db.query("SELECT COALESCE(SUM(pnl),0) AS p FROM trades WHERE status='closed'")
    return config.START_BALANCE + row[0]["p"]


def open_trades() -> list[dict]:
    return db.query("SELECT * FROM trades WHERE status='open' ORDER BY id")


def risk_pct(avg: float) -> float:
    """70 -> RISK_MIN_PCT, 90+ -> RISK_MAX_PCT, linear in between."""
    lo, hi = config.AVG_MIN_CONF, 90
    f = max(0.0, min(1.0, (avg - lo) / max(1, hi - lo)))
    return round(config.RISK_MIN_PCT + f * (config.RISK_MAX_PCT - config.RISK_MIN_PCT), 2)


def consensus(scout: dict, hunter: dict, analyst: dict) -> dict:
    """Per symbol: decision + why."""
    out = {}
    for s in SYMS:
        ops = {"scout": scout[s], "hunter": hunter[s], "analyst": analyst[s]}
        biases = {o["bias"] for o in ops.values()}
        avg = round(sum(o["confidence"] for o in ops.values()) / 3, 1)
        a = ops["analyst"]
        if a["bias"] == "NEUTRAL" or a["confidence"] < config.ANALYST_MIN_CONF:
            dec, why = "NO", f"The Analyst säger nej ({a['bias']} {a['confidence']}%)"
        elif len(biases) != 1:
            dec, why = "NO", "Agenterna är inte överens"
        elif avg < config.AVG_MIN_CONF:
            dec, why = "NO", f"Alla överens men snittet {avg}% är under {config.AVG_MIN_CONF}%"
        else:
            dec, why = a["bias"], f"Alla tre säger {a['bias']} · snitt {avg}%"
        out[s] = {"decision": dec, "why": why, "avg": avg,
                  "votes": {k: {"bias": v["bias"], "confidence": v["confidence"]} for k, v in ops.items()}}
    return out


def manage_open(market: dict, analyst_op: dict) -> None:
    """Check stop loss / take profit on the newest 5min candles, and early exit."""
    for t in open_trades():
        m = market.get(t["symbol"])
        if not m:
            continue
        since = t["opened_ts"]
        exit_price, why = None, ""
        for c in m["candles5"][-3:]:
            # candle start time (UTC); only candles that started after the entry count
            ct = calendar.timegm(time.strptime(c["t"][:19], "%Y-%m-%d %H:%M:%S"))
            if ct < since - 60:
                continue
            if t["side"] == "BUY":
                if c["l"] <= t["sl"]:
                    exit_price, why = t["sl"], "Stop loss träffad"
                elif c["h"] >= t["tp"]:
                    exit_price, why = t["tp"], "Take profit träffad 🎯"
            else:
                if c["h"] >= t["sl"]:
                    exit_price, why = t["sl"], "Stop loss träffad"
                elif c["l"] <= t["tp"]:
                    exit_price, why = t["tp"], "Take profit träffad 🎯"
            if exit_price:
                break
        a = analyst_op.get(t["symbol"], {})
        opposite = "SELL" if t["side"] == "BUY" else "BUY"
        if not exit_price and a.get("bias") == opposite and a.get("confidence", 0) >= 70:
            exit_price, why = m["price"], f"The Analyst vände till {opposite} ({a['confidence']}%) – stänger tidigt"
        if exit_price:
            close(t, exit_price, why)


def close(t: dict, price: float, why: str) -> None:
    d = 1 if t["side"] == "BUY" else -1
    pnl = round((price - t["entry"]) * t["units"] * d, 2)
    db.execute("UPDATE trades SET status='closed', closed_ts=?, exit=?, pnl=?, close_reason=? WHERE id=?",
               (time.time(), price, pnl, why, t["id"]))
    bal = balance()
    db.execute("INSERT OR REPLACE INTO equity (ts, balance) VALUES (?,?)", (time.time(), bal))
    bus.emit("system", "close", f"Stängde {t['side']} {t['symbol']} @ {price:.2f} · {why} · "
             f"{'+' if pnl >= 0 else ''}{pnl:.2f} USD", {"trade_id": t["id"], "pnl": pnl})
    bus.push({"type": "trades"})


def act(decisions: dict, market: dict) -> None:
    held = {t["symbol"] for t in open_trades()}
    for s, d in decisions.items():
        if d["decision"] not in ("BUY", "SELL") or s in held or s not in market:
            continue
        m = market[s]
        price, atr = m["price"], m["atr_1h"]
        if atr <= 0:
            continue
        sl_dist = atr * config.SL_ATR_MULT
        side = d["decision"]
        sl = price - sl_dist if side == "BUY" else price + sl_dist
        tp = price + sl_dist * config.RR if side == "BUY" else price - sl_dist * config.RR
        rp = risk_pct(d["avg"])
        risk_usd = balance() * rp / 100
        units = round(risk_usd / sl_dist, 4)
        tid = db.execute(
            "INSERT INTO trades (symbol, side, units, entry, sl, tp, opened_ts, status, confidence, risk_pct, reason)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (s, side, units, price, sl, tp, time.time(), "open", d["avg"], rp, d["why"]))
        bus.emit("system", "open",
                 f"ÖPPNADE {side} {s} @ {price:.2f} · SL {sl:.2f} · TP {tp:.2f} · risk {rp}% "
                 f"({risk_usd:.0f} USD) · {d['why']}", {"trade_id": tid})
        bus.push({"type": "trades"})
