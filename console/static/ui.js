/* TaskForge Web UI — a client of the Projection API (docs/PROJECTION_API.md).
   Every screen renders exactly one projection (Dashboard composes board +
   health + feature summaries). No engine logic here: the UI maps projection
   state to visuals and nothing more. Untrusted text is always escaped. */
"use strict";

const view = document.getElementById("view");
const railFoot = document.getElementById("rail-foot");

const api = (p) => fetch("/api/p/" + p).then((r) => r.json());
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

/* state -> pill. terminal wins over readiness (a finished task shows how it
   finished; an active one shows where it routes). */
function statePill(card) {
  const v = card.terminal || card.readiness;
  return `<span class="pill p-${esc(v)}">${esc(v)}</span>`;
}
function taskRow(card) {
  const route = card.is_feature ? "feature" : "task";
  const land = card.is_feature && card.landable != null
    ? `<span class="pill ${card.landable ? "p-landed" : "p-open"}">${card.landable ? "landable" : "blocked"}</span>` : "";
  const feat = card.feature ? `<span class="sub">▸ ${esc(card.feature.title)}</span>` : "";
  return `<div class="row link" onclick="go('${route}/${card.id}')">
      ${statePill(card)}<span class="ti">${esc(card.title)}</span>${feat}${land}
      <span class="id">${esc(card.id)}</span></div>`;
}
function go(path) { location.hash = "#/" + path; }
window.go = go;

/* ---- Dashboard: board + health + in-flight feature summaries ---- */
async function dashboard() {
  const [b, h] = await Promise.all([api("board"), api("health")]);
  const groups = [["run", "Ready to run"], ["refine", "Needs a spec"], ["explore", "Pending decision"]];
  const readyHtml = groups.filter(([k]) => b.ready[k].length).map(([k, label]) =>
    `<div class="grp"><div class="kick">${label} · ${b.ready[k].length}</div>${b.ready[k].map(taskRow).join("")}</div>`
  ).join("") || `<div class="empty">Nothing ready — everything is waiting, parked, or done.</div>`;

  const human = b.awaiting_human.length
    ? b.awaiting_human.map((i) =>
      `<div class="row link" onclick="go('task/${i.task.id}')">
        <span class="pill p-blocked_on_human">${esc(i.kind)}</span>
        <span class="ti">${esc(i.prompt || i.task.title)}</span>
        <span class="id">${esc(i.task.id)}</span></div>`).join("")
    : `<div class="empty">Nothing needs you.</div>`;

  // in-flight features: distinct owners seen on the board, linked & not landed
  const featIds = new Set();
  for (const c of [...b.ready.run, ...b.ready.refine, ...b.ready.explore, ...b.waiting]) {
    if (c.is_feature) featIds.add(c.id);
    if (c.feature) featIds.add(c.feature.id);
  }
  const feats = (await Promise.all([...featIds].map((id) => api("feature/" + id).catch(() => null))))
    .filter((f) => f && f.delivery && f.delivery.branch && !f.delivery.landed_at);
  const inflight = feats.length ? feats.map((f) => {
    const pct = f.progress.total ? Math.round(100 * f.progress.closed / f.progress.total) : 0;
    return `<div class="row link" onclick="go('feature/${f.ref.id}')">
      <span class="ti">${esc(f.ref.title)}</span>
      <span class="pill ${f.landing.landable ? "p-landed" : "p-open"}">${f.progress.closed}/${f.progress.total}</span>
      <span class="sub">${esc(f.delivery.branch)}${f.delivery.pr ? " · " + esc(f.delivery.pr) : ""}</span></div>`;
  }).join("") : `<div class="empty">No features in flight.</div>`;

  const next = b.next
    ? `<div class="card hero"><div class="kick acc">Next — do this</div>${taskRow(b.next)}</div>`
    : `<div class="card"><div class="kick">Next</div><div class="empty">No actionable work.</div></div>`;

  view.innerHTML = `<h1>Dashboard</h1>
    <p class="muted">What needs you, and what to do next.</p>
    ${next}
    <div class="card"><div class="kick">Needs you · ${b.awaiting_human.length}</div>${human}</div>
    <div class="grid2">
      <div class="card"><h2 style="margin-top:0">Ready</h2>${readyHtml}</div>
      <div class="card"><h2 style="margin-top:0">In flight</h2>${inflight}
        <div class="kick" style="margin-top:14px">Health</div>
        <div class="check"><span class="m ${h.integrity_ok ? "ok" : "no"}">${h.integrity_ok ? "✓" : "✕"}</span>integrity ${h.integrity_ok ? "intact" : "issues"}</div>
        <div class="check"><span class="m pend">•</span>${h.unaudited_reviews.length} unaudited · ${h.done_unlanded.length} done, not landed
          <a class="sub" href="#/health" style="margin-left:auto">details →</a></div>
      </div>
    </div>`;
  railFoot.textContent = `run ${b.counts.run} · refine ${b.counts.refine} · explore ${b.counts.explore}
  wait ${b.counts.waiting} · you ${b.counts.awaiting_human} · done ${b.counts.terminal}`;
}

