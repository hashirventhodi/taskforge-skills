/* TaskForge Web UI — a client of the Projection API (docs/PROJECTION_API.md).
   Every screen renders one projection (the Dashboard composes board + health +
   feature summaries). No engine logic here: the UI maps projection state to
   visuals and nothing more. Untrusted text is always escaped. */
"use strict";

const view = document.getElementById("view");
const railFoot = document.getElementById("rail-foot");
const SPIN = '<div class="spinner"><i></i>Loading…</div>';

const api = (p) => fetch("/api/p/" + p).then((r) => r.json());
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const md = (s) => (window.renderMarkdown ? renderMarkdown(s) : esc(s));

function relTime(iso) {
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 45) return "just now";
  const units = [["y", 31536000], ["mo", 2592000], ["d", 86400], ["h", 3600], ["m", 60]];
  for (const [u, n] of units) if (s >= n) return `${Math.floor(s / n)}${u} ago`;
  return "just now";
}
function sinceFor(range) {
  if (range === "all") return "0000-01-01T00:00:00+00:00";
  const hours = { "24h": 24, "7d": 168, "30d": 720 }[range] || 168;
  return new Date(Date.now() - hours * 3600e3).toISOString().replace("Z", "+00:00");
}

/* state -> pill. terminal (how it finished) wins over readiness (where active). */
function statePill(card) {
  const v = card.terminal || card.readiness;
  return `<span class="pill p-${esc(v)}">${esc(v)}</span>`;
}
/* Audit Status is its own domain concept, distinct from the review verdict. */
const AUDIT = {
  verified: { cls: "p-approved", label: "isolated" },
  breach: { cls: "p-rejected", label: "isolation breach" },
  unrecorded: { cls: "p-refine", label: "unaudited" },
  none: { cls: "p-waiting", label: "no review" },
};
const auditPill = (s) => `<span class="pill ${(AUDIT[s] || AUDIT.none).cls}">${(AUDIT[s] || AUDIT.none).label}</span>`;

function taskRow(card, extra = "") {
  const route = card.is_feature ? "feature" : "task";
  const land = card.is_feature && card.landable != null
    ? `<span class="pill ${card.landable ? "p-landed" : "p-open"}">${card.landable ? "landable" : "blocked"}</span>` : "";
  const meta = [card.feature ? "▸ " + esc(card.feature.title) : "", esc(card.id)].filter(Boolean).join("  ·  ");
  return `<div class="row link" onclick="go('${route}/${card.id}')" role="link" tabindex="0">
      ${statePill(card)}
      <div class="rmain"><div class="rtitle">${esc(card.title)}</div><div class="rmeta">${meta}</div></div>
      ${extra}${land}<span class="go">→</span></div>`;
}
function go(path) { location.hash = "#/" + path; }
window.go = go;
function setView(html) { view.innerHTML = html; }

