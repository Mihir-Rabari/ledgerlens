// The authenticated investigator console. Logic is ported 1:1 from the proven
// single-file console; the differences are auth-aware: analysts are pinned to
// their bank, the stress bench is admin-only, and every request rides api().

import { api } from "../api.js";
import { logout, myLogins } from "../auth.js";

const IC = {
  note: '<svg width="12" height="12" viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="M3 2h7l3 3v9H3V2Z" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/><path d="M6 7h4M6 10h4" stroke="currentColor" stroke-width="1.2"/></svg>',
  msg: '<svg width="12" height="12" viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="M14 8a6 6 0 0 1-6 6H3l1.8-1.8A6 6 0 1 1 14 8Z" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/></svg>',
  brain: '<svg width="12" height="12" viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="M6 3.5c-2 0-3.5 1.2-3.5 3 0 1.2.6 2 1.5 2.5V11c0 1 .8 1.8 1.8 1.8H7.5V3.5H6ZM10 3.5c2 0 3.5 1.2 3.5 3 0 1.2-.6 2-1.5 2.5V11c0 1-.8 1.8-1.8 1.8H8.5V3.5H10Z" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/></svg>',
  arrow: '<svg width="12" height="12" viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="M3 4h7M10 4v7" stroke="currentColor" stroke-width="1.5"/><path d="M7 8l3 3 3-3" stroke="currentColor" stroke-width="1.5" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  chev: '<svg width="12" height="12" viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="M6 3l5 5-5 5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  doc: '<svg width="11" height="11" viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="M3 2h7l3 3v9H3V2Z" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/><path d="M6 7h4M6 10h4" stroke="currentColor" stroke-width="1.2"/></svg>',
  q: '<svg width="12" height="12" viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="M13 3v10M6.5 3v6.5a2.5 2.5 0 0 0 5 0" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>',
  spin: '<svg class="spin" width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true"><circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="2.2" opacity=".22"/><path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/></svg>',
  bolt: '<svg width="13" height="13" viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="M9 1 3 9h4l-1 6 7-8H8l1-6Z" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/></svg>',
  lens: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5" stroke="currentColor" stroke-width="1.8"/><path d="M15.5 15.5 21 21" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/></svg>',
};

