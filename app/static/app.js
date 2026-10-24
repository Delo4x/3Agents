const AV = { scout: "/static/avatars/scout.svg", hunter: "/static/avatars/hunter.svg", analyst: "/static/avatars/analyst.svg" };
const NAMES = { scout: "The Scout", hunter: "The Hunter", analyst: "The Analyst", system: "Beslut" };
const SYM = { XAUUSD: { label: "Guld", cls: "gold" }, OIL: { label: "Olja", cls: "oil" } };
const BIAS_SV = { BUY: "KÖP", SELL: "SÄLJ", NEUTRAL: "Avvakta", NO: "NEJ" };
const COLOR = { BUY: "var(--buy)", SELL: "var(--sell)", NEUTRAL: "var(--neutral)" };

let S = null;
let filter = "all";
const $ = (s, el = document) => el.querySelector(s);
const esc = (t) => String(t ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const money = (v) => (v == null ? "–" : v.toLocaleString("sv-SE", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + " $");
const clock = (ts) => new Date(ts * 1000).toLocaleTimeString("sv-SE", { hour: "2-digit", minute: "2-digit" });
const ago = (ts) => {
  if (!ts) return "aldrig";
  const s = Math.round(Date.now() / 1000 - ts);
  if (s < 60) return "nyss";
  if (s < 3600) return `${Math.round(s / 60)} min sedan`;
  return `${Math.round(s / 3600)} h sedan`;
};

async function load() {
  const r = await fetch("/api/state");
  S = await r.json();
  renderAll();
}

function renderAll() {
  renderTop();
  S.agents.forEach(renderAgent);
  renderVerdicts();
  renderFeed();
  renderTrades();
  loadEquity();
}

function renderTop() {
  $("#market").textContent = S.market_open ? "Öppen" : "Helg";
  $("#balance").textContent = money(S.balance);
  $("#winrate").textContent = S.stats.winrate == null ? "–" : `${S.stats.winrate}% (${S.stats.trades})`;
  const f = [`<span class="flag ok">Testläge – låtsaspengar</span>`];
  if (S.demo.llm) f.push(`<span class="flag warn">AI i demoläge: lägg in ANTHROPIC_API_KEY</span>`);
  if (S.demo.prices) f.push(`<span class="flag warn">Priser i demoläge: lägg in TWELVEDATA_API_KEY</span>`);
  f.push(S.x_connected ? `<span class="flag ok">X kopplat</span>` : `<span class="flag">X ej kopplat – nyhetsflöden används</span>`);
  $("#flags").innerHTML = f.join("");
  const r = S.rules;
  $("#rules").textContent = `Regel: alla tre måste säga samma sak. The Analyst behöver minst ${r.analyst_min}%, snittet minst ${r.avg_min}%. Högre snitt ger större position (${r.risk_min}–${r.risk_max}% risk). Vinstmål ${r.rr}× stoppet.`;
}

function renderAgent(a) {
  const el = $(`.agent[data-agent="${a.key}"]`);
  if (!el) return;
  el.dataset.state = a.status?.state || "idle";
  $(".activity", el).textContent = a.status?.activity || "";
  const op = a.opinion || {};
  $(".views", el).innerHTML = Object.keys(SYM).map((s) => {
    const o = op[s] || { bias: "NEUTRAL", confidence: 0, reason: "" };
    return `<div class="view">
      <span class="sym ${SYM[s].cls}">${SYM[s].label}</span>
      <span class="bias ${o.bias}">${BIAS_SV[o.bias]}</span>
      <span class="bar"><i style="width:${o.confidence}%;background:${COLOR[o.bias]}"></i></span>
      <span class="pct">${o.confidence}%</span>
      ${o.reason ? `<p class="reason">${esc(o.reason)}</p>` : ""}
    </div>`;
  }).join("");
  $(".summary", el).textContent = op.summary || "";
  $(".updated", el).textContent = `Senaste bedömning: ${ago(a.updated)}`;
  el.dataset.updated = a.updated || 0;
}

function renderVerdicts() {
  document.querySelectorAll(".verdict").forEach((el) => {
    const s = el.dataset.sym;
    const d = S.decisions?.[s];
    const price = S.prices?.[s];
    const votes = d ? d.votes : Object.fromEntries(S.agents.map((a) => [a.key, a.opinion[s]]));
    el.classList.toggle("live", !!d && d.decision !== "NO");
    el.innerHTML = `
      <div><div class="name" style="color:var(--${SYM[s].cls})">${SYM[s].label}</div>
        <div class="price">${price ? price.toFixed(2) : "–"}</div></div>
      <div class="votes">${["scout", "hunter", "analyst"].map((k) => {
        const v = votes[k] || { bias: "NEUTRAL", confidence: 0 };
        return `<div class="vote ${v.bias}"><img src="${AV[k]}" alt="${NAMES[k]}"><b>${BIAS_SV[v.bias]} ${v.confidence}%</b></div>`;
      }).join("")}</div>
      <div class="call"><div class="word ${d ? d.decision : "NO"}">${d ? BIAS_SV[d.decision] : "–"}</div>
        <div class="why">${d ? esc(d.why) : "Väntar på första rundan"}</div></div>`;
  });
}

function feedItem(e, fresh = false) {
  const icon = e.agent === "system"
    ? `<span class="sysdot">${e.kind === "open" ? "⚡" : e.kind === "close" ? "✓" : "⚖"}</span>`
    : `<img src="${AV[e.agent]}" alt="">`;
  const items = e.data?.items?.length
    ? `<ul class="items">${e.data.items.map((i) => `<li><b>${esc(i.source)}</b>: ${i.url ? `<a href="${esc(i.url)}" target="_blank" rel="noopener">${esc(i.text)}</a>` : esc(i.text)}</li>`).join("")}</ul>`
    : "";
  const li = document.createElement("li");
  li.className = `k-${e.kind}${fresh ? " new" : ""}`;
  li.dataset.agent = e.agent;
  li.hidden = filter !== "all" && filter !== e.agent;
  li.innerHTML = `${icon}<div><div class="meta">${NAMES[e.agent] || e.agent} · ${clock(e.ts)}</div><div class="txt">${esc(e.text)}</div>${items}</div>`;
  return li;
}

function renderFeed() {
  const ol = $("#feed");
  ol.innerHTML = "";
  [...S.events].reverse().forEach((e) => ol.appendChild(feedItem(e)));
  if (!S.events.length) ol.innerHTML = `<li><span></span><p class="empty">Inget har hänt än. Första rundan startar strax.</p></li>`;
}

function renderTrades() {
  const open = S.trades.filter((t) => t.status === "open");
  const closed = S.trades.filter((t) => t.status === "closed");
  $("#open").innerHTML = open.length ? `<table><tr><th>Marknad</th><th>Riktning</th><th>Pris in</th><th>SL / TP</th><th>Nu</th></tr>
    ${open.map((t) => `<tr><td>${SYM[t.symbol].label}</td><td class="${t.side === "BUY" ? "pos" : "neg"}">${BIAS_SV[t.side]}</td>
      <td>${t.entry.toFixed(2)}</td><td>${t.sl.toFixed(2)} / ${t.tp.toFixed(2)}</td>
      <td class="${(t.live_pnl ?? 0) >= 0 ? "pos" : "neg"}">${t.live_pnl == null ? "–" : money(t.live_pnl)}</td></tr>`).join("")}</table>`
    : `<p class="empty">Inga öppna positioner. Agenterna väntar på att alla tre ska vara överens.</p>`;
  $("#closed").innerHTML = closed.length ? `<table><tr><th>Tid</th><th>Marknad</th><th>Riktning</th><th>Resultat</th><th>Varför stängd</th></tr>
    ${closed.slice(0, 25).map((t) => `<tr><td>${new Date(t.closed_ts * 1000).toLocaleString("sv-SE", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}</td>
      <td>${SYM[t.symbol].label}</td><td>${BIAS_SV[t.side]}</td>
      <td class="${t.pnl >= 0 ? "pos" : "neg"}">${money(t.pnl)}</td><td class="muted">${esc(t.close_reason)}</td></tr>`).join("")}</table>`
    : `<p class="empty">Inga avslutade trades än.</p>`;
}

async function loadEquity() {
  const rows = await (await fetch("/api/equity")).json();
  const cv = $("#equity");
  const dpr = window.devicePixelRatio || 1;
  const w = cv.clientWidth, h = 160;
  cv.width = w * dpr; cv.height = h * dpr;
  const ctx = cv.getContext("2d");
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, w, h);
  const start = S.start_balance;
  const vals = [start, ...rows.map((r) => r.balance)];
  const diff = S.balance - start;
  $("#pnlTotal").textContent = `${diff >= 0 ? "+" : ""}${money(diff)} sedan start`;
  const min = Math.min(...vals), max = Math.max(...vals);
  const pad = Math.max((max - min) * 0.15, start * 0.002);
  const y = (v) => h - 12 - ((v - (min - pad)) / (max + pad - (min - pad))) * (h - 24);
  const x = (i) => (i / Math.max(1, vals.length - 1)) * (w - 4) + 2;
  ctx.strokeStyle = "#24495A"; ctx.setLineDash([4, 4]);
  ctx.beginPath(); ctx.moveTo(0, y(start)); ctx.lineTo(w, y(start)); ctx.stroke();
  ctx.setLineDash([]);
  ctx.strokeStyle = diff >= 0 ? "#79C98F" : "#E8735F"; ctx.lineWidth = 2;
  ctx.beginPath();
  vals.forEach((v, i) => (i ? ctx.lineTo(x(i), y(v)) : ctx.moveTo(x(i), y(v))));
  ctx.stroke();
}

// countdown
setInterval(() => {
  if (!S) return;
  if (!S.market_open) { $("#countdown").textContent = "måndag"; return; }
  const s = Math.max(0, Math.round(S.next_cycle - Date.now() / 1000));
  $("#countdown").textContent = S.next_cycle ? `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}` : "–";
  document.querySelectorAll(".agent").forEach((el) => {
    $(".updated", el).textContent = `Senaste bedömning: ${ago(+el.dataset.updated)}`;
  });
}, 1000);

// filters
document.querySelectorAll(".chip").forEach((b) => b.addEventListener("click", () => {
  document.querySelectorAll(".chip").forEach((c) => c.classList.toggle("on", c === b));
  filter = b.dataset.f;
  document.querySelectorAll("#feed li[data-agent]").forEach((li) => { li.hidden = filter !== "all" && filter !== li.dataset.agent; });
}));

$("#runNow").addEventListener("click", async (ev) => {
  ev.target.disabled = true;
  const r = await fetch("/api/run-now", { method: "POST" });
  if (!r.ok) alert((await r.json()).msg);
  setTimeout(() => (ev.target.disabled = false), 5000);
});

// live updates
function connect() {
  const es = new EventSource("/api/stream");
  es.onmessage = (m) => {
    const msg = JSON.parse(m.data);
    if (!S) return;
    if (msg.type === "event") {
      S.events.push(msg.event);
      const ol = $("#feed");
      if (ol.querySelector(".empty")) ol.innerHTML = "";
      ol.prepend(feedItem(msg.event, true));
      while (ol.children.length > 200) ol.lastChild.remove();
    } else if (msg.type === "status") {
      const a = S.agents.find((x) => x.key === msg.agent);
      if (a) { a.status = msg.status; renderAgent(a); }
    } else if (msg.type === "opinion") {
      const a = S.agents.find((x) => x.key === msg.agent);
      if (a) { a.opinion = msg.opinion; a.updated = msg.ts; renderAgent(a); renderVerdicts(); }
    } else if (msg.type === "decisions") {
      S.decisions = msg.decisions; renderVerdicts();
    } else if (msg.type === "prices") {
      S.prices = msg.prices; renderVerdicts();
    } else if (msg.type === "tick") {
      S.next_cycle = msg.next_cycle; S.market_open = msg.market_open; renderTop();
    } else if (msg.type === "trades") {
      load();
    }
  };
  es.onerror = () => { es.close(); setTimeout(() => { load(); connect(); }, 4000); };
}

load().then(connect);
window.addEventListener("resize", () => S && loadEquity());