/* ---- Dashboard: board + health + in-flight feature summaries ---- */
async function dashboard() {
  const [b, h] = await Promise.all([api("board"), api("health")]);
  const nextId = b.next ? b.next.id : null;
  const groups = [["run", "Ready to run"], ["refine", "Needs a spec"], ["explore", "Pending decision"]];
  // dedup: the hero (next) never repeats in the Ready list below it.
  const readyHtml = groups
    .map(([k, label]) => [label, b.ready[k].filter((c) => c.id !== nextId)])
    .filter(([, items]) => items.length)
    .map(([label, items]) => `<div style="margin-bottom:4px"><div class="kick">${label} · ${items.length}</div>${items.map((c) => taskRow(c)).join("")}</div>`)
    .join("") || `<div class="empty">Nothing else ready — the next action above is it.</div>`;

  const human = b.awaiting_human.length
    ? b.awaiting_human.map((i) =>
      `<div class="row link" onclick="go('task/${i.task.id}')" role="link" tabindex="0">
        <span class="pill p-blocked_on_human">${esc(i.kind)}</span>
        <span class="ti">${esc(i.prompt || i.task.title)}</span>
        <span class="id">${esc(i.task.id)}</span><span class="go">→</span></div>`).join("")
    : `<div class="empty">Nothing needs you right now.</div>`;

  const featIds = new Set();
  for (const c of [...b.ready.run, ...b.ready.refine, ...b.ready.explore, ...b.waiting]) {
    if (c.is_feature) featIds.add(c.id);
    if (c.feature) featIds.add(c.feature.id);
  }
  const feats = (await Promise.all([...featIds].map((id) => api("feature/" + id).catch(() => null))))
    .filter((f) => f && f.delivery && f.delivery.branch && !f.delivery.landed_at);
  const inflight = feats.length ? feats.map((f) => {
    const pct = f.progress.total ? Math.round(100 * f.progress.closed / f.progress.total) : 0;
    return `<div class="row link" onclick="go('feature/${f.ref.id}')" role="link" tabindex="0">
      <span class="ti">${esc(f.ref.title)}</span>
      <span class="pill ${f.landing.landable ? "p-landed" : "p-open"}">${f.progress.closed}/${f.progress.total}</span>
      <span class="sub dim">${esc(f.delivery.branch)}</span><span class="go">→</span></div>`;
  }).join("") : `<div class="empty">No features in flight.</div>`;

  const next = b.next
    ? `<div class="card hero"><div class="kick acc">Next — do this</div>${taskRow(b.next)}</div>`
    : `<div class="card"><div class="kick">Next</div><div class="empty">No actionable work — you're all caught up.</div></div>`;

  setView(`<h1>Dashboard</h1><p class="lede">What needs you, and what to do next.</p>
    ${next}
    <div class="card"><div class="kick">Needs you<span class="r">${b.awaiting_human.length}</span></div>${human}</div>
    <div class="grid2">
      <div class="card"><div class="kick">Ready</div>${readyHtml}</div>
      <div>
        <div class="card"><div class="kick">In flight<span class="r">${feats.length}</span></div>${inflight}</div>
        <div class="card"><div class="kick">Health</div>
          <div class="check"><span class="m ${h.structural.sound ? "ok" : "no"}">${h.structural.sound ? "✓" : "✕"}</span>structural integrity ${h.structural.sound ? "sound" : "issues"}</div>
          <div class="check"><span class="m ${h.audit.breach ? "no" : h.audit.unrecorded ? "pend" : "ok"}">${h.audit.breach ? "✕" : h.audit.unrecorded ? "•" : "✓"}</span>reviews · ${h.audit.breach} breach · ${h.audit.unrecorded} unaudited</div>
          <div class="check"><span class="m pend">•</span>${h.delivery.done_unlanded.length} done, not landed<a class="sub" href="#/health" style="margin-left:auto;color:var(--accent)">details →</a></div>
        </div>
      </div>
    </div>`);
  railFoot.innerHTML = `<b>run</b> ${b.counts.run} · <b>refine</b> ${b.counts.refine} · <b>explore</b> ${b.counts.explore}<br><b>wait</b> ${b.counts.waiting} · <b>you</b> ${b.counts.awaiting_human} · <b>done</b> ${b.counts.terminal}<br><span style="opacity:.7">d·a·h nav · ? help</span>`;
}

