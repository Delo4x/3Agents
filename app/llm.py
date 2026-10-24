"""Calls Claude and gets back a strict JSON opinion."""
import json
import random
import re

from . import config

_client = None


def _get_client():
    global _client
    if _client is None:
        from anthropic import AsyncAnthropic
        _client = AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
    return _client


OPINION_FORMAT = """
Svara ENDAST med JSON i exakt detta format (inga andra ord):
{
  "XAUUSD": {"bias": "BUY" | "SELL" | "NEUTRAL", "confidence": 0-100, "reason": "kort, enkel svenska, max 2 meningar"},
  "OIL":    {"bias": "BUY" | "SELL" | "NEUTRAL", "confidence": 0-100, "reason": "kort, enkel svenska, max 2 meningar"},
  "summary": "en mening om vad du ser just nu",
  "highlights": ["upp till 3 viktigaste sakerna du såg, korta"]
}
Regler för confidence: 0-40 = svag/osäker, 40-70 = måttlig, 70-85 = stark, 85+ = mycket stark och tydlig.
Var ärlig. Om du inte ser något tydligt: NEUTRAL med låg confidence. Gissa aldrig. Bygg bara på fakta du fått, inte känslor.
"""


def _parse(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("no JSON in reply")
    data = json.loads(m.group(0))
    for sym in ("XAUUSD", "OIL"):
        o = data.get(sym) or {}
        bias = str(o.get("bias", "NEUTRAL")).upper()
        if bias not in ("BUY", "SELL", "NEUTRAL"):
            bias = "NEUTRAL"
        try:
            conf = int(max(0, min(100, float(o.get("confidence", 0)))))
        except (TypeError, ValueError):
            conf = 0
        data[sym] = {"bias": bias, "confidence": conf, "reason": str(o.get("reason", ""))[:400]}
    data["summary"] = str(data.get("summary", ""))[:400]
    data["highlights"] = [str(h)[:200] for h in (data.get("highlights") or [])][:3]
    return data


async def opinion(model: str, system: str, user: str) -> dict:
    if config.demo_llm():
        return _demo_opinion()
    resp = await _get_client().messages.create(
        model=model,
        max_tokens=800,
        system=system + "\n" + OPINION_FORMAT,
        messages=[{"role": "user", "content": user}],
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    return _parse(text)


def _demo_opinion() -> dict:
    def one():
        bias = random.choice(["BUY", "BUY", "SELL", "NEUTRAL"])
        return {"bias": bias, "confidence": random.randint(35, 95),
                "reason": "DEMO: slumpad åsikt eftersom ingen Anthropic-nyckel finns."}
    return {"XAUUSD": one(), "OIL": one(), "summary": "Demoläge – ingen riktig analys.",
            "highlights": ["Demoläge aktivt"]}