export function renderConsole(root, user) {
  const ADMIN = user.role === "admin";
  let TENANT = user.tenant;
  let CHAT_SESSION = null;

  const initials = (user.name || user.username || "?")
    .split(/\s+/).map((w) => w[0]).join("").slice(0, 2).toUpperCase();

  root.innerHTML = `
  <header>
    <div class="brand">
      <svg width="26" height="26" viewBox="0 0 28 28" fill="none" aria-hidden="true">
        <circle cx="12" cy="12" r="7.2" stroke="#e3b34c" stroke-width="1.7"/>
        <path d="M17.2 17.2 L23.4 23.4" stroke="#e3b34c" stroke-width="2.4" stroke-linecap="round"/>
        <circle cx="9.5" cy="10" r="1.5" fill="#e3b34c"/><circle cx="14.6" cy="11.4" r="1.5" fill="#e3b34c"/>
        <circle cx="11" cy="14.6" r="1.5" fill="#e3b34c"/>
        <path d="M9.5 10 L14.6 11.4 L11 14.6 Z" stroke="#e3b34c" stroke-width="1" opacity=".55"/>
      </svg>
      <span class="word">Ledger<i>Lens</i></span>
    </div>
    <div class="tagline">fraud-ring investigator · FalkorDB context layer · every answer shows its path</div>
    <div class="spacer"></div>
    <div class="hpill" id="health"><span class="dot" id="hdot"></span><span id="htxt">connecting…</span></div>
    ${ADMIN ? `<select id="tenant" aria-label="Tenant"></select>` : ""}
    <div class="userwrap">
      <button class="uchip" id="uchip" type="button" aria-haspopup="true" aria-expanded="false">
        <span class="uavatar">${initials}</span>
        <span class="uname">${esc(user.name || user.username)}</span>
        <span class="urole ${user.role}">${user.role}</span>
      </button>
      <div class="umenu" id="umenu" hidden>
        <div class="who"><span class="n">${esc(user.name || user.username)}</span>
          <span class="u">${esc(user.username)} · tenant ${esc(user.tenant)}</span></div>
        <div class="mut">recent logins (graph audit)</div>
        <div id="ulogins"><div class="lg"><span>loading…</span></div></div>
        <hr>
        <button class="btn-ghost" id="signout" type="button" style="padding:7px 10px">Sign out</button>
      </div>
    </div>
  </header>

  <main>
    <div class="col col-l">
      <section class="panel">
        <h2>Alert queue <span class="chip" id="alert-count"></span></h2>
        <div id="alerts"><div class="skel w85"></div><div class="skel w70"></div><div class="skel w50"></div></div>
        ${ADMIN ? `
        <button class="btn-ghost" style="width:100%;margin-top:6px" onclick="window.__bench(this)" id="bench-btn">
          ${IC.bolt} Stress: 4 parallel investigations across tenants
        </button>` : ""}
      </section>
      <section class="panel">
        <h2>Tenant graph <span class="h2-sub">node census</span></h2>
        <div class="stats" id="stats"><div class="skel w70"></div><div class="skel w85"></div><div class="skel w50"></div></div>
      </section>
    </div>

    <div class="col col-c">
      <section class="panel">
        <h2>Investigation <span class="h2-sub" id="inv-status"></span></h2>
        <div id="investigation">
          <div class="empty">
            ${IC.lens.replace('width="13" height="13"', 'width="22" height="22"')}
            <div>Pick an alert from the queue</div>
            <div class="hint">The analyst triages it, hands off to the investigator if evidence warrants — and every step shows the tool path it walked.</div>
          </div>
        </div>
      </section>
      <section class="panel">
        <h2>Ring view <span class="h2-sub">association graph of involved accounts</span></h2>
        <div id="ringview">
          <div class="empty">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true"><circle cx="6" cy="6" r="2.4" stroke="currentColor" stroke-width="1.6"/><circle cx="18" cy="8" r="2.4" stroke="currentColor" stroke-width="1.6"/><circle cx="10" cy="18" r="2.4" stroke="currentColor" stroke-width="1.6"/><path d="M8.3 6.8 15.6 7.7M7 8.3l2.2 7.3M16.3 10 11.9 16" stroke="currentColor" stroke-width="1.3"/></svg>
            <div>Appears after an investigation</div>
            <div class="hint">Accounts involved in the case, laid out as a ring: shared devices, addresses and owners as edges, money flow highlighted.</div>
          </div>
        </div>
        <div class="legend" id="ringlegend" style="display:none">
          <span><b class="lc-good"></b>active</span>
          <span><b class="lc-bad"></b>frozen</span>
          <span><b class="lc-assoc"></b>association</span>
          <span><b class="lc-money"></b>money flow</span>
        </div>
      </section>
    </div>

    <div class="col col-r">
      <section class="panel">
        <h2>Ask the graph <span class="h2-sub">read-only Q&amp;A · answers carry their shape</span></h2>
        <div id="chatlog">
          <div class="empty">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M21 12a8 8 0 0 1-8 8H4l2.5-2.5A8 8 0 1 1 21 12Z" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/></svg>
            <div>Answers carry their shape and tool path</div>
            <div class="hint">Try an example below — accounts, links, rings, recalled memory.</div>
          </div>
          <div class="ex-row">
            <button class="ex" type="button">Which accounts received transfers just under the 10,000 threshold?</button>
            <button class="ex" type="button">What do we already know about the ghost device ring?</button>
          </div>
        </div>
        <div class="chatbox">
          <input id="chat-input" placeholder="Ask about accounts, links, past cases…" autocomplete="off">
          <button class="btn" id="chat-send">${IC.lens} Ask</button>
        </div>
      </section>
      <section class="panel">
        <h2>Cases</h2>
        <div id="cases"><div class="skel w85"></div><div class="skel w70"></div><div class="skel w60"></div></div>
      </section>
      <section class="panel">
        <h2>Sessions <span class="h2-sub">episodic timeline · handoffs</span></h2>
        <div id="sessions"><div class="skel w70"></div><div class="skel w85"></div></div>
      </section>
    </div>
  </main>
  <footer>LedgerLens · Graph Hacks 2026 · WeMakeDevs × FalkorDB · Tracks 1 + 2 · synthetic data only</footer>
  <div class="toast" id="toast"></div>`;

  const $ = (id) => document.getElementById(id);

  function esc(s) {
    return String(s ?? "").replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }
  function el(html) { const t = document.createElement("template"); t.innerHTML = html.trim(); return t.content.firstChild; }
  function shapeBadge(shape) { return `<span class="shape ${esc(shape)}">${esc(shape)}</span>`; }
  function sevClass(s) { return "s" + Math.max(1, Math.min(5, s)); }
  function emptyBox(title, hint, icon) {
    return `<div class="empty">${icon || ""}<div>${esc(title)}</div>${hint ? `<div class="hint">${esc(hint)}</div>` : ""}</div>`;
  }
  function toast(text, kind = "") {
    const t = el(`<div class="t-msg ${kind}">${esc(text)}</div>`);
    $("toast").appendChild(t);
    setTimeout(() => t.remove(), 3800);
  }
  const guard = (p) => p.catch((e) => { if (e.status !== 401) toast(e.message, "err"); });

  // ── user menu ────────────────────────────────────────
  const chip = $("uchip"), menu = $("umenu");
  chip.onclick = async () => {
    const open = menu.hidden;
    menu.hidden = !open;
    chip.setAttribute("aria-expanded", String(!menu.hidden));
    if (!menu.hidden) {
      try {
        const rows = await myLogins();
        $("ulogins").innerHTML = rows.length
          ? rows.slice(0, 5).map((r) =>
              `<div class="lg"><span>${esc((r.at || "").replace("T", " ").split("+")[0])}</span>` +
              `<span class="${r.ok ? "ok-ic" : "no-ic"}">${r.ok ? "✓ ok" : "✗ failed"}</span></div>`).join("")
          : `<div class="lg"><span>no logins recorded yet</span></div>`;
      } catch { $("ulogins").innerHTML = `<div class="lg"><span>unavailable</span></div>`; }
    }
  };
  document.addEventListener("click", (e) => {
    if (!menu.hidden && !e.target.closest(".userwrap")) { menu.hidden = true; }
  });
  $("signout").onclick = async () => { await logout(); location.hash = "#/login"; };

  // ── example chips ────────────────────────────────────
  root.querySelectorAll(".ex").forEach((b) =>
    (b.onclick = () => { const i = $("chat-input"); i.value = b.textContent.trim(); i.focus(); }));

  // ── bench button ────────────────────────────────────
  if (ADMIN) { window.__bench = (btn) => runBench(btn); }

  async function loadHealth() {
    try {
      const h = await api("/healthz");
      $("hdot").className = "dot" + (h.ok ? " ok" : "");
      $("htxt").textContent = h.ok
        ? `FalkorDB · ${h.tenants.length} tenants · LLM ${h.llm_configured ? "live" : "off"}${h.live_feed ? " · live feed" : ""}`
        : "FalkorDB down";
      if (ADMIN) {
        const sel = $("tenant");
        sel.innerHTML = (h.tenants || []).map((t) => `<option ${t === TENANT ? "selected" : ""}>${esc(t)}</option>`).join("");
      }
      if (!TENANT && h.tenants.length) { TENANT = h.tenants[0]; }
      if (h.tenants.length) refreshTenant();
    } catch { $("htxt").textContent = "offline"; }
  }

  function refreshTenant() {
    guard(loadAlerts()); guard(loadStats()); guard(loadCases()); guard(loadSessions());
  }

  async function loadSessions() {
    const r = await api(`/api/tenants/${TENANT}/sessions`);
    const wrap = $("sessions");
    wrap.innerHTML = "";
    if (!r.data.sessions.length) { wrap.innerHTML = emptyBox("no sessions yet"); return; }
    r.data.sessions.slice(0, 10).forEach((s) => {
      const handoff = (s.handed_from && s.handed_from.length)
        ? `<div class="hoffs">${IC.arrow} hands_off from ${esc(s.handed_from[0])}</div>` : "";
      wrap.appendChild(el(`<div class="row">
        <div class="t">${esc(s.agent)} <span class="sid">${esc(s.id)}</span></div>
        ${handoff}
        <div class="m"><span>${esc((s.started_at || "").replace("T", " ").split("+")[0])}</span>
        <span>${IC.note} ${s.findings} finding(s)</span><span>${IC.msg} ${s.messages} msg(s)</span></div>
      </div>`));
    });
  }

  async function loadStats() {
    const s = await api(`/api/tenants/${TENANT}/stats`);
    const nodes = s.data?.nodes || [];
    const max = Math.max(...nodes.map((n) => n.count), 1);
    const rows = nodes.map((n) => `
      <div class="stat-row"><span class="l">${esc(n.label)}</span>
        <span class="bar"><i style="width:${Math.max(4, Math.round(n.count / max * 100))}%"></i></span>
        <span class="v">${esc(n.count)}</span></div>`).join("");
    $("stats").innerHTML = `<div class="stats-lead">${esc(s.summary || "")}</div>${rows}`;
  }

  async function loadAlerts() {
    const r = await api(`/api/tenants/${TENANT}/alerts?status=open`);
    const wrap = $("alerts");
    $("alert-count").textContent = r.data.alerts.length + " open";
    wrap.innerHTML = "";
    if (!r.data.alerts.length) { wrap.innerHTML = emptyBox("no open alerts"); return; }
    r.data.alerts.forEach((a) => {
      wrap.appendChild(el(`<div class="alert ${sevClass(a.severity)}">
        <div class="row1"><span class="aid">${esc(a.id)}</span><span class="pill ${sevClass(a.severity)}">sev ${a.severity}</span></div>
        <div class="kind">${esc(a.kind)} · ${esc(a.account)} (${esc(a.account_name)}) · ${esc((a.amount || 0).toLocaleString())}</div>
        <div class="summary">${esc(a.summary)}</div>
        <button class="btn-quiet" type="button" data-alert="${esc(a.id)}">Investigate</button>
      </div>`));
    });
    wrap.querySelectorAll("button[data-alert]").forEach((b) =>
      (b.onclick = () => investigate(b.dataset.alert, b)));
  }

  async function loadCases() {
    const r = await api(`/api/tenants/${TENANT}/cases`);
    const wrap = $("cases");
    wrap.innerHTML = "";
    if (!r.data.cases.length) { wrap.innerHTML = emptyBox("no cases yet"); return; }
    r.data.cases.slice(0, 12).forEach((c) => {
      const row = el(`<div class="row" role="button" tabindex="0" data-case="${esc(c.id)}">
        <div class="t">${esc(c.title)}</div>
        <div class="m"><span>${esc(c.id)}</span><span class="pill st-${esc(c.status)}">${esc(c.status)}</span><span>sev ${c.severity}</span></div>
        <span class="chev">${IC.chev}</span>
      </div>`);
      wrap.appendChild(row);
    });
    wrap.querySelectorAll("[data-case]").forEach((r2) => {
      const open = () => openCase(r2.dataset.case);
      r2.onclick = open;
      r2.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); } };
    });
  }

  async function openCase(id) {
    try {
      const r = await api(`/api/tenants/${TENANT}/case/${id}`);
      const d = r.data;
      $("chatlog").prepend(el(`<div class="msg case-doc">
        <div class="doc-head"><span class="id">${esc(d.id)} · ${esc(d.title)} <span class="pill st-${esc(d.status)}">${esc(d.status)}</span></span>
          <a href="/api/tenants/${TENANT}/case/${esc(id)}/report" target="_blank">${IC.doc} report.md</a></div>
        <div class="out"><b>Outcome:</b> ${esc(d.outcome || "—")}</div>
        <div class="list"><b>Findings:</b><br>${(d.findings || []).map((f) => "· " + esc(f.text)).join("<br>") || "—"}</div>
        <div class="list"><b>Actions:</b><br>${(d.actions || []).map((a) => `· ${esc(a.kind)} @ ${esc(a.at)} — ${esc(a.reason || "")}`).join("<br>") || "—"}</div>
      </div>`));
    } catch (e) { toast(e.message, "err"); }
  }

  async function investigate(alertId, btn) {
    if (btn) { btn.disabled = true; btn.textContent = "Investigating…"; }
    $("inv-status").textContent = "running…";
    $("investigation").innerHTML = `<div class="empty">${IC.spin}<div>Analyst walking the graph…</div>
      <div class="hint">intake-analyst → case-investigator · every step shows its tool path</div></div>`;
    try {
      const r = await api(`/api/tenants/${TENANT}/investigate`, {
        method: "POST", body: JSON.stringify({ alert_id: alertId }),
      });
      renderInvestigation(r);
    } catch (e) {
      $("investigation").innerHTML = emptyBox(`investigation failed: ${e.message}`);
    }
    if (btn) { btn.disabled = false; btn.textContent = "Investigate"; }
    $("inv-status").textContent = "";
    guard(loadAlerts()); guard(loadCases());
  }

  function renderInvestigation(r) {
    const box = $("investigation");
    box.innerHTML = "";
    if (r.analyst_final) {
      box.appendChild(el(`<div class="verdict">
        <div class="head"><span class="agent-name">intake-analyst</span>${shapeBadge(r.analyst_final.shape)}
          <span class="conf">confidence ${esc(r.analyst_final.confidence)} · verdict ${esc(r.analyst_final.verdict || "—")}</span></div>
        <div class="body">${esc(r.analyst_final.summary || "")}</div></div>`));
    }
    if (r.handoff) {
      box.appendChild(el(`<div class="handoff">${IC.arrow} HANDS_OFF ${esc(r.analyst_session_id)} → ${esc(r.investigator_session_id)} · case ${esc(r.case_id)}</div>`));
    }
    if (r.investigator_final) {
      box.appendChild(el(`<div class="verdict investigator">
        <div class="head"><span class="agent-name">case-investigator</span>${shapeBadge(r.investigator_final.shape)}
          <span class="conf">confidence ${esc(r.investigator_final.confidence)} · verdict ${esc(r.investigator_final.verdict || "—")}</span></div>
        <div class="body">${esc(r.investigator_final.summary || "")}</div></div>`));
    }
    if (r.turns && r.turns.length) {
      const trail = el('<div class="trail"></div>');
      trail.appendChild(el(`<div class="trail-head"><span>agent</span><span>tool</span><span>result</span></div>`));
      r.turns.forEach((t) => {
        trail.appendChild(el(`<div class="turn ${t.ok ? "" : "err"}">
          <span class="agent">${esc(t.agent)}</span><span class="tool"><span class="${t.ok ? "ok" : "no"}">${t.ok ? "✓" : "✗"}</span> ${esc(t.tool)}</span>
          <span class="summ" title="${esc(t.summary || "")}">${esc(t.summary || "")}</span></div>`));
      });
      box.appendChild(trail);
    }
    loadRing(r);
  }

  async function loadRing(r) {
    const ids = new Set();
    (r.turns || []).forEach((t) => {
      if (t.tool === "find_rings") return;
      if (t.tool === "freeze_account") ids.add(t.arguments.account_id);
      if (t.tool === "open_case") (t.arguments.account_ids || []).forEach((i) => ids.add(i));
      if (t.tool === "get_account_profile") ids.add(t.arguments.account_id);
    });
    (r.turns || []).forEach((t) => {
      if (t.tool === "find_rings" && t.data && t.data.components) {
        const best = t.data.components.slice().sort((a, b) => b.internal_transfer_edges - a.internal_transfer_edges)[0];
        if (best) best.member_ids.forEach((i) => ids.add(i));
      }
    });
    if (!ids.size) return;
    const g = await api(`/api/tenants/${TENANT}/graph?ids=${encodeURIComponent([...ids].join(","))}`);
    drawRing(g.data);
  }

  function drawRing(data) {
    const nodes = data.nodes, edges = data.edges, transfers = data.transfers || [];
    if (!nodes.length) return;
    const W = 760, H = 440, cx = W / 2, cy = H / 2, R = Math.min(W, H) / 2 - 46;
    nodes.forEach((n, i) => {
      const a = (2 * Math.PI * i) / nodes.length - Math.PI / 2;
      n.x = cx + R * Math.cos(a); n.y = cy + R * Math.sin(a);
    });
    const byId = Object.fromEntries(nodes.map((n) => [n.id, n]));
    const lines = edges.filter((e) => byId[e.source] && byId[e.target])
      .map((e) => `<line x1="${byId[e.source].x}" y1="${byId[e.source].y}" x2="${byId[e.target].x}" y2="${byId[e.target].y}" stroke="#3a4150" stroke-width="1" opacity=".55"/>`).join("");
    const money = transfers.filter((e) => byId[e.source] && byId[e.target])
      .map((e) => `<line x1="${byId[e.source].x}" y1="${byId[e.source].y}" x2="${byId[e.target].x}" y2="${byId[e.target].y}" stroke="#e3b34c" stroke-width="1.8" stroke-dasharray="4 3" opacity=".85"/>`).join("");
    const circles = nodes.map((n) => `
      <circle cx="${n.x}" cy="${n.y}" r="14" fill="${n.status === "frozen" ? "#e5534b" : "#3ecf8e"}" stroke="#0b0d11" stroke-width="2.5"><title>${esc(n.id)} · ${esc(n.status)}</title></circle>
      <text x="${n.x}" y="${n.y + 30}" text-anchor="middle" fill="#8b93a3" font-size="10" font-family="ui-monospace,Menlo,monospace">${n.id.slice(-4)}</text>`).join("");
    $("ringview").innerHTML = `<svg class="graphviz" viewBox="0 0 ${W} ${H}">${lines}${money}${circles}</svg>`;
    $("ringlegend").style.display = "flex";
  }

  async function runBench(btn) {
    if (btn) { btn.dataset.orig = btn.innerHTML; btn.disabled = true; btn.textContent = "⚡ running parallel investigations…"; }
    const box = $("investigation");
    $("inv-status").textContent = "stress bench";
    box.innerHTML = `<div class="empty">${IC.spin}<div>Running 4 parallel investigations across tenants</div>
      <div class="hint">watch the case list grow…</div></div>`;
    try {
      const r = await api("/api/bench", { method: "POST" });
      box.innerHTML = "";
      const rows = (r.results || []).map((x) => `<div class="turn"><span class="agent">${esc(x.tenant)}</span><span class="tool"><span class="${x.error ? "no" : "ok"}">${x.error ? "✗" : "✓"}</span> ${esc(x.alert_id)}</span><span class="summ">${x.error ? esc(x.error) : esc(x.verdict || "no_case") + " · " + esc(x.seconds) + "s · " + esc(x.tool_calls) + " tool calls · case " + esc(x.case_id || "—")}</span></div>`).join("");
      box.appendChild(el(`<div class="verdict"><div class="head"><span class="agent-name">stress bench</span><span class="shape action">high-concurrency</span><span class="conf">${esc(r.parallelism)} parallel investigations · ${esc(r.wall_seconds)}s wall time</span></div>
        <div class="trail" style="margin-top:4px">${rows}</div></div>`));
    } catch (e) {
      box.innerHTML = emptyBox(`bench failed: ${e.message}`);
    }
    if (btn) { btn.disabled = false; btn.innerHTML = btn.dataset.orig; }
    $("inv-status").textContent = "";
    guard(loadAlerts()); guard(loadCases()); guard(loadSessions());
  }

  async function ask() {
    const input = $("chat-input");
    const q = input.value.trim();
    if (!q) return;
    input.value = "";
    const holder = el(`<div class="msg"><div class="q">${IC.q} you asked: ${esc(q)}</div>
      <div class="empty" style="padding:8px 0">${IC.spin}<div>walking the graph…</div></div></div>`);
    $("chatlog").prepend(holder);
    try {
      const r = await api(`/api/tenants/${TENANT}/ask`, {
        method: "POST", body: JSON.stringify({ message: q, session_id: CHAT_SESSION }),
      });
      CHAT_SESSION = r.session_id;
      const a = r.answer || {};
      const turns = (r.turns || []).map((t) => `<div class="turn ${t.ok ? "" : "err"}"><span class="tool"><span class="${t.ok ? "ok" : "no"}">${t.ok ? "✓" : "✗"}</span> ${esc(t.tool)}</span><span class="summ">${esc(t.summary || "")}</span></div>`).join("");
      holder.innerHTML = `<div class="q">${IC.q} you asked: ${esc(q)}</div>
        ${r.recalled && (r.recalled.findings || r.recalled.prior_session)
          ? `<div class="recall">${IC.brain} new session — recalled ${esc(r.recalled.findings)} finding(s) from prior sessions${r.recalled.prior_session ? " · prior chat: " + esc(r.recalled.prior_session) : ""}</div>` : ""}
        <div class="shaperow">${shapeBadge(a.shape || "not_in_graph")} <span class="conf">confidence ${esc(a.confidence ?? "—")}</span></div>
        <div class="answer">${esc(a.summary || r.answer_text || "")}</div>
        ${turns ? `<div class="mini-trail">${turns}</div>` : ""}`;
    } catch (e) {
      holder.innerHTML = `<div class="q">${IC.q} you asked: ${esc(q)}</div><div style="color:var(--bad)">failed: ${esc(e.message)}</div>`;
    }
  }

  $("chat-send").onclick = ask;
  $("chat-input").addEventListener("keydown", (e) => { if (e.key === "Enter") ask(); });
  if (ADMIN) {
    $("tenant").addEventListener("change", (e) => {
      TENANT = e.target.value; CHAT_SESSION = null;
      refreshTenant();
    });
  }

  loadHealth();
  const healthTimer = setInterval(loadHealth, 30000);

  return () => { clearInterval(healthTimer); window.__bench = undefined; };
}