/* ---- Task Focus ---- */
async function taskFocus(id) {
  const t = await api("task/" + id);
  if (t.error) return fail(t.error);
  const crumb = t.feature
    ? `<div class="crumb"><a href="#/feature/${t.feature.id}">${esc(t.feature.title)}</a> / ${esc(t.ref.title)}</div>` : "";
  const criteria = t.spec ? t.spec.criteria.map((c) =>
    `<div class="check"><span class="m ${c.result === "pass" ? "ok" : c.result === "fail" ? "no" : "pend"}">${c.result === "pass" ? "✓" : c.result === "fail" ? "✕" : "•"}</span>${esc(c.text)}</div>`).join("") : "";
  const spec = t.spec
    ? `<div class="card"><div class="kick">Specification v${t.spec.version} — the contract</div>
        <p class="sub">${esc(t.spec.scope)}</p>${criteria}</div>`
    : `<div class="card"><div class="kick">Specification</div><div class="empty">No active spec — this task routes to ${esc(t.readiness)}.</div></div>`;
  const review = t.review
    ? `<div class="row link" onclick="go('review/${t.ref.id}')">
        <span class="pill p-${t.review.latest_verdict || "open"}">${esc(t.review.latest_verdict || "in review")}</span>
        <span class="ti">${t.review.attempts} attempt(s)</span>
        <span class="sub">${t.review.audited ? "audited ✓" : "unaudited"}</span></div>`
    : `<div class="empty">No review yet.</div>`;
  const list = (label, arr) => arr.length
    ? `<div class="kick" style="margin-top:10px">${label}</div>${arr.map(taskRow).join("")}` : "";
  const d = t.delivery;
  view.innerHTML = `${crumb}<h1>${esc(t.ref.title)} ${statePill(t)}</h1>
    <div class="grid2">
      <div>${spec}
        <div class="card"><div class="kick">Review</div>${review}</div></div>
      <div>
        <div class="card"><div class="kick">Delivery</div>
          ${d ? `<div class="kv"><b>${d.owner.id === t.ref.id ? "branch" : "via " + esc(d.owner.title)}</b><span>${esc(d.branch || "—")}</span></div>
            <div class="kv"><b>pr</b><span>${esc(d.pr || "—")}</span></div>
            <div class="kv"><b>landed</b><span>${d.landed_at ? "yes" : "not yet"}</span></div>`
            : `<div class="empty">Not linked.</div>`}</div>
        <div class="card"><div class="kick">Relationships</div>
          ${list("Blocked by", t.blockers) || `<div class="empty">No blockers.</div>`}
          ${list("Blocks", t.blocks)}${list("Follow-ups", t.follow_ups)}</div>
      </div>
    </div>
    <div class="card"><div class="kick">Description</div><div class="desc">${esc(t.description)}</div></div>`;
}