/* ---- Task Focus ---- */
async function taskFocus(id) {
  const t = await api("task/" + id);
  if (t.error) return fail(t.error);
  const crumb = t.feature
    ? `<div class="crumb"><a href="#/feature/${t.feature.id}">${esc(t.feature.title)}</a><span class="sep">/</span>${esc(t.ref.title)}</div>` : "";
  const criteria = t.spec ? t.spec.criteria.map((c) =>
    `<div class="check"><span class="m ${c.result === "pass" ? "ok" : c.result === "fail" ? "no" : "pend"}">${c.result === "pass" ? "✓" : c.result === "fail" ? "✕" : "•"}</span>${esc(c.text)}</div>`).join("") : "";
  const spec = t.spec
    ? `<div class="card"><div class="kick">Specification v${t.spec.version} — the contract</div>
        <p class="sub" style="margin:0 0 8px">${esc(t.spec.scope)}</p>${criteria}</div>`
    : `<div class="card"><div class="kick">Specification</div><div class="empty">No active spec — routes to ${esc(t.readiness)}.</div></div>`;
  const review = t.review
    ? `<div class="row link" onclick="go('review/${t.ref.id}')" role="link" tabindex="0">
        <span class="pill p-${t.review.verdict || "open"}">${esc(t.review.verdict || "in review")}</span>
        <span class="ti">${t.review.attempts} attempt(s) · did the work pass</span><span class="go">→</span></div>
       <div class="row" style="border-top:0">${auditPill(t.audit.status)}<span class="sub" style="align-self:center">can the review be trusted (isolation)</span></div>`
    : `<div class="empty">No review yet.</div>`;
  const list = (label, arr) => arr.length
    ? `<div class="kick" style="margin-top:12px">${label}</div>${arr.map((c) => taskRow(c)).join("")}` : "";
  const d = t.delivery;
  setView(`${crumb}<h1>${esc(t.ref.title)} ${statePill(t)}</h1>
    <div class="grid2">
      <div>${spec}<div class="card"><div class="kick">Review</div>${review}</div></div>
      <div>
        <div class="card"><div class="kick">Delivery</div>
          ${d ? `<div class="kv"><b>${d.owner.id === t.ref.id ? "branch" : "via " + esc(d.owner.title)}</b><span>${esc(d.branch || "—")}</span></div>
            <div class="kv"><b>pr</b><span>${esc(d.pr || "—")}</span></div>
            <div class="kv"><b>landed</b><span>${d.landed_at ? relTime(d.landed_at) : "not yet"}</span></div>`
            : `<div class="empty">Not linked to a branch yet.</div>`}</div>
        <div class="card"><div class="kick">Relationships</div>
          ${list("Blocked by", t.blockers) || `<div class="empty">No blockers.</div>`}
          ${list("Blocks", t.blocks)}${list("Follow-ups", t.follow_ups)}</div>
      </div>
    </div>
    <div class="card"><div class="kick">Description</div><div class="md">${md(t.description)}</div></div>`);
}

/* ---- Feature ---- */
async function feature(id) {
  const f = await api("feature/" + id);
  if (f.error) return fail(f.error);
  const kids = f.children.length ? f.children.map((c) =>
    `<div class="row link" onclick="go('${c.is_feature ? "feature" : "task"}/${c.id}')" role="link" tabindex="0" style="padding-left:${9 + c.depth * 18}px">
      ${statePill(c)}<span class="ti">${esc(c.title)}</span>
      ${c.review_state !== "none" ? `<span class="pill p-${c.review_state}">${esc(c.review_state)}</span>` : ""}
      <span class="go">→</span></div>`).join("") : `<div class="empty">No children — a standalone unit.</div>`;
  const pct = f.progress.total ? Math.round(100 * f.progress.closed / f.progress.total) : 0;
  setView(`<div class="crumb"><a href="#/">Dashboard</a><span class="sep">/</span>${esc(f.ref.title)}</div>
    <h1>${esc(f.ref.title)} ${statePill(f)}</h1>
    <div class="grid2">
      <div class="card"><div class="kick">Delivery</div>
        <div class="kv"><b>branch</b><span>${esc(f.delivery.branch || "—")}</span></div>
        <div class="kv"><b>pr</b><span>${esc(f.delivery.pr || "—")}</span></div>
        <div class="kv"><b>landed</b><span>${f.delivery.landed_at ? relTime(f.delivery.landed_at) : "not yet"}</span></div></div>
      <div class="card"><div class="kick">Land readiness</div>
        <div class="check"><span class="m ${f.landing.landable ? "ok" : "no"}">${f.landing.landable ? "✓" : "✕"}</span>${f.landing.landable ? "ready to land" : "not landable"}</div>
        ${f.landing.blockers.map((c) => taskRow(c)).join("")}
        <div class="kick" style="margin-top:14px">Review audit</div>
        <div class="check">${auditPill(f.audit.status)}<span class="sub" style="align-self:center">${f.audit.breach} breach · ${f.audit.unrecorded} unaudited · ${f.audit.verified} verified</span></div></div>
    </div>
    <div class="card"><div class="kick">Children<span class="r">${f.progress.closed}/${f.progress.total} closed</span></div>
      <div class="bar"><i style="width:${pct}%"></i></div><div style="margin-top:10px">${kids}</div></div>`);
}

