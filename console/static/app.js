/* Human Console client.
 *
 * Rules (docs/console/design-principles.md): reads from /api/snapshot and
 * /api/task (the engine's snapshot + show/budget, verbatim); every button is
 * an existing engine command via /api/command; readiness is data, never
 * re-derived; the client interprets (sections, grouping, emphasis) but never
 * decides. All engine text is rendered escaped, verbatim.
 */
"use strict";

const $app = document.getElementById("app");
const state = { snap: null, view: null };

/* ---------- utilities ---------- */

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g,
    c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function uuid() {
  return (crypto.randomUUID && crypto.randomUUID()) ||
    "r-" + Date.now() + "-" + Math.random().toString(16).slice(2);
}
function ago(iso) {
  if (!iso) return "";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 90) return "just now";
  if (s < 5400) return Math.round(s / 60) + "m ago";
  if (s < 129600) return Math.round(s / 3600) + "h ago";
  return Math.round(s / 86400) + "d ago";
}
function shortId(id) { return id ? id.slice(0, 13) : ""; }

async function api(path) {
  const r = await fetch(path);
  const body = await r.json();
  if (!r.ok) throw new Error(body.error || r.statusText);
  return body;
}
async function command(body, box) {
  /* POST an engine command; surface the engine's refusal verbatim. */
  try {
    const r = await fetch("/api/command", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const payload = await r.json();
    if (!r.ok) throw new Error(payload.error || "command failed");
    await refresh();
    return payload;
  } catch (e) {
    if (box) box.innerHTML = `<div class="error-box">engine refused: ${esc(e.message)}</div>`;
    else alert("engine refused: " + e.message);
    return null;
  }
}

/* ---------- snapshot + routing ---------- */

let lastSnapJson = null;

async function loadSnap() {
  const snap = await api("/api/snapshot");
  const j = JSON.stringify({ ...snap, generated_at: null });
  const changed = j !== lastSnapJson;
  lastSnapJson = j;
  state.snap = snap;
  document.getElementById("store-info").textContent =
    `${snap.store.tasks} task(s) · ${snap.store.dir}`;
  return changed;
}

async function refresh() {
  await loadSnap();
  route();
}

function route() {
  const h = location.hash || "#/";
  document.querySelectorAll("[data-nav]").forEach(a => {
    a.classList.toggle("active",
      (h === "#/" && a.dataset.nav === "home") || h.startsWith("#/" + a.dataset.nav));
  });
  if (h.startsWith("#/task/")) return renderTask(h.slice(7));
  if (h === "#/board") return renderBoard();
  if (h === "#/graph") return renderGraph();
  return renderHome();
}
window.addEventListener("hashchange", route);

/* ---------- classification (docs/console/home-screen.md) ----------
 * Every discriminator is an engine fact from the human_blocked event or
 * readiness_detail; the client sections, the engine never classifies. */

function parkInfo(t) {
  const hb = t.human_blocked;
  if (hb) {
    const d = hb.detail || {};
    if (d.cycle) return { section: "redirect", cause: "cycle", hb, cycle: d.cycle };
    if (d.enforced_by === "engine")
      return d.kind ? { section: "redirect", cause: "breaker", hb }
                    : { section: "redirect", cause: "budget", hb };
    if (hb.actor === "explore") {
      const r = hb.reason || "";
      return { section: "approve",
               cause: r.startsWith("DECISION IS THE DELIVERABLE") ? "disposition" : "topology",
               hb };
    }
    return { section: "answer", cause: "question", hb };
  }
  if (t.readiness === "human" && t.readiness_detail && t.readiness_detail.cycle)
    return { section: "redirect", cause: "cycle", cycle: t.readiness_detail.cycle };
  return null;
}

function cycleKey(cycle) { return [...new Set(cycle)].sort().join("+"); }

/* Queue membership is the two-clause rule: parked OR readiness "human". */
function queue() {
  const items = [], cycles = new Map();
  for (const t of state.snap.tasks) {
    const p = parkInfo(t);
    if (!p) continue;
    if (p.cause === "cycle") {
      const key = cycleKey(p.cycle);
      if (!cycles.has(key)) {
        cycles.set(key, { section: "redirect", cause: "cycle",
                          members: [], at: p.hb ? p.hb.at : null });
        items.push(cycles.get(key));
      }
      const c = cycles.get(key);
      c.members.push(t);
      if (p.hb) { c.hb = p.hb; c.at = c.at || p.hb.at; }
    } else {
      items.push({ ...p, task: t, at: p.hb.at });
    }
  }
  items.sort((a, b) => (a.at || "").localeCompare(b.at || "")); // oldest ask first
  return items;
}

/* ---------- shared renderers ---------- */

function chips(t) {
  /* A parked task's derived readiness is "terminal" — true but misleading
   * next to the parked badge, so the badge replaces the readiness chip. */
  let h = t.status === "blocked_on_human"
    ? `<span class="chip parked">parked</span>`
    : `<span class="chip readiness-${esc(t.readiness)}">${esc(t.readiness)}</span>`;
  for (const [k, v] of Object.entries(t.active_artifacts || {}))
    if (v) h += ` <span class="chip artifact">${esc(k.slice(0, 4))} v${v}</span>`;
  return h;
}

function cardHead(t, info) {
  const actorChip = info && info.hb && !["tasks.py"].includes(info.hb.actor)
    ? ` <span class="chip actor">${esc(info.hb.actor)}</span>` : "";
  return `<div class="card-head">
    <a class="title" href="#/task/${esc(t.id)}">${esc(t.title)}</a>
    <span class="mono muted">${esc(shortId(t.id))}</span>${chips(t)}${actorChip}
    <span class="when">${info && info.at ? "parked " + esc(ago(info.at)) : ""}</span>
  </div>`;
}

/* ---------- composers: every submit is one engine command ---------- */

function composerHTML(item) {
  const t = item.task;
  const noteBox = (ph) =>
    `<label>Your note (recorded in history — required)</label>
     <textarea class="note" data-role="note" placeholder="${esc(ph)}"></textarea>`;
  const resultBox = (json, label) =>
    `<label>${esc(label)} (result.json applied as the human — edit before submitting)</label>
     <textarea data-role="result">${esc(JSON.stringify(json, null, 2))}</textarea>`;

  if (item.cause === "topology") {
    const prefill = parseProposal(item.hb.reason);
    return `<div class="composer">
      ${noteBox("approved as proposed / adjustments…")}
      ${resultBox(prefill, "Approved topology")}
      <div class="actions">
        <button class="primary" data-act="human-update-result">Commit as human</button>
        <button data-act="human-update-note">Reject decision (note only → re-explore)</button>
      </div><div data-role="msg"></div></div>`;
  }
  if (item.cause === "disposition") {
    return `<div class="composer">
      ${noteBox("your call on the disposition…")}
      <div class="actions">
        <button class="primary" data-act="dispose-close">Close — decision is the deliverable</button>
        <button data-act="dispose-spawn">Spawn work + close</button>
        <button data-act="human-update-note">Continue → refine</button>
      </div><div data-role="spawn"></div><div data-role="msg"></div></div>`;
  }
  if (item.cause === "question") {
    return `<div class="composer">
      ${noteBox("your answer…")}
      <div class="actions"><button class="primary" data-act="human-update-note">Answer</button></div>
      <div data-role="msg"></div></div>`;
  }
  if (item.cause === "budget" || item.cause === "breaker") {
    return `<div class="composer">
      ${noteBox("how to proceed: respec, new approach, take over…")}
      <details><summary>attach a result.json (e.g. a superseding spec)</summary>
        ${resultBox({ result_id: uuid(), artifacts: [] }, "Optional result")}</details>
      <div class="actions">
        <button class="primary" data-act="human-update-auto">Redirect</button>
        <button class="danger" data-act="cancel">Cancel task…</button>
      </div><div data-role="msg"></div></div>`;
  }
  return "";
}

/* Parse explore's numbered decomposition + findings into an editable result.
 * A prompt-template convention, not a contract (home-screen.md finding 4):
 * on no match the human simply gets an empty scaffold to fill. */
function parseProposal(reason) {
  const children = [], followUps = [];
  for (const line of (reason || "").split("\n")) {
    const m = line.match(/^\s*\d+\.\s*(.+?)\s+—\s+(.+)$/);
    if (m) children.push({ title: m[1], description: m[2],
                           relation: "child", reason: "approved decomposition" });
    const f = line.match(/^\s*-\s*(.+?)\s*→.*promote/i);
    if (f) followUps.push({ title: f[1], description: f[1],
                            relation: "follow_up", reason: "promoted finding" });
  }
  return { result_id: uuid(), generated_tasks: [...children, ...followUps] };
}

function wireComposer(card, item) {
  const t = item.task;
  const q = (sel) => card.querySelector(sel);
  const note = () => {
    const v = q('[data-role="note"]').value.trim();
    if (!v) { q('[data-role="msg"]').innerHTML =
      '<div class="error-box">a note is required — it becomes the human_updated event</div>'; }
    return v;
  };
  const send = (body) => command(body, q('[data-role="msg"]'));

  card.addEventListener("click", async (ev) => {
    const act = ev.target.dataset && ev.target.dataset.act;
    if (!act) return;
    const n = note(); if (!n) return;
    if (act === "human-update-note")
      return send({ command: "human-update", id: t.id, text: { note: n } });
    if (act === "human-update-result" || act === "human-update-auto") {
      let result = null;
      const rb = q('[data-role="result"]');
      if (rb && rb.value.trim()) {
        try { result = JSON.parse(rb.value); }
        catch (e) { return q('[data-role="msg"]').innerHTML =
          `<div class="error-box">result is not valid JSON: ${esc(e.message)}</div>`; }
      }
      if (act === "human-update-result" && !result) return;
      return send({ command: "human-update", id: t.id, text: { note: n },
                    ...(result ? { result } : {}) });
    }
    if (act === "dispose-close")
      return send({ command: "human-update", id: t.id, text: { note: n },
                    result: { result_id: uuid(), signal: "done" } });
    if (act === "dispose-spawn") {
      const slot = q('[data-role="spawn"]');
      if (!slot.querySelector("textarea")) {
        slot.innerHTML = `<label>Work to file, then close (edit)</label>
          <textarea data-role="result">${esc(JSON.stringify({
            result_id: uuid(),
            generated_tasks: [{ title: "", description: "",
                                relation: "follow_up", reason: "from the research decision" }],
            signal: "done" }, null, 2))}</textarea>
          <div class="actions"><button class="primary" data-act="human-update-result">Spawn + close as human</button></div>`;
        return;
      }
      return; // second click falls through to human-update-result button
    }
    if (act === "cancel") {
      const reason = prompt("Cancellation reason (recorded forever):");
      if (reason) return send({ command: "cancel", id: t.id, text: { reason } });
    }
    if (act === "reopen") {
      const reason = prompt("Why is this task back?");
      if (reason) return send({ command: "reopen", id: t.id, text: { reason } });
    }
  });
}

/* ---------- Home ---------- */

const SECTIONS = [
  ["approve", "Approve", "decision proposals from explore — topology and research dispositions"],
  ["answer", "Answer", "questions a skill parked on"],
  ["redirect", "Redirect", "work the engine stopped: budget, non-convergence, cycles"],
];

function renderHome() {
  const items = queue();
  if (!items.length) {
    const counts = {};
    for (const t of state.snap.tasks) counts[t.readiness] = (counts[t.readiness] || 0) + 1;
    $app.innerHTML = `<div class="empty-state">
      <div class="big">Nothing needs you.</div>
      <div class="muted">${counts.run || 0} task(s) ready to run · ${counts.refine || 0} in refinement
      · ${counts.waiting || 0} waiting</div>
      <p class="small muted">The empty queue is the success state.</p></div>`;
    return;
  }
  let html = `<h1>Needs a human <span class="muted">(${items.length})</span></h1>`;
  for (const [key, label, hint] of SECTIONS) {
    const rows = items.filter(i => i.section === key);
    if (!rows.length) continue;
    html += `<h2>${label} <span class="muted">(${rows.length})</span></h2>
             <p class="section-hint">${esc(hint)}</p>`;
    for (const item of rows) html += homeCard(item);
  }
  $app.innerHTML = html;
  wireHome(items);
}

function homeCard(item) {
  if (item.cause === "cycle") {
    const names = item.members.map(m =>
      `<a href="#/task/${esc(m.id)}">${esc(m.title)}</a>`).join(" ⇄ ");
    return `<div class="card" data-key="cycle:${esc(cycleKey(item.members.length ? (item.hb?.detail?.cycle || item.members.map(m=>m.id)) : []))}">
      <div class="card-head"><span class="title">Dependency cycle</span>
        <span class="chip parked">needs untangling</span></div>
      <p>${names}</p>
      <p class="small muted">Each blocks the other; neither can proceed. Resolve by
      cancelling or re-scoping one member (edges cannot be removed) — open a task to act.</p>
    </div>`;
  }
  const t = item.task;
  return `<div class="card" data-task="${esc(t.id)}">
    ${cardHead(t, item)}
    <div class="ask">${esc(item.hb.reason)}</div>
    ${composerHTML(item)}
  </div>`;
}

function wireHome(items) {
  for (const item of items) {
    if (item.cause === "cycle") continue;
    const card = $app.querySelector(`[data-task="${CSS.escape(item.task.id)}"]`);
    if (card) wireComposer(card, item);
  }
}

/* ---------- Task Detail (docs/console/task-detail.md) ---------- */

async function renderTask(id) {
  $app.innerHTML = `<p class="muted">Loading ${esc(id)}…</p>`;
  let detail;
  try { detail = await api("/api/task/" + encodeURIComponent(id)); }
  catch (e) { $app.innerHTML = `<div class="error-box">${esc(e.message)}</div>`; return; }
  const task = detail.task, budget = detail.budget;
  const row = state.snap.tasks.find(t => t.id === id) || {};
  const info = row.id ? parkInfo(row) : null;

  let html = `<h1>${esc(task.title)}</h1>
    <p><span class="mono muted">${esc(task.id)}</span> ${chips(row.id ? row : { readiness: "?", active_artifacts: {} })}
    ${row.readiness_detail && row.readiness_detail.reason
      ? `<span class="muted"> — ${esc(row.readiness_detail.reason)}</span>` : ""}</p>`;
  if (task.source && task.source.reference) {
    const ref = String(task.source.reference);
    html += `<p class="small muted">source: ${/^https?:/.test(ref)
      ? `<a href="${esc(ref)}" target="_blank" rel="noopener">${esc(ref)}</a>` : esc(ref)}</p>`;
  }
  html += `<div class="desc">${esc(task.description)}</div>
           <p class="small muted">The immutable intake text — every judgment below is made against it.</p>`;

  html += `<h2>The story</h2><div class="story">${storyHTML(task, budget, row)}</div>`;

  if (info && info.cause !== "cycle") {
    html += `<h2>The ask</h2><div class="card" data-task="${esc(task.id)}">
      <div class="ask">${esc(info.hb.reason)}</div>${composerHTML({ ...info, task: row })}</div>`;
  }

  html += `<h2>Actions</h2><div class="card" data-task-actions="1"><div class="actions">`;
  if (["done", "cancelled"].includes(task.status))
    html += `<button data-act="reopen">Reopen…</button>`;
  else if (task.status !== "blocked_on_human" || (info && info.cause === "cycle"))
    html += `<button class="danger" data-act="cancel">Cancel…</button>`;
  html += `<button data-act="copy">Copy id</button></div><div data-role="msg"></div></div>`;

  html += relatedHTML(task.id);

  html += `<details><summary>Raw timeline (${task.history.length} events — the unabridged authority)</summary>
    <table class="timeline">${task.history.map(e => `<tr>
      <td class="mono muted">${esc((e.at || "").slice(0, 19))}</td>
      <td>${esc(e.type)}</td><td class="mono">${esc(e.actor)}</td>
      <td>${esc(e.reason || "")}</td></tr>`).join("")}</table></details>`;

  $app.innerHTML = html;

  if (info && info.cause !== "cycle") {
    const card = $app.querySelector(`[data-task="${CSS.escape(task.id)}"]`);
    if (card) wireComposer(card, { ...info, task: row });
  }
  const actions = $app.querySelector("[data-task-actions]");
  actions.addEventListener("click", async (ev) => {
    const act = ev.target.dataset && ev.target.dataset.act;
    if (act === "copy") navigator.clipboard.writeText(task.id);
    if (act === "cancel") {
      const reason = prompt("Cancellation reason (recorded forever):");
      if (reason) await command({ command: "cancel", id: task.id, text: { reason } },
                                actions.querySelector('[data-role="msg"]'));
    }
    if (act === "reopen") {
      const reason = prompt("Why is this task back?");
      if (reason) await command({ command: "reopen", id: task.id, text: { reason } },
                                actions.querySelector('[data-role="msg"]'));
    }
  });
}

function storyHTML(task, budget, row) {
  let h = "";
  const arts = task.artifacts || {};
  const active = k => (arts[k] || []).filter(a => !a.superseded).slice(-1)[0];
  const superseded = k => (arts[k] || []).filter(a => a.superseded);

  if (row.decision_ref)
    h += `<div class="story-row kind-decision"><span class="story-kind">bound by</span>
      <span class="story-body">decision v${esc(row.decision_ref.version)} of
      <a href="#/task/${esc(row.decision_ref.task_id)}">${esc(shortId(row.decision_ref.task_id))}</a>
      — binding input for this task</span></div>`;

  for (const kind of ["decision", "specification"]) {
    const a = active(kind);
    if (a) h += `<div class="story-row kind-${kind}"><span class="story-kind">${kind} v${a.version}</span>
      <span class="story-body">${esc(summaryOf(kind, a.payload))}</span></div>`;
    for (const s of superseded(kind))
      h += `<div class="superseded">↳ ${kind} v${s.version} superseded — ${esc(s.superseded_reason || "")}</div>`;
  }

  // Attempts: an implementation+review pair is one unit; pair by version.
  const impls = arts.implementation || [], reviews = arts.review || [];
  const rejectedCauses = [];
  impls.forEach((impl, i) => {
    const rev = reviews.find(r => r.version === impl.version) || reviews[i];
    const rejected = rev && rev.payload.verdict === "rejected";
    if (rejected) rejectedCauses.push(rev.payload.root_cause);
    h += `<div class="story-row attempt ${rejected ? "rejected" : ""}">
      <span class="story-kind">attempt ${impl.version}</span>
      <span class="story-body">${esc(impl.payload.summary)}
        <span class="mono muted">${esc(impl.payload.diff_ref)}</span>
        ${rev ? `<br>${rev.payload.verdict === "approved" ? "✓ approved"
          : `✗ rejected: ${esc(rev.payload.root_cause || "")}`}` : ""}
        ${rejected && rev.payload.findings ? rev.payload.findings.map(f =>
          `<br><span class="finding">— ${esc(f)}</span>`).join("") : ""}</span></div>`;
  });
  // Repetition is the diagnosis: same root_cause rejected 2+ times.
  const causeCounts = rejectedCauses.reduce((m, c) => (m[c] = (m[c] || 0) + 1, m), {});
  for (const [cause, n] of Object.entries(causeCounts))
    if (n >= 2) h += `<div class="repeat-flag">⟳ ${n} attempts rejected with root cause
      <b>${esc(cause)}</b> against the same spec — is the spec ambiguous, or the approach wrong?</div>`;

  if (budget && budget.total_reviews > 0)
    h += `<div class="story-row"><span class="story-kind">budget</span>
      <span class="story-body">${budget.review_rejections_in_current_cycle} of
      ${budget.max_review_retries} retries used</span></div>`;

  if (task.status === "blocked_on_human") {
    const hb = [...task.history].reverse().find(e => e.type === "human_blocked");
    if (hb) h += `<div class="story-row park"><span class="story-kind">parked</span>
      <span class="story-body">${esc(hb.reason)} <span class="muted">(${esc(ago(hb.at))})</span></span></div>`;
  }
  return h || `<p class="muted">No artifacts yet — this task hasn't been worked.</p>`;
}

function summaryOf(kind, payload) {
  if (kind === "decision") return payload.chosen_approach || "";
  if (kind === "specification") return payload.scope || "";
  return "";
}

function relatedHTML(id) {
  const phrases = [];
  for (const e of state.snap.edges) {
    const other = e.from === id ? e.to : (e.to === id ? e.from : null);
    if (!other) continue;
    const out = e.from === id;
    const text = {
      blocked_by: out ? "blocked by" : "blocking",
      parent: out ? "child of" : "parent of",
      generated_from: out ? "generated from" : "origin of",
      decision_ref: out ? `pinned to decision v${e.version} of` : `decision (v${e.version}) binds`,
    }[e.type] || e.type;
    const t = state.snap.tasks.find(x => x.id === other);
    phrases.push({ blocking: e.type === "blocked_by",
      html: `<li>${esc(text)} <a href="#/task/${esc(other)}">${esc(t ? t.title : shortId(other))}</a>
        <span class="mono muted">${esc(shortId(other))}</span></li>` });
  }
  if (!phrases.length) return "";
  phrases.sort((a, b) => Number(b.blocking) - Number(a.blocking)); // blocking first
  return `<h2>Related tasks</h2><ul>${phrases.map(p => p.html).join("")}</ul>`;
}

/* ---------- Board (docs/console/board-view.md) — read-only ---------- */

function renderBoard() {
  const cols = [
    ["refine", t => t.readiness === "refine"],
    ["explore", t => t.readiness === "explore"],
    ["run", t => t.readiness === "run"],
    ["waiting", t => t.readiness === "waiting"],
    ["needs a human", t => parkInfo(t) !== null],
  ];
  const childCount = {};
  for (const e of state.snap.edges)
    if (e.type === "parent") childCount[e.to] = (childCount[e.to] || 0) + 1;

  const bcard = t => `<div class="board-card">
    <a href="#/task/${esc(t.id)}">${esc(t.title)}</a><br>
    <span class="mono">${esc(shortId(t.id))}</span>
    ${t.status === "blocked_on_human" ? ' <span class="chip parked">parked</span>' : ""}
    ${childCount[t.id] ? ` <span class="chip artifact">${childCount[t.id]} children</span>` : ""}
    ${(t.readiness_detail && t.readiness_detail.blocking_ids)
      ? ` <span class="chip artifact">${t.readiness_detail.blocking_ids.length} blocker(s)</span>` : ""}
  </div>`;

  let html = `<h1>Board</h1>
    <p class="section-hint">A projection of derived readiness. Cards cannot be dragged —
    columns are derived and statuses are earned; act from a task's own page.</p>
    <div class="board">`;
  const used = new Set();
  for (const [label, pred] of cols) {
    const rows = state.snap.tasks.filter(t => !used.has(t.id) && pred(t));
    rows.forEach(t => used.add(t.id));
    html += `<div class="column"><h3>${esc(label)} (${rows.length})</h3>
      ${rows.map(bcard).join("") || '<p class="small muted">—</p>'}</div>`;
  }
  const terminal = state.snap.tasks.filter(t => !used.has(t.id));
  html += `</div><details><summary>terminal (${terminal.length})</summary>
    <div class="board"><div class="column">${terminal.map(bcard).join("")}</div></div></details>`;
  $app.innerHTML = html;
}

/* ---------- Graph (docs/console/graph-view.md) ---------- */

const graphToggles = { parent: true, generated_from: false, decision_ref: true, relates_to: false };

function renderGraph() {
  const tasks = state.snap.tasks, edges = state.snap.edges;
  const byId = new Map(tasks.map(t => [t.id, t]));

  // Layered layout on the blocking skeleton: blockers left, dependents right.
  // Deterministic: no physics, same snapshot -> same picture.
  const blockers = new Map(); // task -> [its blockers]
  for (const e of edges) if (e.type === "blocked_by")
    blockers.set(e.from, [...(blockers.get(e.from) || []), e.to]);
  const depth = new Map(), visiting = new Set(), cyclic = new Set();
  function d(id) {
    if (depth.has(id)) return depth.get(id);
    if (visiting.has(id)) { cyclic.add(id); return 0; }
    visiting.add(id);
    const v = Math.max(0, ...(blockers.get(id) || [])
      .filter(b => byId.has(b)).map(b => d(b) + 1));
    visiting.delete(id);
    depth.set(id, v);
    return v;
  }
  const connected = new Set();
  for (const e of edges) if (e.type === "blocked_by" && byId.has(e.from) && byId.has(e.to)) {
    connected.add(e.from); connected.add(e.to);
  }
  const NW = 172, NH = 46, GX = 90, GY = 26;
  const pos = new Map(), layers = new Map();
  const inGraph = tasks.filter(t => connected.has(t.id)).sort((a, b) => a.id.localeCompare(b.id));
  for (const t of inGraph) {
    const dep = d(t.id);
    const row = layers.get(dep) || 0;
    layers.set(dep, row + 1);
    pos.set(t.id, { x: 40 + dep * (NW + GX), y: 40 + row * (NH + GY) });
  }
  // Disconnected tasks: a quiet grid below the skeleton.
  const maxY = Math.max(40, ...[...pos.values()].map(p => p.y + NH));
  const rest = tasks.filter(t => !connected.has(t.id)).sort((a, b) => a.id.localeCompare(b.id));
  rest.forEach((t, i) => pos.set(t.id, {
    x: 40 + (i % 4) * (NW + 30), y: maxY + 50 + Math.floor(i / 4) * (NH + GY) }));

  const width = Math.max(760, ...[...pos.values()].map(p => p.x + NW + 40));
  const height = Math.max(300, ...[...pos.values()].map(p => p.y + NH + 40));

  let svg = `<svg width="${width}" height="${height}">
    <defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7"
      markerHeight="7" orient="auto-start-reverse">
      <path d="M0,0 L10,5 L0,10 z" fill="#b3261e"/></marker></defs>`;
  for (const e of edges) {
    if (e.type !== "blocked_by" && !graphToggles[e.type]) continue;
    const a = pos.get(e.from), b = pos.get(e.to);
    if (!a || !b) continue;
    const x1 = a.x + (b.x > a.x ? NW : 0), y1 = a.y + NH / 2;
    const x2 = b.x + (b.x > a.x ? 0 : NW), y2 = b.y + NH / 2;
    const mx = (x1 + x2) / 2;
    svg += `<path class="edge-${esc(e.type)}" d="M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}"
      ${e.type === "blocked_by" ? 'marker-end="url(#arrow)"' : ""}/>`;
    if (e.type === "decision_ref")
      svg += `<text class="edge-label" x="${mx}" y="${(y1 + y2) / 2 - 4}">v${esc(e.version)}</text>`;
  }
  for (const t of tasks) {
    const p = pos.get(t.id);
    const parked = t.status === "blocked_on_human" || t.readiness === "human";
    svg += `<a href="#/task/${esc(t.id)}"><g class="node ${parked ? "parked" : ""}">
      <rect x="${p.x}" y="${p.y}" width="${NW}" height="${NH}"></rect>
      <text x="${p.x + 10}" y="${p.y + 19}">${esc(t.title.length > 22 ? t.title.slice(0, 21) + "…" : t.title)}</text>
      <text x="${p.x + 10}" y="${p.y + 36}" class="mono" fill="#8a9099" font-size="10.5">
        ${esc(shortId(t.id))} · ${esc(t.status === "blocked_on_human" ? "parked" : t.readiness)}</text>
    </g></a>`;
  }
  svg += `</svg>`;

  $app.innerHTML = `<h1>Graph</h1>
    <p class="section-hint">The blocking skeleton is the foreground — it is the only
    edge readiness reads. Provenance is discoverable, not ambient.</p>
    <div class="legend">
      <span><span class="sw" style="border-color:#b3261e"></span>blocked_by</span>
      <label><input type="checkbox" data-toggle="parent" ${graphToggles.parent ? "checked" : ""}>
        <span class="sw" style="border-color:#b9c0c7"></span>parent</label>
      <label><input type="checkbox" data-toggle="generated_from" ${graphToggles.generated_from ? "checked" : ""}>
        <span class="sw" style="border-color:#b9c0c7;border-top-style:dashed"></span>generated_from</label>
      <label><input type="checkbox" data-toggle="decision_ref" ${graphToggles.decision_ref ? "checked" : ""}>
        <span class="sw" style="border-color:#7a3bb8;border-top-style:dotted"></span>decision_ref</label>
    </div>
    <div class="graph-wrap">${svg}</div>`;
  $app.querySelectorAll("[data-toggle]").forEach(cb =>
    cb.addEventListener("change", () => { graphToggles[cb.dataset.toggle] = cb.checked; renderGraph(); }));
}

/* ---------- boot ---------- */

refresh().catch(e => { $app.innerHTML = `<div class="error-box">${esc(e.message)}</div>`; });
/* Background poll: re-render ONLY when the store actually changed, and never
 * while the human is mid-composition — a re-render would destroy their
 * unsubmitted note (found live in browser testing). */
setInterval(async () => {
  try {
    const changed = await loadSnap();
    const el = document.activeElement;
    const typing = el && /^(TEXTAREA|INPUT)$/.test(el.tagName);
    if (changed && !typing) route();
  } catch (e) { /* transient; next tick retries */ }
}, 8000);
