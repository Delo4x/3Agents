"""Web server + the 24/5 loop that runs the three agents."""
import asyncio
import base64
import json
import secrets
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import bus, config, db, engine
from .agents import Analyst, Hunter, Scout

STATIC = Path(__file__).parent / "static"

scout, hunter, analyst = Scout(), Hunter(), Analyst()
AGENTS = [scout, hunter, analyst]
state = {"decisions": {}, "last_cycle": 0.0, "next_cycle": 0.0, "cycle": 0, "market_open": False,
         "prices": {}}


def market_open(now: datetime | None = None) -> bool:
    if config.ALWAYS_OPEN:
        return True
    now = now or datetime.now(ZoneInfo(config.TIMEZONE))
    wd = now.weekday()  # 0 = Monday
    if wd >= 5:
        return False
    if wd == 4 and now.hour >= config.CLOSE_FRIDAY_HOUR:
        return False
    return True


_cycle_lock = asyncio.Lock()


async def run_cycle() -> None:
    if _cycle_lock.locked():
        return
    async with _cycle_lock:
        await _run_cycle()


async def _run_cycle() -> None:
    state["cycle"] += 1
    bus.set_status("system", "working", f"Runda {state['cycle']} pågår")
    # News agents and the analyst work at the same time, each on its own.
    results = await asyncio.gather(scout.run(), hunter.run(), analyst.run(), return_exceptions=True)
    for a, r in zip(AGENTS, results):
        if isinstance(r, Exception):
            bus.emit(a.key, "error", f"Kraschade i rundan: {r}")
            bus.set_status(a.key, "error", "Fel – försöker igen nästa runda")
    if analyst.market:
        state["prices"] = {s: m["price"] for s, m in analyst.market.items()}
        engine.manage_open(analyst.market, analyst.opinion)
    decisions = engine.consensus(scout.opinion, hunter.opinion, analyst.opinion)
    state["decisions"] = decisions
    bus.push({"type": "decisions", "decisions": decisions})
    sv = {"BUY": "KÖP", "SELL": "SÄLJ", "NO": "NEJ"}
    names = {"XAUUSD": "Guld", "OIL": "Olja"}
    summary = " · ".join(f"{names[s]}: {sv[d['decision']]}" for s, d in decisions.items())
    bus.emit("system", "decision", f"Beslut runda {state['cycle']}: {summary}", decisions)
    if analyst.market:
        engine.act(decisions, analyst.market)
    db.execute("INSERT OR REPLACE INTO equity (ts, balance) VALUES (?,?)", (time.time(), engine.balance()))
    state["last_cycle"] = time.time()


async def loop() -> None:
    await asyncio.sleep(2)
    mode = []
    if config.demo_llm():
        mode.append("AI i DEMO (ingen ANTHROPIC_API_KEY)")
    if config.demo_prices():
        mode.append("priser i DEMO (ingen TWELVEDATA_API_KEY)")
    bus.emit("system", "start", "Systemet startade. Testläge: papperstrading, inga riktiga order."
             + (" · " + ", ".join(mode) if mode else ""))
    was_open = None
    while True:
        is_open = market_open()
        state["market_open"] = is_open
        if is_open != was_open and was_open is not None:
            bus.emit("system", "market", "Marknaden öppnade – agenterna börjar jobba" if is_open
                     else "Helg – marknaden stängd, agenterna vilar")
        was_open = is_open
        if is_open:
            try:
                await run_cycle()
            except Exception as e:  # noqa: BLE001
                bus.emit("system", "error", f"Rundan misslyckades: {e}")
            if state["cycle"] % 50 == 0:
                db.prune()
        else:
            for a in ("scout", "hunter", "analyst"):
                bus.set_status(a, "sleeping", "Helg – vilar till måndag")
        wait = config.CYCLE_MINUTES * 60
        state["next_cycle"] = time.time() + wait
        bus.set_status("system", "idle", "Väntar på nästa runda" if is_open else "Helgvila")
        bus.push({"type": "tick", "next_cycle": state["next_cycle"], "market_open": is_open})
        await asyncio.sleep(wait)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.conn()
    task = asyncio.create_task(loop())
    yield
    task.cancel()


app = FastAPI(title="3Agents", lifespan=lifespan)


@app.middleware("http")
async def password(request: Request, call_next):
    if config.DASHBOARD_PASSWORD and request.url.path != "/health":
        ok = False
        auth = request.headers.get("authorization", "")
        if auth.startswith("Basic "):
            try:
                _, pw = base64.b64decode(auth[6:]).decode().split(":", 1)
                ok = secrets.compare_digest(pw, config.DASHBOARD_PASSWORD)
            except Exception:  # noqa: BLE001
                ok = False
        if not ok:
            return Response("Lösenord krävs", status_code=401,
                            headers={"WWW-Authenticate": 'Basic realm="3Agents"'})
    return await call_next(request)


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")


def _trades():
    rows = db.query("SELECT * FROM trades ORDER BY id DESC LIMIT 100")
    prices = state["prices"]
    for t in rows:
        if t["status"] == "open" and t["symbol"] in prices:
            d = 1 if t["side"] == "BUY" else -1
            t["live_pnl"] = round((prices[t["symbol"]] - t["entry"]) * t["units"] * d, 2)
    return rows


@app.get("/api/state")
def api_state():
    closed = db.query("SELECT pnl FROM trades WHERE status='closed'")
    wins = sum(1 for t in closed if t["pnl"] > 0)
    return {
        "agents": [a.public() for a in AGENTS],
        "system": bus.status["system"],
        "decisions": state["decisions"],
        "prices": state["prices"],
        "market_open": state["market_open"],
        "next_cycle": state["next_cycle"],
        "cycle": state["cycle"],
        "balance": round(engine.balance(), 2),
        "start_balance": config.START_BALANCE,
        "stats": {"trades": len(closed), "wins": wins,
                  "winrate": round(wins / len(closed) * 100, 1) if closed else None},
        "rules": {"analyst_min": config.ANALYST_MIN_CONF, "avg_min": config.AVG_MIN_CONF,
                  "risk_min": config.RISK_MIN_PCT, "risk_max": config.RISK_MAX_PCT, "rr": config.RR},
        "demo": {"llm": config.demo_llm(), "prices": config.demo_prices()},
        "x_connected": bool(config.X_AUTH_TOKEN and config.X_CT0),
        "events": db.recent_events(150),
        "trades": _trades(),
    }


@app.get("/api/trades")
def api_trades():
    return _trades()


@app.get("/api/equity")
def api_equity():
    rows = db.query("SELECT ts, balance FROM equity ORDER BY ts DESC LIMIT 2000")
    return list(reversed(rows))


@app.get("/api/history/{agent}")
def api_history(agent: str):
    return db.query("SELECT ts, symbol, bias, confidence FROM opinions WHERE agent=? "
                    "ORDER BY id DESC LIMIT 400", (agent,))


@app.post("/api/run-now")
async def run_now():
    if not market_open():
        return JSONResponse({"ok": False, "msg": "Marknaden är stängd (helg)"}, status_code=400)
    asyncio.create_task(run_cycle())
    return {"ok": True}


@app.get("/api/stream")
async def stream(request: Request):
    q = bus.subscribe()

    async def gen():
        try:
            yield "retry: 3000\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=20)
                    yield f"data: {json.dumps(msg, ensure_ascii=False, default=str)}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            bus.unsubscribe(q)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
