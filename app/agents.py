"""The three agents: The Scout, The Hunter and The Analyst."""
import json
import time
from datetime import datetime, timezone

from . import bus, config, db, indicators, llm
from .sources import news, prices, x_source

SYMS = ("XAUUSD", "OIL")


def _neutral(reason: str) -> dict:
    return {s: {"bias": "NEUTRAL", "confidence": 0, "reason": reason} for s in SYMS} | {
        "summary": reason, "highlights": []}


def _fmt_items(items: list[dict], limit: int) -> str:
    lines = []
    for it in items[:limit]:
        age = int((time.time() - it["ts"]) / 60)
        lines.append(f"- [{it['source']}, {age} min sedan] {it['text']}")
    return "\n".join(lines)


class Agent:
    key = ""
    name = ""
    model = ""
    refresh_minutes = 30    # re-think even without new info after this long
    decay = 0.95            # confidence multiplier per cycle when nothing new

    def __init__(self) -> None:
        self.opinion: dict = _neutral("Har inte kört än")
        self.updated = 0.0
        self.last_llm = 0.0

    def save(self, op: dict) -> None:
        self.opinion = op
        self.updated = time.time()
        for s in SYMS:
            o = op[s]
            db.execute("INSERT INTO opinions (ts, agent, symbol, bias, confidence, reason) VALUES (?,?,?,?,?,?)",
                       (self.updated, self.key, s, o["bias"], o["confidence"], o["reason"]))
        bus.push({"type": "opinion", "agent": self.key, "opinion": op, "ts": self.updated})

    def apply_decay(self) -> None:
        op = json.loads(json.dumps(self.opinion))
        for s in SYMS:
            op[s]["confidence"] = int(op[s]["confidence"] * self.decay)
            if op[s]["confidence"] < 15:
                op[s]["bias"] = "NEUTRAL"
        self.save(op)

    def public(self) -> dict:
        return {"key": self.key, "name": self.name, "opinion": self.opinion, "updated": self.updated,
                "status": bus.status.get(self.key)}

    async def think(self, system: str, prompt: str) -> None:
        bus.set_status(self.key, "thinking", "Tänker och väger informationen…")
        try:
            op = await llm.opinion(self.model, system, prompt)
        except Exception as e:  # noqa: BLE001
            bus.emit(self.key, "error", f"Kunde inte analysera: {e}")
            bus.set_status(self.key, "error", "Fel vid analys")
            return
        self.last_llm = time.time()
        self.save(op)
        parts = [f"{s}: {op[s]['bias']} {op[s]['confidence']}%" for s in SYMS]
        bus.emit(self.key, "opinion", f"{op['summary']}  ({' · '.join(parts)})", op)


# ---------------------------------------------------------------------------
class Scout(Agent):
    key, name = "scout", "The Scout"
    model = config.MODEL_SCOUT
    refresh_minutes = 30
    decay = 0.97

    SYSTEM = (
        "Du är The Scout, en av tre agenter i ett tradingteam som bara handlar guld (XAUUSD) och olja (WTI). "
        "Ditt jobb: läsa det breda flödet av nyheter och vad folk säger på X om världen, och bedöma hur det "
        "påverkar guld och olja de närmaste timmarna. Tänk på: dollarn, räntor/Fed, inflation, krig/oro "
        "(säker hamn = guld upp), OPEC, utbud/efterfrågan på olja, lager, sanktioner, handelskrig. "
        "Var kall och saklig. Rykten och åsikter väger mindre än bekräftade fakta. Ignorera brus och reklam."
    )

    async def run(self) -> None:
        bus.set_status(self.key, "working", "Läser nyhetsflöden och X…")
        items, errors = await news.fetch_many(config.NEWS_FEEDS, max_age_h=3)
        x_items, x_err = await x_source.search(config.SCOUT_X_QUERIES)
        items += x_items
        for e in errors + x_err:
            bus.warn_once(self.key, e)
        new = [it for it in items if db.mark_seen(f"scout:{it['id']}")]
        bus.emit(self.key, "scan",
                 f"Skannade {len(items)} inlägg/nyheter ({len(new)} nya)"
                 + ("" if x_source.enabled() else " – X ej kopplat, bara nyheter"),
                 {"items": [{"source": i["source"], "text": i["text"][:180], "url": i["url"]} for i in new[:8]]})
        stale = time.time() - self.last_llm > self.refresh_minutes * 60
        if not new and not stale:
            self.apply_decay()
            bus.set_status(self.key, "idle", "Inget nytt – håller kvar senaste bilden")
            return
        if not items:
            self.save(_neutral("Inga nyheter hittades just nu"))
            bus.set_status(self.key, "idle", "Inga nyheter")
            return
        items.sort(key=lambda x: x["ts"], reverse=True)
        prompt = (f"Tid nu (UTC): {datetime.now(timezone.utc):%Y-%m-%d %H:%M}\n\n"
                  f"NYA sedan förra rundan ({len(new)} st):\n{_fmt_items(new, 25) or '(inga)'}\n\n"
                  f"Allt från senaste timmarna:\n{_fmt_items(items, 40)}")
        await self.think(self.SYSTEM, prompt)
        bus.set_status(self.key, "idle", f"Klar. {self.opinion['summary'][:80]}")