/* ---- Feature ---- */
async function feature(id) {
  const f = await api("feature/" + id);
  if (f.error) return fail(f.error);
  const kids = f.children.length ? f.children.map((c) =>
    `<div class="row link" onclick="go('${c.is_feature ? "feature" : "task"}/${c.id}')" style="padding-left:${8 + c.depth * 16}px">
      ${statePill(c)}<span class="ti">${esc(c.title)}</span>
      <span class="pill p-${c.review_state === "approved" ? "approved" : c.review_state === "rejected" ? "rejected" : "waiting"}">${esc(c.review_state)}</span>
    </div>`).join("") : `<div class="empty">No children — standalone unit.</div>`;
  const blockers = f.landing.blockers.map(taskRow).join("");
  const pct = f.progress.total ? Math.round(100 * f.progress.closed / f.progress.total) : 0;
  view.innerHTML = `<div class="crumb"><a href="#/">Dashboard</a> / ${esc(f.ref.title)}</div>
    <h1>${esc(f.ref.title)} ${statePill(f)}</h1>
    <div class="grid2">
      <div class="card"><div class="kick">Delivery</div>
        <div class="kv"><b>branch</b><span>${esc(f.delivery.branch || "—")}</span></div>
        <div class="kv"><b>pr</b><span>${esc(f.delivery.pr || "—")}</span></div>
        <div class="kv"><b>landed</b><span>${f.delivery.landed_at ? "yes" : "not yet"}</span></div></div>
      <div class="card"><div class="kick">Land readiness</div>
        <div class="check"><span class="m ${f.landing.landable ? "ok" : "no"}">${f.landing.landable ? "✓" : "✕"}</span>${f.landing.landable ? "ready to land" : "not landable"}</div>
        ${blockers}
        <div class="kick" style="margin-top:12px">Audit</div>
        <div class="check"><span class="m ${f.audit.reviews_unaudited ? "pend" : "ok"}">${f.audit.reviews_unaudited ? "•" : "✓"}</span>${f.audit.reviews_total} reviews · ${f.audit.reviews_unaudited} unaudited</div></div>
    </div>
    <div class="card"><div class="kick">Children · ${f.progress.closed}/${f.progress.total} closed</div>
      <div class="bar"><i style="width:${pct}%"></i></div><div style="margin-top:8px">${kids}</div></div>`;
}

/* ---- Review ---- */
async function review(id) {
  const r = await api("review/" + id);
  if (r.error) return fail(r.error);
  const crit = r.criteria.map((c) =>
    `<div class="check"><span class="m ${c.result === "pass" ? "ok" : c.result === "fail" ? "no" : "pend"}">${c.result === "pass" ? "✓" : c.result === "fail" ? "✕" : "•"}</span>${esc(c.text)}</div>`).join("") || `<div class="empty">No criteria.</div>`;
  const attempts = r.attempts.map((a) =>
    `<div class="row"><span class="pill p-${a.verdict}">v${a.version} ${esc(a.verdict)}</span>
      <span class="ti sub">${a.root_cause ? esc(a.root_cause) + ": " : ""}${esc((a.findings || []).join("; ")) || "—"}</span></div>`).join("");
  view.innerHTML = `<div class="crumb"><a href="#/task/${r.ref.id}">${esc(r.ref.title)}</a> / review</div>
    <h1>Review — ${esc(r.ref.title)}</h1>
    <div class="grid2">
      <div class="card"><div class="kick">Acceptance</div>${crit}</div>
      <div class="card"><div class="kick">Isolation audit</div>
        <div class="check"><span class="m ${r.audit.isolated ? "ok" : "no"}">${r.audit.isolated ? "✓" : "✕"}</span>${r.audit.isolated ? "reviewer isolated, prompts recorded" : "isolation issues"}</div>
        ${r.audit.findings.map((f) => `<div class="check"><span class="m no">✕</span>${esc(f)}</div>`).join("")}
        <div class="kv" style="margin-top:10px"><b>budget</b><span>${r.budget.retries_used} of ${r.budget.retries_max} retries used</span></div></div>
    </div>
    <div class="card"><div class="kick">Attempts</div>${attempts || `<div class="empty">No reviews yet.</div>`}</div>`;
}

