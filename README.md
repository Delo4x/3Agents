# 3Agents – The Scout, The Hunter, The Analyst

Tre AI-agenter som bevakar **guld (XAUUSD)** och **olja (WTI)** dygnet runt, måndag–fredag,
och handlar med **låtsaspengar** (papperstrading). Allt syns live på en hemsida.

| Agent | Jobb | Källor |
|---|---|---|
| **The Scout** | Läser det breda flödet och bedömer hur världen påverkar guld/olja | Nyhets-RSS + sök på X |
| **The Hunter** | Bevakar bara stora konton som rör marknaden | Trump (Truth Social + X), @financialjuice, @FirstSquawk, @DeItaone |
| **The Analyst** | Läser själva priset live (1h trend + 5min timing). Har sista ordet | Twelve Data |

## Hur ett beslut tas (var 5:e minut)

1. Alla tre jobbar samtidigt och var för sig. Var och en ger **KÖP / SÄLJ / Avvakta** + **confidence 0–100** för guld och olja.
2. En trade öppnas bara om:
   - alla tre säger **samma riktning**,
   - The Analyst har **minst 65%** (säger han nej blir det nej),
   - **snittet** av alla tre är **minst 70%**.
3. Positionsstorlek styrs av snittet: 70% → 0,5% risk, 90%+ → 2% risk.
4. Stop loss = 1,5 × ATR (1h). Take profit = 2 × stoppet.
5. Om The Analyst vänder åt andra hållet med 70%+ stängs traden tidigt.

Alla siffror kan ändras med variabler (se `.env.example`).

## Starta på Railway

1. railway.com → **New Project → Deploy from GitHub repo** → välj `Delo4x/3Agents`.
2. **Variables** – lägg in:
   - `ANTHROPIC_API_KEY`
   - `TWELVEDATA_API_KEY`
   - `DASHBOARD_PASSWORD` (valfritt lösenord till sidan)
   - `DB_PATH=/data/agents.db`
3. **Volume** – högerklicka servicen → *Attach volume* → mount path `/data` (så historiken inte försvinner vid omstart).
4. **Settings → Networking → Generate Domain** – där är din hemsida.
5. Inloggning: valfritt användarnamn + lösenordet du satte.

Utan nycklar kör allt i **demoläge** (slumpade åsikter och priser) så du kan se att sidan funkar.

## Koppla X (valfritt)

Använd ett **separat X-konto**, inte ditt vanliga – kontot kan bli avstängt.

1. Logga in på x.com med botkontot i Chrome.
2. Tryck F12 → fliken **Application** → **Cookies** → `https://x.com`.
3. Kopiera värdet för `auth_token` → lägg in som `X_AUTH_TOKEN` i Railway.
4. Kopiera värdet för `ct0` → lägg in som `X_CT0`.
5. Logga **inte ut** från X i den webbläsaren (då slutar cookies fungera). Stäng bara fliken.

## Kostnad (ungefär)

- Twelve Data gratisplan räcker (~620 anrop/dag av 800).
- Claude: The Analyst tänker var 5:e minut, Scout/Hunter bara när något nytt händer.
  Räkna med några dollar per dag. Byt till billigare modell med `MODEL_ANALYST=claude-haiku-5-5`.

## Köra lokalt

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
# öppna http://localhost:8000
```