/* ---- Review ---- */
async function review(id) {
  const r = await api("review/" + id);
  if (r.error) return fail(r.error);
  const crit = r.criteria.map((c) =>
    `<div class="check"><span class="m ${c.result === "pass" ? "ok" : c.result === "fail" ? "no" : "pend"}">${c.result === "pass" ? "✓" : c.result === "fail" ? "✕" : "•"}</span>${esc(c.text)}</div>`).join("") || `<div class="empty">No criteria.</div>`;
  const attempts = r.attempts.map((a) =>
    `<div class="row"><span class="pill p-${a.verdict}">v${a.version} ${esc(a.verdict)}</span>
      <span class="ti sub">${a.root_cause ? `<b>${esc(a.root_cause)}:</b> ` : ""}${esc((a.findings || []).join("; ")) || "—"}</span></div>`).join("");
  const note = { verified: "reviewer isolated, prompts recorded", breach: "isolation violated — see below", unrecorded: "reviewer prompt not recorded", none: "no reviews" }[r.audit.status];
  setView(`<div class="crumb"><a href="#/task/${r.ref.id}">${esc(r.ref.title)}</a><span class="sep">/</span>review</div>
    <h1>Review — ${esc(r.ref.title)}</h1>
    <div class="grid2">
      <div class="card"><div class="kick">Acceptance</div>${crit}</div>
      <div class="card"><div class="kick">Isolation audit</div>
        <div class="check">${auditPill(r.audit.status)}<span class="sub" style="align-self:center">${note}</span></div>
        ${r.audit.findings.map((f) => `<div class="check"><span class="m no">✕</span>${esc(f)}</div>`).join("")}
        <div class="kv" style="margin-top:10px"><b>budget</b><span>${r.budget.retries_used} of ${r.budget.retries_max} retries used</span></div></div>
    </div>
    <div class="card"><div class="kick">Attempts</div>${attempts || `<div class="empty">No reviews yet.</div>`}</div>`);
}

/* ---- Activity (Digest) — visible ranges, never hidden behind local state ---- */
async function activity(range) {
  range = range || "7d";
  const d = await api("digest?since=" + encodeURIComponent(sinceFor(range)));
  const RANGES = [["24h", "Last 24h"], ["7d", "7 days"], ["30d", "30 days"], ["all", "All"]];
  const tabs = `<div class="tabs">${RANGES.map(([r, l]) => `<a class="tab ${r === range ? "on" : ""}" href="#/activity/${r}">${l}</a>`).join("")}</div>`;
  const labels = { awaiting_human: "Now needs you", landed: "Landed", done: "Done", escalated: "Escalated", reopened: "Reopened" };
  const body = d.total
    ? Object.keys(labels).filter((k) => d.groups[k].length).map((k) =>
      `<div class="card"><div class="kick acc">${labels[k]}<span class="r">${d.groups[k].length}</span></div>${d.groups[k].map((i) =>
        `<div class="row link" onclick="go('task/${i.task.id}')" role="link" tabindex="0">
          <span class="ti">${esc(i.task.title)}</span>${i.note ? `<span class="sub dim">${esc(i.note)}</span>` : ""}
          <span class="id" title="${esc(i.at)}">${relTime(i.at)}</span><span class="go">→</span></div>`).join("")}</div>`).join("")
    : `<div class="empty">Nothing changed in this range. Try a wider one above.</div>`;
  setView(`<h1>Activity</h1><p class="lede">Meaningful changes, grouped by impact — not a raw log.</p>${tabs}${body}`);
}