# ---------------------------------------------------------------------------
class Hunter(Agent):
    key, name = "hunter", "The Hunter"
    model = config.MODEL_HUNTER
    refresh_minutes = 10_000   # only thinks when a big account posts something new
    decay = 0.93

    SYSTEM = (
        "Du är The Hunter, en av tre agenter i ett tradingteam som bara handlar guld (XAUUSD) och olja (WTI). "
        "Du följer BARA stora, marknadsrörande konton: Trump, FinancialJuice, FirstSquawk och Walter Bloomberg "
        "(@DeItaone). Ditt jobb: hitta rubriker som kan skapa stor volym och snabba rörelser i guld eller olja – "
        "t.ex. tullar, sanktioner, krig/fred, Fed-besked, CPI/NFP-siffror, OPEC-beslut, oljelager. "
        "Nya inlägg väger mest. Om inget av det nya påverkar guld eller olja: NEUTRAL med låg confidence. "
        "Var kall och saklig, ingen hype."
    )

    async def run(self) -> None:
        bus.set_status(self.key, "working", "Bevakar Trump, FinancialJuice, FirstSquawk, Walter Bloomberg…")
        x_items, x_err = await x_source.user_tweets(config.HUNTER_ACCOUNTS)
        truth, t_err = await news.fetch_many([config.TRUTH_FEED], max_age_h=3)
        for it in truth:
            it["source"] = "Trump (Truth Social)"
        items = sorted(x_items + truth, key=lambda x: x["ts"], reverse=True)
        for e in x_err + t_err:
            bus.warn_once(self.key, e)
        new = [it for it in items if db.mark_seen(f"hunter:{it['id']}")]
        if new:
            bus.emit(self.key, "scan", f"🎯 {len(new)} nya inlägg från stora konton",
                     {"items": [{"source": i["source"], "text": i["text"][:220], "url": i["url"]} for i in new[:8]]})
        if not new:
            if self.last_llm:
                self.apply_decay()
            else:
                self.save(_neutral("Inga nya inlägg från de stora kontona"))
            bus.set_status(self.key, "idle", f"Inga nya inlägg ({len(items)} senaste 3h)")
            return
        prompt = (f"Tid nu (UTC): {datetime.now(timezone.utc):%Y-%m-%d %H:%M}\n\n"
                  f"NYA inlägg:\n{_fmt_items(new, 20)}\n\n"
                  f"Tidigare inlägg senaste 3h (för sammanhang):\n{_fmt_items(items, 30)}\n\n"
                  f"Din förra bedömning: {json.dumps({s: self.opinion[s] for s in SYMS}, ensure_ascii=False)}")
        await self.think(self.SYSTEM, prompt)
        bus.set_status(self.key, "idle", f"Klar. {self.opinion['summary'][:80]}")


# ---------------------------------------------------------------------------
class Analyst(Agent):
    key, name = "analyst", "The Analyst"
    model = config.MODEL_ANALYST
    refresh_minutes = 0
    decay = 1.0

    SYSTEM = (
        "Du är The Analyst, den viktigaste av tre agenter i ett tradingteam som bara handlar guld (XAUUSD) och "
        "olja (WTI). Du har sista ordet: säger du nej blir det ingen trade. Du analyserar BARA själva marknaden "
        "(pris, trend, struktur, momentum, volatilitet, nivåer) – inga nyheter. Analysera marknaden generellt "
        "som en erfaren trader: vad gör priset på 1h (riktning) och 5min (timing)? Ge BUY/SELL bara när "
        "trend och timing pekar åt samma håll och priset inte står precis i en motståndsnivå/stödnivå emot dig. "
        "Hellre NEUTRAL än en dålig trade. Bara fakta från datan, inga känslor."
    )

    def __init__(self) -> None:
        super().__init__()
        self.market: dict = {}

    async def run(self) -> None:
        bus.set_status(self.key, "working", "Hämtar live-priser och läser diagrammen…")
        market = {}
        for s in SYMS:
            try:
                m5 = await prices.candles(s, "5min", 150)
                h1 = await prices.candles(s, "1h", 120)
                market[s] = {"1h": indicators.summarize(h1, "1h"), "5min": indicators.summarize(m5, "5min"),
                             "price": m5[-1]["c"], "atr_1h": indicators.atr(h1), "candles5": m5}
            except Exception as e:  # noqa: BLE001
                bus.warn_once(self.key, f"Pris saknas för {s}: {e}")
        self.market = market
        if not market:
            self.save(_neutral("Inga prisdata – säger NEJ till allt"))
            bus.set_status(self.key, "error", "Inga prisdata")
            return
        bus.push({"type": "prices", "prices": {s: market[s]["price"] for s in market}})
        facts = {s: {"1h": market[s]["1h"], "5min": market[s]["5min"]} for s in market}
        bus.emit(self.key, "scan", "Läste diagram: " + " · ".join(
            f"{s} {market[s]['price']:.2f} (1h {market[s]['1h']['structure'].split(' ')[0]}, "
            f"RSI {market[s]['5min']['rsi14']})" for s in market))
        prompt = (f"Tid nu (UTC): {datetime.now(timezone.utc):%Y-%m-%d %H:%M}\n"
                  f"Marknadsdata (JSON):\n{json.dumps(facts, ensure_ascii=False)}")
        await self.think(self.SYSTEM, prompt)
        for s in SYMS:
            if s not in market:
                self.opinion[s] = {"bias": "NEUTRAL", "confidence": 0, "reason": "Inga prisdata"}
        bus.set_status(self.key, "idle", f"Klar. {self.opinion['summary'][:80]}")