/* ---- Activity (Digest) ---- */
async function activity() {
  const since = localStorage.getItem("tf_last") || "1970-01-01T00:00:00+00:00";
  const d = await api("digest?since=" + encodeURIComponent(since));
  const labels = { landed: "Landed", done: "Done", awaiting_human: "Now needs you",
    escalated: "Escalated", reopened: "Reopened" };
  let newest = since;
  const blocks = Object.keys(labels).filter((k) => d.groups[k].length).map((k) => {
    const items = d.groups[k].map((i) => {
      if (i.at > newest) newest = i.at;
      return `<div class="row link" onclick="go('task/${i.task.id}')">
        <span class="ti">${esc(i.task.title)}</span><span class="sub">${esc(i.note)}</span>
        <span class="id">${esc(i.at.slice(0, 16).replace("T", " "))}</span></div>`;
    }).join("");
    return `<div class="card"><div class="kick acc">${labels[k]} · ${d.groups[k].length}</div>${items}</div>`;
  }).join("") || `<div class="empty">Nothing has changed since your last visit.</div>`;
  view.innerHTML = `<h1>Activity</h1>
    <p class="muted">What changed since your last visit — grouped by impact.</p>${blocks}`;
  localStorage.setItem("tf_last", newest);
}

/* ---- Health ---- */
async function health() {
  const h = await api("health");
  const cards = (label, arr, render) => `<div class="card"><div class="kick">${label} · ${arr.length}</div>${arr.length ? arr.map(render).join("") : `<div class="empty">None.</div>`}</div>`;
  view.innerHTML = `<h1>Health</h1>
    <div class="card"><div class="kick">Integrity</div>
      <div class="check"><span class="m ${h.integrity_ok ? "ok" : "no"}">${h.integrity_ok ? "✓" : "✕"}</span>${h.integrity_ok ? "no dangling edges, cycles, or bad refs" : "integrity issues below"}</div></div>
    ${cards("Done but not landed", h.done_unlanded, taskRow)}
    ${cards("Unaudited reviews", h.unaudited_reviews, (u) =>
      `<div class="row link" onclick="go('review/${u.id}')"><span class="ti">${esc(u.title)}</span><span class="id">v${u.version} · ${esc(u.id)}</span></div>`)}
    ${h.findings.length ? cards("Diagnostics", h.findings, (f) => `<div class="check"><span class="m pend">•</span>${esc(f)}</div>`) : ""}`;
}

/* ---- router ---- */
function fail(msg) { view.innerHTML = `<h1>Not found</h1><p class="err">${esc(msg)}</p><p><a href="#/">← Dashboard</a></p>`; }

async function route() {
  const h = location.hash.replace(/^#\/?/, "");
  const [seg, id] = h.split("/");
  document.querySelectorAll(".nav").forEach((n) =>
    n.classList.toggle("on", n.dataset.nav === (["task", "feature", "review"].includes(seg) ? "" : seg)));
  view.innerHTML = `<p class="muted">Loading…</p>`;
  try {
    if (seg === "task") return await taskFocus(id);
    if (seg === "feature") return await feature(id);
    if (seg === "review") return await review(id);
    if (seg === "activity") return await activity();
    if (seg === "health") return await health();
    return await dashboard();
  } catch (e) { view.innerHTML = `<p class="err">${esc(e.message || e)}</p>`; }
}
window.addEventListener("hashchange", route);
route();