/* ---- Health ---- */
async function health() {
  const h = await api("health");
  const structural = h.structural.sound
    ? `<div class="check"><span class="m ok">✓</span>graph sound — no dangling edges, cycles, or bad refs</div>`
    : h.structural.issues.map((i) => `<div class="check"><span class="m no">✕</span>${esc(i.message)}</div>`).join("");
  const audit = h.audit.needs_attention.length
    ? h.audit.needs_attention.map((n) => `<div class="row link" onclick="go('review/${n.task.id}')" role="link" tabindex="0">${auditPill(n.status)}<span class="ti">${esc(n.task.title)}</span><span class="id">${esc(n.task.id)}</span><span class="go">→</span></div>`).join("")
    : `<div class="check"><span class="m ok">✓</span>every review is isolated and recorded</div>`;
  const delivery = h.delivery.done_unlanded.length
    ? h.delivery.done_unlanded.map((c) => taskRow(c)).join("")
    : `<div class="check"><span class="m ok">✓</span>nothing reviewed is sitting unmerged</div>`;
  setView(`<h1>Health</h1><p class="lede">Three separate concerns — never conflated.</p>
    <div class="card"><div class="kick">Structural integrity</div>${structural}</div>
    <div class="card"><div class="kick">Review audit<span class="r">${h.audit.breach} breach · ${h.audit.unrecorded} unaudited · ${h.audit.verified} verified</span></div>${audit}</div>
    <div class="card"><div class="kick">Delivery — done but not landed<span class="r">${h.delivery.done_unlanded.length}</span></div>${delivery}</div>`);
}

/* ---- help overlay ---- */
function toggleHelp() {
  const ex = document.getElementById("help");
  if (ex) return ex.remove();
  const el = document.createElement("div");
  el.id = "help"; el.className = "overlay"; el.onclick = () => el.remove();
  el.innerHTML = `<div class="box" onclick="event.stopPropagation()"><h3>Keyboard</h3>
    <div class="kv"><span>Dashboard</span><b>d</b></div><div class="kv"><span>Activity</span><b>a</b></div>
    <div class="kv"><span>Health</span><b>h</b></div><div class="kv"><span>Back</span><b>esc</b></div>
    <div class="kv"><span>This help</span><b>?</b></div></div>`;
  document.body.appendChild(el);
}

/* ---- router ---- */
function fail(msg) {
  setView(`<div class="errbox"><div class="t">Couldn't load that</div><p class="sub">${esc(msg)}</p>
    <button class="btn" onclick="route()">Retry</button>
    <a class="btn" href="#/" style="margin-left:8px;background:var(--panel-2);color:var(--ink)">← Dashboard</a></div>`);
}
async function route() {
  const h = location.hash.replace(/^#\/?/, "");
  const [seg, arg] = h.split("/");
  const navSeg = ["task", "feature", "review"].includes(seg) ? "" : seg;
  document.querySelectorAll(".nav").forEach((n) => n.classList.toggle("on", n.dataset.nav === navSeg));
  view.innerHTML = SPIN;
  try {
    if (seg === "task") return await taskFocus(arg);
    if (seg === "feature") return await feature(arg);
    if (seg === "review") return await review(arg);
    if (seg === "activity") return await activity(arg);
    if (seg === "health") return await health();
    return await dashboard();
  } catch (e) { fail(e.message || String(e)); }
}
window.route = route;
window.addEventListener("hashchange", route);
document.addEventListener("keydown", (e) => {
  if (e.target.matches("input,textarea,select") || e.metaKey || e.ctrlKey || e.altKey) return;
  if (e.key === "?") { e.preventDefault(); return toggleHelp(); }
  if (e.key === "Escape") { const hp = document.getElementById("help"); return hp ? hp.remove() : history.back(); }
  const map = { d: "", a: "activity", h: "health" };
  if (e.key in map) { e.preventDefault(); go(map[e.key]); }
});
route();
