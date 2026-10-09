"use strict";
/* Fresher Data Jobs dashboard. Plain JS, no framework. All data comes from /api/*; nothing is invented here.
   Safety rules enforced in the UI: only Verified jobs get the green "Apply on company site" button; every
   external link is http(s)-only and opens with noopener; text from the sheet is always inserted as text. */

const $ = s => document.querySelector(s);
const store = {
  get(k, s = localStorage) { try { return s.getItem(k) } catch { return null } },
  set(k, v, s = localStorage) { try { v == null ? s.removeItem(k) : s.setItem(k, v) } catch {} },
};
const readJSON = (k, d) => { try { return JSON.parse(store.get(k)) ?? d } catch { return d } };
const S = { data: null, view: "dashboard", page: 25, analytics: null, range: "30", profiles: null, tailorJob: null, busy: false,
  f: { q: "", role: "All", loc: "", mode: "All", exp: "All", posted: "All", vstatus: "All", minMatch: 0, company: "", prio: "All",
       sort: "priority", showHidden: false } };
const VIEWS = [["dashboard", "Dashboard"], ["find", "Find Jobs"], ["saved", "Saved Jobs"], ["apps", "Applications"],
  ["follow", "Follow-ups"], ["resume", "Resume Lab"], ["analytics", "Analytics"], ["settings", "Settings"], ["archive", "Archive"]];
const IN_PROGRESS = ["Applied", "Online Assessment", "Recruiter Screening", "Technical Interview", "HR Interview"];
const TERMINAL = ["Offer", "Rejected", "Withdrawn", "Not Interested"];
const CHECK_NAMES = { employer: "Employer identified", official_site: "Official website", careers_page: "Careers page",
  ats_link: "Employer ↔ ATS link", vacancy_match: "Exact vacancy", requisition_id: "Requisition ID", open_status: "Accepting applications",
  apply_url: "Direct apply URL", experience: "Fresher / 0–1 yr", location: "Location / work mode" };

// ---------- DOM helpers ----------
function el(tag, attrs = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "class") n.className = v; else if (k.startsWith("on")) n[k] = v; else if (k === "text") n.textContent = v; else n.setAttribute(k, v === true ? "" : v);
  }
  for (const k of kids.flat(Infinity)) if (k != null && k !== false && k !== "") n.append(k.nodeType ? k : document.createTextNode(String(k)));
  return n;
}
const safeUrl = u => { try { const x = new URL(u); return /^https?:$/.test(x.protocol) ? x.href : null } catch { return null } };
const ext = (href, text, cls = "btn small", title) => { const u = safeUrl(href); return u ? el("a", { class: cls, href: u, target: "_blank", rel: "noopener noreferrer", title }, text) : null };
const today = () => new Date(Date.now() + 5.5 * 3600e3).toISOString().slice(0, 10);   // IST date
const addDays = (d, n) => new Date(new Date(d + "T00:00:00Z").getTime() + n * 864e5).toISOString().slice(0, 10);
const daysAgo = s => { const d = Date.parse((s || "").slice(0, 10)); return isNaN(d) ? null : Math.floor((Date.parse(today()) - d) / 864e5) };
const isWfh = j => /work from home|\bremote\b|\bwfh\b|anywhere/i.test(`${j.employment} ${j.location}`);
const stageOf = j => (j.application && j.application.Stage) || "Discovered";
const roleOf = t => /data/i.test(t) && /engineer/i.test(t) ? "Data Engineer" : /data/i.test(t) && /analyst/i.test(t) ? "Data Analyst" : "Other";
const uid = () => Math.random().toString(36).slice(2, 12);

let toastTimer;
function toast(msg, ms = 4500, action) {
  const t = $("#toast");
  t.replaceChildren(el("span", {}, msg), action ? el("button", { onclick() { t.hidden = true; action.fn() } }, action.label) : "");
  t.hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => t.hidden = true, ms);
}

// ---------- API ----------
async function api(path, opts = {}) {
  const token = store.get("session", sessionStorage);
  const r = await fetch(path, { ...opts, headers: { "Content-Type": "application/json", ...(token ? { Authorization: "Bearer " + token } : {}), ...(opts.headers || {}) } });
  if (r.status === 401) { store.set("session", null, sessionStorage); showGate("Please sign in again."); throw new Error("unauthorized") }
  const data = await r.json().catch(() => ({ error: `Unexpected response (HTTP ${r.status})` }));
  if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
  return data;
}
const post = (path, body) => api(path, { method: "POST", body: JSON.stringify(body) });
const fail = e => { if (e.message !== "unauthorized") toast(e.message, 7000) };

// ---------- sign in / register ----------
const AUTH = { multi: false, registration: false, registering: false };
function showGate(msg = "") {
  $("#app").hidden = true; $("#gate").hidden = false; $("#gateErr").textContent = msg;
  fetch("/api/health").then(r => r.json()).then(h => {
    AUTH.multi = h.auth === "users"; AUTH.registration = !!h.registration; drawGate();
  }).catch(drawGate);
}
function drawGate() {
  $("#emailField").hidden = !AUTH.multi; $("#email").required = AUTH.multi;
  $("#regFields").hidden = !AUTH.registering; $("#regToggle").hidden = !(AUTH.multi && AUTH.registration);
  $("#regLink").textContent = AUTH.registering ? "Already have an account? Sign in" : "Have an invite code? Create an account";
  $("#gateBtn").textContent = AUTH.registering ? "Create account" : "Sign in";
  $("#gateSub").textContent = AUTH.multi ? (AUTH.registering ? "Create your account (password: 10+ characters)." : "Sign in to your account. Sessions last 12 hours.")
    : "Sign in with the dashboard password. Your session lasts 12 hours.";
  $("#pw").autocomplete = AUTH.registering ? "new-password" : "current-password";
  (AUTH.multi ? $("#email") : $("#pw")).focus();
}
$("#regLink").onclick = () => { AUTH.registering = !AUTH.registering; drawGate() };
$("#gateForm").onsubmit = async e => {
  e.preventDefault();
  const btn = $("#gateBtn"); btn.disabled = true; $("#gateErr").textContent = "";
  const body = AUTH.registering ? { email: $("#email").value, password: $("#pw").value, name: $("#rname").value, invite_code: $("#invite").value }
    : AUTH.multi ? { email: $("#email").value, password: $("#pw").value } : { password: $("#pw").value };
  try {
    const r = await fetch(AUTH.registering ? "/api/register" : "/api/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.error || "Sign-in failed");
    store.set("session", d.token, sessionStorage); $("#pw").value = ""; AUTH.registering = false;
    $("#gate").hidden = true; $("#app").hidden = false; load();
  } catch (err) { $("#gateErr").textContent = err.message } finally { btn.disabled = false }
};

// ---------- theme / nav ----------
const savedTheme = store.get("theme"); if (savedTheme) document.documentElement.dataset.theme = savedTheme;
function toggleTheme() {
  const dark = document.documentElement.dataset.theme ? document.documentElement.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  document.documentElement.dataset.theme = dark ? "light" : "dark"; store.set("theme", document.documentElement.dataset.theme);
}
function go(view) { S.view = view; S.page = 25; history.replaceState(null, "", "#" + view); render(); $("#main").focus() }
function renderNav() {
  const jobs = S.data ? S.data.jobs : [];
  const n = { find: jobs.filter(j => stageOf(j) === "Discovered" && j.priority !== "Hidden").length,
    saved: jobs.filter(j => ["Saved", "Ready to Apply"].includes(stageOf(j))).length,
    apps: jobs.filter(j => IN_PROGRESS.includes(stageOf(j))).length,
    follow: S.data ? S.data.followups.overdue.length + S.data.followups.today.length : 0,
    archive: S.data ? S.data.archive.length : 0 };
  const who = S.data && S.data.user && S.data.user.multi_user ? el("div", { class: "sub", style: "padding:0 10px 12px;margin-top:-10px" }, S.data.user.name || S.data.user.email) : "";
  $("#nav").replaceChildren(el("div", { class: "brand" }, "Fresher Data Jobs"), who,
    ...VIEWS.map(([k, label]) => el("button", { "aria-current": S.view === k ? "page" : null, onclick() { go(k) } }, label, n[k] ? el("span", { class: "count" }, n[k]) : "")),
    el("div", { class: "foot" }, el("button", { class: "btn small", onclick: load }, "Refresh"), el("button", { class: "btn small", onclick: toggleTheme }, "Theme"),
      el("button", { class: "btn small", onclick() { store.set("session", null, sessionStorage); showGate() } }, "Sign out")));
}

// ---------- data ----------
async function load() {
  $("#main").replaceChildren(el("div", { class: "empty" }, el("span", { class: "spinner" }), " Loading your jobs…"));
  try { S.data = await api("/api/jobs"); render() }
  catch (e) { if (e.message !== "unauthorized") $("#main").replaceChildren(el("div", { class: "notice bad" }, e.message)) }
}
const job = id => S.data.jobs.find(j => j.id === id);

// ---------- application actions ----------
async function setApp(j, fields, label) {
  const prev = { ...j.application };
  Object.assign(j.application, fields); render();
  try {
    await post("/api/application", { action: "set", job_id: j.id, fields, action_id: uid() });
    toast(label || "Saved", 6000, { label: "Undo", fn: () => undoApp(j) });
  } catch (e) { j.application = prev; render(); fail(e) }
}
async function undoApp(j) {
  try { await post("/api/application", { action: "undo", job_id: j.id, action_id: uid() }); toast("Undone"); await load() } catch (e) { fail(e) }
}

// ---------- job card ----------
function verificationBlock(j) {
  const v = j.verification || {}, checks = v.checks || {};
  const items = Object.keys(CHECK_NAMES).filter(k => checks[k]).map(k => {
    const c = checks[k];
    return el("li", {}, el("span", { class: "ic " + c.status, "aria-label": c.status }, c.status === "pass" ? "✓" : c.status === "fail" ? "✗" : "?"),
      el("span", {}, CHECK_NAMES[k]), el("span", { class: "d muted" }, c.detail, " ", c.url ? ext(c.url, "evidence ↗", "btn link") : ""));
  });
  return el("details", {}, el("summary", {}, "Verification details"),
    items.length ? el("ul", { class: "checks" }, items) : el("p", { class: "muted" }, "No verification breakdown stored for this job yet (found by an earlier version). Reason: ", v.reason || j.notes || "—"),
    el("p", { class: "muted" }, v.req_id ? `Requisition ID: ${v.req_id} · ` : "", v.last_open_check ? `Last confirmed open: ${v.last_open_check}` : "Not yet confirmed open",
      v.retry ? " · queued for an automatic re-check" : ""),
    v.history && v.history.length > 1 ? el("details", {}, el("summary", {}, "Verification history"),
      el("table", {}, el("tr", {}, el("th", {}, "When"), el("th", {}, "Result"), el("th", {}, "Reason")),
        v.history.slice().reverse().map(h => el("tr", {}, el("td", {}, h.time), el("td", {}, h.status), el("td", {}, h.reason))))) : "");
}
function matchBlock(j) {
  const m = j.match;
  if (!m) return "";
  const comp = Object.entries(m.components).filter(([, v]) => v != null);
  return el("div", { class: "skills" },
    m.matched.length ? el("div", {}, el("span", { class: "lbl" }, "You have:"), el("span", { class: "tags" }, m.matched.map(s => el("span", { class: "tag ok" }, s)))) : "",
    m.missing_required.length ? el("div", {}, el("span", { class: "lbl" }, "Missing (required):"), el("span", { class: "tags" }, m.missing_required.map(s => el("span", { class: "tag bad" }, s)))) : "",
    m.missing_preferred.length ? el("div", {}, el("span", { class: "lbl" }, "Missing (nice to have):"), el("span", { class: "tags" }, m.missing_preferred.map(s => el("span", { class: "tag warn" }, s)))) : "",
    el("div", {}, el("span", { class: "lbl" }, "Next step:"), m.next_action),
    el("details", {}, el("summary", {}, "Why this match score"),
      el("div", { class: "bars", style: "margin-top:8px" }, comp.map(([k, v]) => el("div", { class: "bar" },
        el("span", {}, `${k.replace("_", " ")} (×${m.weights[k]})`), el("span", { class: "track" }, el("span", { class: "fill", style: `width:${Math.round(v * 100)}%` })),
        el("span", { class: "v" }, Math.round(v * 100) + "%")))),
      m.mandatory_failures.length ? el("p", { class: "notice bad", style: "margin-top:8px" }, "Not eligible: " + m.mandatory_failures.join("; ")) : "",
      m.reasons.length ? el("p", { class: "muted" }, m.reasons.join(" · ")) : ""));
}
function contactsBlock(j) {
  const c = j.contacts || [];
  const group = (type, title) => {
    const xs = c.filter(x => x.type === type);
    return xs.length ? el("div", {}, el("span", { class: "lbl" }, title), el("span", { class: "tags" }, xs.map(x => x.value.includes("@")
      ? el("a", { class: "tag " + (type === "published" ? "ok" : "warn"), href: "mailto:" + encodeURIComponent(x.value).replace("%40", "@"), title: "Source: " + (x.evidence || "") }, "✉ " + x.value)
      : ext(x.value, `${x.name || "Profile"}${x.role ? " — " + x.role : ""} ↗`, "tag warn", "From " + (x.evidence || "public search results") + "; unverified")))) : "";
  };
  return el("details", {}, el("summary", {}, `Recruiter / HR contacts (${c.length})`),
    el("div", { class: "skills" }, group("published", "Published by the employer:"), group("listing", "In a job-board listing (unverified):"),
      group("profile", "Public profiles (unverified leads):"),
      el("div", {}, ext(j.linkedin, "Search HR on LinkedIn ↗", "btn small"), el("span", { class: "muted" }, " Opens LinkedIn's own search; nothing is fetched or sent automatically."))));
}
function jobCard(j) {
  const st = stageOf(j), m = j.match, verified = j.apply_kind === "verified";
  const posted = j.posted ? (daysAgo(j.posted) === 0 ? "today" : `${daysAgo(j.posted)}d ago`) : "date unknown";
  const applyBtn = verified
    ? ext(j.apply_link, "✓ Apply on company site ↗", "btn small verified", "Verified: employer, exact vacancy and open status confirmed")
    : ext(j.apply_link, { company: "Open company listing (not verified) ↗", portal: "Open job-board listing (not verified) ↗", careers: "Open careers page (not verified) ↗" }[j.apply_kind] || "Open listing ↗",
      "btn small unverified", "Not verified: check the role on the employer's own site before applying");
  return el("article", { class: "card" + (TERMINAL.includes(st) || j.priority === "Hidden" ? " dim" : "") },
    el("div", { class: "score " + j.priority, title: j.why.join(", ") }, m ? (m.eligible ? "Match" : "Not eligible") : j.priority, el("small", {}, m ? m.overall + "%" : j.priority === "Hidden" ? "–" : j.score)),
    el("div", {},
      el("h3", { class: "title" }, j.title, " ", el("span", { class: "company" }, "· " + j.company), j.preferred ? el("span", { class: "tag acc", style: "margin-left:6px" }, "preferred") : ""),
      el("div", { class: "tags meta" },
        el("span", { class: "tag " + (j.status === "Verified" ? "ok" : j.status === "Needs Review" ? "warn" : "bad") }, j.status || "Unchecked"),
        isWfh(j) ? el("span", { class: "tag ok" }, "Work from home") : "", j.location ? el("span", { class: "tag acc" }, j.location) : "",
        j.employment ? el("span", { class: "tag" }, j.employment) : "", el("span", { class: "tag" }, "Exp: " + (j.experience || "not stated")),
        el("span", { class: "tag" }, "Posted " + posted), el("span", { class: "tag" }, (j.source || "").split(" + ").pop() || "source unknown"),
        st !== "Discovered" ? el("span", { class: "tag acc" }, st) : "", j.closes ? el("span", { class: "tag warn" }, "Closes " + j.closes) : "",
        el("span", { class: "tag" }, `Priority: ${j.priority}`)),
      matchBlock(j),
      el("div", { class: "actions" }, applyBtn,
        st === "Discovered" ? el("button", { class: "btn small", onclick() { setApp(j, { Stage: "Saved" }, "Saved") } }, "☆ Save") : "",
        el("label", { class: "f", style: "flex-direction:row;align-items:center" }, el("span", { class: "sr" }, ""),
          el("select", { "aria-label": "Application status", onchange(e) { setApp(j, { Stage: e.target.value }, "Status: " + e.target.value) } },
            S.data.stages.map(s => el("option", { value: s, selected: s === st || null }, s)))),
        st !== "Not Interested" ? el("button", { class: "btn small danger", onclick() { setApp(j, { Stage: "Not Interested" }, "Marked not interested") } }, "Not interested") : "",
        el("button", { class: "btn small", onclick() { openApp(j) } }, "Track / notes"),
        el("button", { class: "btn small", onclick() { S.tailorJob = j.id; go("resume") } }, "Tailor resume"),
        j.careers && j.careers !== j.apply_link ? ext(j.careers, "Careers page ↗", "btn small link") : ""),
      verificationBlock(j), contactsBlock(j)));
}

// ---------- application modal ----------
function openApp(j) {
  const a = j.application, dlg = $("#dlg");
  const field = (k, type = "date") => el("label", { class: "f" }, k, type === "textarea"
    ? el("textarea", { name: k, rows: 3 }, a[k] || "") : el("input", { type, name: k, value: a[k] || "" }));
  const form = el("form", { method: "dialog", id: "appForm" },
    el("div", { class: "grid", style: "grid-template-columns:repeat(auto-fit,minmax(180px,1fr))" },
      el("label", { class: "f" }, "Stage", el("select", { name: "Stage" }, S.data.stages.map(s => el("option", { value: s, selected: s === stageOf(j) || null }, s)))),
      field("Applied Date"), field("Deadline"), field("Follow-up Date"), field("Assessment Date"), field("Interview Date"),
      field("Recruiter", "text"), field("Resume Version", "text")),
    el("div", { class: "grid", style: "margin-top:10px" }, field("Offer Details", "textarea"), field("Notes", "textarea")),
    el("div", { id: "histBox", class: "muted", style: "margin-top:10px" }, "Loading history…"));
  dlg.replaceChildren(el("div", { class: "dh" }, el("h2", { style: "margin:0" }, `${j.title} · ${j.company}`), el("button", { class: "btn small", onclick() { dlg.close() } }, "Close")),
    el("div", { class: "db" }, form),
    el("div", { class: "df" }, el("button", { class: "btn", onclick() { dlg.close(); undoApp(j) } }, "Undo last change"),
      el("button", { class: "btn primary", async onclick() {
        const fd = new FormData(form), fields = {};
        for (const [k, v] of fd.entries()) if ((a[k] || "") !== v && !(k === "Stage" && v === stageOf(j))) fields[k] = v;
        if (Object.keys(fields).length) await setApp(j, fields, "Application updated");
        dlg.close();
      } }, "Save")));
  dlg.showModal();
  post("/api/application", { action: "history", job_id: j.id }).then(r => {
    $("#histBox").replaceChildren(el("h3", {}, "Status history"), r.history.length
      ? el("table", {}, el("tr", {}, el("th", {}, "When"), el("th", {}, "Field"), el("th", {}, "From"), el("th", {}, "To"), el("th", {}, "By")),
        r.history.slice().reverse().map(h => el("tr", {}, el("td", {}, h.Timestamp), el("td", {}, h.Field), el("td", {}, h.Old), el("td", {}, h.New), el("td", {}, h.Source))))
      : "No changes yet.");
  }).catch(() => $("#histBox").textContent = "History unavailable.");
}

// ---------- filters & lists ----------
function filtered(base) {
  const f = S.f, minMatch = Number(f.minMatch) || 0;
  let xs = base.filter(j =>
    (f.showHidden || j.priority !== "Hidden") &&
    (f.role === "All" || roleOf(j.title) === f.role) &&
    (!f.loc || f.loc.split(",").some(t => t.trim() && (`${j.location} ${j.employment}`).toLowerCase().includes(t.trim().toLowerCase()))) &&
    (f.mode === "All" || (f.mode === "Work from home") === isWfh(j)) &&
    (f.exp === "All" || (f.exp === "Fresher-friendly" ? /fresh|entry|0|month|graduate/i.test(j.experience) && !/not stated/i.test(j.experience) : /not stated/i.test(j.experience || "not stated"))) &&
    (f.posted === "All" || (daysAgo(j.posted) != null && daysAgo(j.posted) <= Number(f.posted))) &&
    (f.vstatus === "All" || j.status === f.vstatus) &&
    (!minMatch || (j.match && j.match.overall >= minMatch)) &&
    (!f.company || j.company.toLowerCase().includes(f.company.toLowerCase())) &&
    (f.prio === "All" || j.priority === f.prio) &&
    (!f.q || `${j.title} ${j.company} ${j.notes}`.toLowerCase().includes(f.q.toLowerCase())));
  const vrank = { Verified: 0, "Needs Review": 1, Closed: 2, Rejected: 3 };
  const sorters = { priority: (a, b) => b.score - a.score, newest: (a, b) => (b.posted || b.found || "").localeCompare(a.posted || a.found || ""),
    match: (a, b) => (b.match ? b.match.overall : -1) - (a.match ? a.match.overall : -1), verification: (a, b) => (vrank[a.status] ?? 9) - (vrank[b.status] ?? 9) || b.score - a.score };
  return xs.sort(sorters[f.sort] || sorters.priority);
}
function filterBar() {
  const f = S.f;
  const sel = (key, label, opts) => el("label", { class: "f" }, label, el("select", { onchange(e) { f[key] = e.target.value; S.page = 25; renderList() } },
    opts.map(o => Array.isArray(o) ? el("option", { value: o[0], selected: String(f[key]) === String(o[0]) || null }, o[1]) : el("option", { value: o, selected: f[key] === o || null }, o))));
  const txt = (key, label, ph) => el("label", { class: "f" }, label, el("input", { type: "search", value: f[key], placeholder: ph, oninput(e) { f[key] = e.target.value; S.page = 25; renderList() } }));
  return el("div", { class: "filters", role: "search" },
    txt("q", "Search", "title, company, notes"), sel("role", "Role", ["All", "Data Analyst", "Data Engineer", "Other"]),
    txt("loc", "Location", "e.g. Pune, Mumbai"), sel("mode", "Work mode", ["All", "Work from home", "Office / hybrid"]),
    sel("exp", "Experience", ["All", "Fresher-friendly", "Not stated"]), sel("posted", "Posted", [["All", "Any time"], ["1", "24 hours"], ["3", "3 days"], ["7", "7 days"], ["14", "14 days"], ["30", "30 days"]]),
    sel("vstatus", "Verification", ["All", "Verified", "Needs Review", "Closed", "Rejected"]),
    el("label", { class: "f" }, `Match ≥ ${f.minMatch}%`, el("input", { type: "range", min: 0, max: 100, step: 10, value: f.minMatch, oninput(e) { f.minMatch = e.target.value; e.target.previousSibling.textContent = `Match ≥ ${f.minMatch}%`; S.page = 25; renderList() } })),
    txt("company", "Company", "name"), sel("prio", "Priority", ["All", "High", "Medium", "Low"]),
    sel("sort", "Sort by", [["priority", "Priority"], ["newest", "Newest"], ["match", "Highest match"], ["verification", "Verification state"]]),
    el("label", { class: "chk", style: "align-self:end" }, el("input", { type: "checkbox", checked: f.showHidden || null, onchange(e) { f.showHidden = e.target.checked; renderList() } }), "Show rejected / closed"));
}
let listBase = () => [];
function renderList() {
  const xs = filtered(listBase()), box = $("#list");
  if (!box) return;
  if (!xs.length) return box.replaceChildren(el("div", { class: "empty" }, S.data.jobs.length ? "No jobs match these filters." : "No jobs yet. Run a search above."));
  box.replaceChildren(el("p", { class: "sub" }, `${xs.length} job${xs.length === 1 ? "" : "s"}`), ...xs.slice(0, S.page).map(jobCard),
    xs.length > S.page ? el("button", { class: "btn", onclick() { S.page += 25; renderList() } }, `Show more (${xs.length - S.page} left)`) : "");
}

// ---------- views ----------
function viewDashboard() {
  const d = S.data, jobs = d.jobs, lastRun = d.runs[0];
  const live = jobs.filter(j => !TERMINAL.includes(stageOf(j)) && j.priority !== "Hidden");
  const newVerified = live.filter(j => j.status === "Verified" && lastRun && j.found >= (lastRun.Started || "").slice(0, 16));
  const top = live.filter(j => j.match && j.match.eligible).sort((a, b) => b.match.overall - a.match.overall).slice(0, 5);
  const inProg = jobs.filter(j => IN_PROGRESS.includes(stageOf(j)));
  const fu = d.followups, interviews = [...fu.today, ...fu.upcoming].filter(x => ["interview", "assessment"].includes(x.kind));
  const b = d.budget || {};
  return [el("div", { class: "head" }, el("div", {}, el("h1", {}, "Dashboard"), el("div", { class: "sub" }, d.updated ? `Last checked ${d.updated} IST` : "No searches yet"))),
    el("div", { class: "tiles" },
      tile(newVerified.length, "New verified jobs", () => { S.f.vstatus = "Verified"; go("find") }),
      tile(live.filter(j => j.status === "Needs Review").length, "Need review", () => { S.f.vstatus = "Needs Review"; go("find") }),
      tile(inProg.length, "Applications in progress", () => go("apps")),
      tile(fu.overdue.length + fu.today.length, "Follow-ups due", () => go("follow")),
      tile(interviews.length, "Interviews & assessments (7d)", () => go("follow")),
      tile(b.confirmed_left ?? "?", b.confirmed_left != null ? "SerpApi searches left (confirmed)" : "SerpApi budget unknown", () => go("settings"))),
    el("div", { class: "two" },
      el("section", { class: "panel" }, el("h2", {}, "Top resume matches"), d.profile ? (top.length ? el("div", { class: "list" }, top.map(miniJob)) : el("p", { class: "muted" }, "No eligible matches yet."))
        : el("p", { class: "muted" }, "Add a resume in ", el("button", { class: "btn link", onclick() { go("resume") } }, "Resume Lab"), " to see match scores.")),
      el("section", { class: "panel" }, el("h2", {}, "Follow-ups"), followList([...fu.overdue, ...fu.today, ...fu.upcoming].slice(0, 6)),
        el("h2", { style: "margin-top:14px" }, "Latest search"), lastRun ? runSummary(lastRun) : el("p", { class: "muted" }, "No search recorded yet."))),
    el("section", { class: "panel" }, el("h2", {}, "Needs review (highest priority)"),
      el("div", { class: "list" }, live.filter(j => j.status === "Needs Review").slice(0, 3).map(jobCard)))];
}
const tile = (n, label, fn) => el("button", { class: "tile", onclick: fn }, el("b", {}, n), el("span", {}, label));
const miniJob = j => el("div", { class: "mini" }, el("b", {}, `${j.match ? j.match.overall + "% · " : ""}${j.title}`), `${j.company} · ${j.location || ""}`,
  el("div", { class: "row", style: "margin-top:6px" }, j.apply_kind === "verified" ? ext(j.apply_link, "✓ Apply ↗", "btn small verified") : el("span", { class: "tag warn" }, "not verified"),
    el("button", { class: "btn small", onclick() { S.f.q = j.title; go("find") } }, "Details")));
const runSummary = r => el("p", { class: "muted" }, `${r.Started} (${r.Trigger || "?"}) · ${r["New Rows"] || 0} new · ${r.Verified || 0} verified · ${r["Needs Review"] || 0} to review · ${r["SerpApi Calls"] || 0} searches used · ${r.Status || ""}`);

function viewFind() {
  const s = S.data.settings, prof = S.data.profile;
  const locs = readJSON("searchLocs", s.locations);
  const roles = readJSON("searchRoles", s.roles || ["Data Analyst", "Data Engineer"]);
  const roleChips = el("div", { class: "chips", "aria-label": "Job roles" });
  const drawRoles = () => roleChips.replaceChildren(...roles.map((r, i) => el("span", { class: "chip" }, r,
      el("button", { "aria-label": "Remove " + r, onclick() { roles.splice(i, 1); store.set("searchRoles", JSON.stringify(roles)); drawRoles() } }, "×"))),
    el("input", { "aria-label": "Add job role", placeholder: "Add job role + Enter (e.g. Business Analyst)", onkeydown(e) {
      const v = e.target.value.trim();
      if (e.key === "Enter" && v) { e.preventDefault(); if (!/^[A-Za-z][A-Za-z0-9 +#.\/&()-]{1,59}$/.test(v)) return toast("Use a plain job title");
        if (roles.length < 6 && !roles.some(x => x.toLowerCase() === v.toLowerCase())) roles.push(v);
        store.set("searchRoles", JSON.stringify(roles)); drawRoles(); roleChips.querySelector("input").focus() } } }));
  drawRoles();
  let mode = store.get("searchMode") || s.mode, age = store.get("searchAge") || String(s.max_age_days);
  const chips = el("div", { class: "chips" });
  const drawChips = () => chips.replaceChildren(...locs.map((l, i) => el("span", { class: "chip" }, l, el("button", { "aria-label": "Remove " + l, onclick() { locs.splice(i, 1); store.set("searchLocs", JSON.stringify(locs)); drawChips() } }, "×"))),
    el("input", { "aria-label": "Add location", placeholder: "Add location + Enter", onkeydown(e) {
      const v = e.target.value.trim();
      if (e.key === "Enter" && v) { e.preventDefault(); if (!/^[A-Za-z][A-Za-z .-]{0,39}$/.test(v)) return toast("Use a plain place name"); if (locs.length < 5 && !locs.includes(v)) locs.push(v); store.set("searchLocs", JSON.stringify(locs)); drawChips(); chips.querySelector("input").focus() } } }));
  drawChips();
  const seg = (opts, cur, set) => { const box = el("div", { class: "seg", role: "group" }); const draw = () => box.replaceChildren(...opts.map(([v, l]) => el("button", { "aria-pressed": String(cur() === v), onclick() { set(v); draw() } }, l))); draw(); return box };
  const useResume = el("input", { type: "checkbox", checked: (prof && prof.use_in_search) || null, disabled: !prof || null });
  const out = el("div", { "aria-live": "polite" });
  const body = () => ({ roles, locations: locs, mode, max_age_days: Number(age), use_resume: useResume.checked });
  const run = async preview => {
    if (!locs.length && mode !== "wfh") return toast("Add a location, or choose Work from home");
    if (!roles.length && !useResume.checked) return toast("Add at least one job role");
    S.busy = true; out.replaceChildren(el("p", { class: "muted" }, el("span", { class: "spinner" }), preview ? " Planning…" : " Searching… (up to 4 minutes)"));
    try {
      const r = await post("/api/run", { ...body(), preview });
      out.replaceChildren(el("pre", { class: "mono", style: "white-space:pre-wrap" }, r.summary.trim()));
      if (!preview) { toast("Search finished"); await load() }
    } catch (e) { out.replaceChildren(el("p", { class: "notice bad" }, e.message)) } finally { S.busy = false }
  };
  listBase = () => S.data.jobs.filter(j => stageOf(j) === "Discovered");
  return [el("div", { class: "head" }, el("div", {}, el("h1", {}, "Find Jobs"), el("div", { class: "sub" }, "Searches cost SerpApi credits; use Preview first to see exactly what would run."))),
    el("section", { class: "panel" }, el("h2", {}, "Search"),
      el("div", { class: "grid", style: "grid-template-columns:1fr" },
        el("label", { class: "f" }, "Job roles to search for", roleChips),
        el("label", { class: "f" }, "Locations", chips),
        el("div", { class: "row" }, seg([["any", "Any mode"], ["wfh", "Work from home"], ["onsite", "Office / hybrid"]], () => mode, v => { mode = v; store.set("searchMode", v) }),
          seg([["1", "24h"], ["3", "3d"], ["7", "7d"], ["14", "14d"], ["30", "30d"]], () => age, v => { age = v; store.set("searchAge", v) }),
          el("label", { class: "chk", title: "Searches the roles and skills from your active resume profile instead of the roles above" }, useResume,
            prof ? `Use my resume's roles instead (${prof.name})` : "No resume profile yet"),
          el("button", { class: "btn", onclick() { run(true) } }, "Preview (free)"),
          el("button", { class: "btn primary", onclick() { if (confirm("Run a live search now? It uses SerpApi credits.")) run(false) } }, "Search for jobs"))),
      out,
      S.data.runs.length ? el("details", {}, el("summary", {}, "Search history"), el("table", {}, el("tr", {}, ["Started", "Trigger", "Profile", "Searches", "New", "Verified", "Status"].map(h => el("th", {}, h))),
        S.data.runs.map(r => el("tr", {}, el("td", {}, r.Started), el("td", {}, r.Trigger), el("td", {}, r.Profile), el("td", {}, r["SerpApi Calls"]), el("td", {}, r["New Rows"]), el("td", {}, r.Verified), el("td", {}, r.Status))))) : ""),
    filterBar(), el("div", { id: "list", class: "list" })];
}
function viewSaved() {
  listBase = () => S.data.jobs.filter(j => ["Saved", "Ready to Apply"].includes(stageOf(j)));
  return [el("div", { class: "head" }, el("div", {}, el("h1", {}, "Saved Jobs"), el("div", { class: "sub" }, "Saved and ready-to-apply roles."))), filterBar(), el("div", { id: "list", class: "list" })];
}
function appMini(j) {
  const a = j.application;
  const info = [a["Applied Date"] && "Applied " + a["Applied Date"], a["Interview Date"] && "Interview " + a["Interview Date"],
    a["Resume Version"] && "Resume: " + a["Resume Version"]].filter(Boolean).join(" · ");
  const link = j.apply_kind === "verified" ? ext(j.apply_link, "Posting ↗", "btn small link") : ext(j.apply_link, "Listing ↗ (unverified)", "btn small link");
  return el("div", { class: "mini" }, el("b", {}, j.title), j.company, el("div", { class: "muted" }, info),
    el("div", { class: "row", style: "margin-top:6px" }, el("button", { class: "btn small", onclick() { openApp(j) } }, "Open"), link));
}
function viewApps() {
  const cols = [...IN_PROGRESS, "Offer", "Rejected", "Withdrawn", "Not Interested"];
  const by = s => S.data.jobs.filter(j => stageOf(j) === s);
  const column = s => el("section", { class: "col", "aria-label": s }, el("h3", {}, s, el("span", { class: "muted" }, by(s).length)), by(s).map(appMini));
  return [el("div", { class: "head" }, el("div", {}, el("h1", {}, "Applications"),
      el("div", { class: "sub" }, "Change a stage, add dates and notes; every change is logged and can be undone."))),
    el("div", { class: "kanban" }, cols.map(column))];
}
function followList(items) {
  if (!items.length) return el("p", { class: "muted" }, "Nothing due.");
  const label = { "follow-up": "Follow up", assessment: "Assessment", interview: "Interview", deadline: "Your deadline", closing: "Vacancy closes" };
  return el("table", {}, items.map(x => {
    const j = job(x.job_id);
    return el("tr", {}, el("td", { class: "mono" }, x.due), el("td", {}, el("span", { class: "tag " + (x.due < today() ? "bad" : x.due === today() ? "warn" : "") }, label[x.kind] || x.kind)),
      el("td", {}, `${x.title} · ${x.company}`), el("td", {}, j && x.kind === "follow-up" ? el("span", { class: "row" },
        el("button", { class: "btn small", onclick() { setApp(j, { "Follow-up Done": today() }, "Follow-up marked done") } }, "Done"),
        el("button", { class: "btn small", onclick() { setApp(j, { "Follow-up Date": addDays(today(), 3) }, "Snoozed 3 days") } }, "Snooze 3d")) : j ? el("button", { class: "btn small", onclick() { openApp(j) } }, "Open") : ""));
  }));
}
function viewFollow() {
  const fu = S.data.followups;
  return [el("div", { class: "head" }, el("div", {}, el("h1", {}, "Follow-ups"), el("div", { class: "sub" }, `Default follow-up ${S.data.settings.follow_up_days} days after applying (change in Settings). Nothing is ever sent for you.`))),
    el("section", { class: "panel" }, el("h2", {}, `Overdue (${fu.overdue.length})`), followList(fu.overdue)),
    el("section", { class: "panel" }, el("h2", {}, `Today (${fu.today.length})`), followList(fu.today)),
    el("section", { class: "panel" }, el("h2", {}, `Next 7 days (${fu.upcoming.length})`), followList(fu.upcoming))];
}

// ---------- Resume Lab ----------
async function fileToBase64(file) {
  if (!/\.(pdf|docx)$/i.test(file.name)) throw new Error("Upload a PDF or DOCX file");
  if (file.size > 3e6) throw new Error("File is larger than 3 MB");
  const bytes = new Uint8Array(await file.arrayBuffer());
  let bin = ""; for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(bin);
}
const resumeKey = id => "resumeText:" + id;
async function loadProfiles() { S.profiles = await api("/api/resume"); return S.profiles }
async function saveProfile(body, msg) { try { S.profiles = await post("/api/resume", body); toast(msg || "Saved"); load() } catch (e) { fail(e) } }
function listEditor(p, key, label) {
  const vals = [...(p[key] || [])];
  const box = el("div", { class: "chips" });
  const draw = () => box.replaceChildren(...vals.map((v, i) => el("span", { class: "chip" }, v, el("button", { "aria-label": "Remove " + v, onclick() { vals.splice(i, 1); saveProfile({ action: "update", id: p.id, [key]: vals }) } }, "×"))),
    el("input", { "aria-label": "Add to " + label, placeholder: "Add + Enter", onkeydown(e) { const v = e.target.value.trim(); if (e.key === "Enter" && v) { e.preventDefault(); vals.push(v); saveProfile({ action: "update", id: p.id, [key]: vals }) } } }));
  draw();
  return el("div", {}, el("h3", {}, label), box);
}
function viewResume() {
  const root = el("div", {}, el("div", { class: "head" }, el("div", {}, el("h1", {}, "Resume Lab"),
    el("div", { class: "sub" }, "Upload a PDF or DOCX (max 3 MB). It is read in memory on the server, the text is sent to the AI (Groq) to build an editable profile, and the file is discarded. Only the profile is saved; a copy of the text stays in this browser for tailoring."))),
    el("div", { class: "empty" }, el("span", { class: "spinner" }), " Loading profiles…"));
  loadProfiles().then(c => root.replaceChildren(root.firstChild, resumeBody(c))).catch(e => { root.lastChild.replaceWith(el("p", { class: "notice bad" }, e.message)) });
  return [root];
}
function resumeBody(c) {
  const p = c.profiles.find(x => x.id === c.active);
  const file = el("input", { type: "file", accept: ".pdf,.docx", hidden: true, async onchange(e) {
    const f = e.target.files[0]; if (!f) return;
    try {
      const name = prompt("Name for this resume profile", f.name.replace(/\.(pdf|docx)$/i, "")) || "";
      toast("Reading and analysing your resume…", 30000);
      const res = await post("/api/resume", { file: await fileToBase64(f), filename: f.name, name });
      if (res.text) store.set(resumeKey(res.active), res.text);   // kept in this browser only, for tailoring
      delete res.text; S.profiles = res; toast("Profile created. Review and correct it below."); render(); load();
    } catch (err) { fail(err) } finally { e.target.value = "" }
  } });
  const head = el("section", { class: "panel" }, el("div", { class: "row" },
    c.profiles.length && el("label", { class: "f" }, "Active profile", el("select", { onchange(e) { saveProfile({ action: "activate", id: e.target.value }, "Profile switched").then(render) } },
      c.profiles.map(x => el("option", { value: x.id, selected: x.id === c.active || null }, x.name)))),
    el("button", { class: "btn primary", onclick() { file.click() } }, "Upload resume (PDF/DOCX)"), file,
    p ? el("label", { class: "chk" }, el("input", { type: "checkbox", checked: c.use_in_search || null, onchange(e) { saveProfile({ action: "use_in_search", value: e.target.checked }) } }), "Use this profile's roles in searches") : "",
    p ? el("button", { class: "btn danger", onclick() { if (confirm(`Delete profile "${p.name}"? The resume text in this browser is removed too.`)) { store.set(resumeKey(p.id), null); saveProfile({ action: "delete", id: p.id }, "Deleted").then(render) } } }, "Delete profile") : ""));
  if (!p) return el("div", {}, head, el("div", { class: "empty" }, "No resume profile yet. Upload your resume to get started."));
  const hasText = !!store.get(resumeKey(p.id));
  const edu = el("textarea", { rows: 3, "aria-label": "Education" }, (p.education || []).join("\n"));
  const certs = el("textarea", { rows: 2, "aria-label": "Certifications" }, (p.certifications || []).join("\n"));
  const years = el("input", { type: "number", min: 0, max: 40, step: 0.5, value: p.experience_years, "aria-label": "Years of experience" });
  return el("div", {}, head,
    el("section", { class: "panel" }, el("h2", {}, "Profile — check and correct it"), el("p", { class: "muted" }, p.summary),
      el("div", { class: "two" }, listEditor(p, "roles", "Target roles"), listEditor(p, "locations", "Preferred locations"),
        listEditor(p, "programming_languages", "Programming languages"), listEditor(p, "data_tools", "Data tools"),
        listEditor(p, "databases", "Databases"), listEditor(p, "frameworks", "Frameworks / libraries / cloud"),
        listEditor(p, "skills", "Other skills"), listEditor(p, "employment_preferences", "Employment preferences")),
      el("div", { class: "two", style: "margin-top:12px" }, el("label", { class: "f" }, "Education (one per line)", edu), el("label", { class: "f" }, "Certifications (one per line)", certs)),
      el("div", { class: "row", style: "margin-top:10px" }, el("label", { class: "f" }, "Full-time experience (years)", years),
        el("button", { class: "btn", onclick() { saveProfile({ action: "update", id: p.id, education: edu.value.split("\n").filter(Boolean), certifications: certs.value.split("\n").filter(Boolean), experience_years: Number(years.value) }) } }, "Save education & experience")),
      p.projects && p.projects.length ? el("details", {}, el("summary", {}, `Projects (${p.projects.length})`), el("ul", {}, p.projects.map(x => el("li", {}, el("b", {}, x.name), " — ", x.summary, x.skills.length ? ` (${x.skills.join(", ")})` : "")))) : "",
      p.experience && p.experience.length ? el("details", {}, el("summary", {}, `Experience (${p.experience.length})`), el("ul", {}, p.experience.map(x => el("li", {}, `${x.title} · ${x.company} · ${x.duration}${x.internship ? " (internship)" : ""}`)))) : ""),
    el("section", { class: "panel" }, el("h2", {}, "Resume text in this browser"),
      el("p", { class: "muted" }, hasText ? "Stored locally for tailoring. It is never saved on the server." : "Not stored in this browser. Upload the resume again (or paste it) to enable tailoring."),
      el("div", { class: "row" }, el("button", { class: "btn", onclick() { const t = prompt("Paste your resume text"); if (t && t.trim().length > 200) { store.set(resumeKey(p.id), t); render() } } }, "Paste text"),
        hasText ? el("button", { class: "btn danger", onclick() { store.set(resumeKey(p.id), null); toast("Removed from this browser"); render() } }, "Delete stored text") : "")),
    tailorPanel(p));
}
function tailorPanel(p) {
  const candidates = S.data.jobs.filter(j => !TERMINAL.includes(stageOf(j)) && j.priority !== "Hidden");
  const pick = el("select", { "aria-label": "Job to tailor for" }, el("option", { value: "" }, "Choose a job…"),
    candidates.map(j => el("option", { value: j.id, selected: j.id === S.tailorJob || null }, `${j.title} · ${j.company}`)));
  const out = el("div", { "aria-live": "polite" });
  const versions = readJSON("resumeVersions", []);
  return el("section", { class: "panel" }, el("h2", {}, "Tailor for a job"),
    el("p", { class: "muted" }, "Suggestions only use facts from your resume. Anything new is flagged; nothing is uploaded or sent to employers."),
    el("div", { class: "row" }, pick, el("button", { class: "btn primary", async onclick() {
      const text = store.get(resumeKey(p.id)); if (!text) return toast("Add your resume text in this browser first");
      if (!pick.value) return toast("Choose a job");
      out.replaceChildren(el("p", { class: "muted" }, el("span", { class: "spinner" }), " Tailoring…"));
      try { out.replaceChildren(tailorResult(await post("/api/tailor", { job_id: pick.value, resume_text: text }), job(pick.value), text)) }
      catch (e) { out.replaceChildren(el("p", { class: "notice bad" }, e.message)) }
    } }, "Suggest changes")), out,
    versions.length ? el("details", {}, el("summary", {}, `Approved versions in this browser (${versions.length})`),
      el("table", {}, versions.map((v, i) => el("tr", {}, el("td", {}, v.name), el("td", {}, v.created), el("td", {}, v.job),
        el("td", {}, el("button", { class: "btn small", onclick() { downloadDocx(v.text, v.name) } }, "DOCX"), " ",
          el("button", { class: "btn small danger", onclick() { versions.splice(i, 1); store.set("resumeVersions", JSON.stringify(versions)); render() } }, "Delete")))))) : "");
}
function tailorResult(r, j, original) {
  const draft = el("textarea", { rows: 18, "aria-label": "Tailored draft" }, r.draft || original);
  return el("div", { style: "margin-top:12px" },
    r.warnings.map(w => el("p", { class: "notice" }, "⚠ " + w)),
    el("h3", {}, "Suggested summary"), el("p", {}, r.summary),
    el("div", { class: "two" }, el("div", {}, el("h3", {}, "Most relevant projects"), el("div", { class: "tags" }, r.relevant_projects.map(x => el("span", { class: "tag acc" }, x)))),
      el("div", {}, el("h3", {}, "Keywords from the job"), el("div", { class: "tags" }, r.keywords.map(k => el("span", { class: "tag " + (k.in_resume ? "ok" : "warn"), title: k.in_resume ? "Already in your resume" : "Not in your resume: add only if true" }, (k.in_resume ? "✓ " : "+ ") + k.keyword))))),
    r.bullet_suggestions.length ? el("div", {}, el("h3", { style: "margin-top:10px" }, "Bullet suggestions"), el("table", {}, el("tr", {}, el("th", {}, "Your bullet"), el("th", {}, "Suggestion"), el("th", {}, "Why")),
      r.bullet_suggestions.map(b => el("tr", {}, el("td", {}, b.original), el("td", {}, b.suggested), el("td", { class: "muted" }, b.reason))))) : "",
    el("h3", { style: "margin-top:10px" }, "Draft (edit freely — it stays a draft until you approve)"), draft,
    el("div", { class: "row", style: "margin-top:8px" },
      el("button", { class: "btn primary", onclick() {
        const name = prompt("Version name", `${j.company} - ${j.title}`.slice(0, 60)); if (!name) return;
        const vs = readJSON("resumeVersions", []); vs.unshift({ name, job: `${j.title} · ${j.company}`, jobId: j.id, text: draft.value, created: today() });
        store.set("resumeVersions", JSON.stringify(vs.slice(0, 30)));
        setApp(j, { "Resume Version": name }, "Draft approved and linked to this application");
      } }, "Approve & link to application"),
      el("button", { class: "btn", onclick() { downloadDocx(draft.value, `${j.company}-${j.title}`) } }, "Download DOCX"),
      el("button", { class: "btn", onclick() { printText(draft.value) } }, "Print / save PDF")));
}
async function downloadDocx(text, name) {
  try {
    const token = store.get("session", sessionStorage);
    const r = await fetch("/api/tailor", { method: "POST", headers: { "Content-Type": "application/json", Authorization: "Bearer " + token }, body: JSON.stringify({ action: "docx", text, name }) });
    if (!r.ok) throw new Error("Export failed");
    const a = el("a", { href: URL.createObjectURL(await r.blob()), download: (name || "resume").replace(/[^\w.-]+/g, "_") + ".docx" }); a.click(); URL.revokeObjectURL(a.href);
  } catch (e) { fail(e) }
}
function printText(text) {
  const w = window.open("", "_blank"); if (!w) return toast("Allow pop-ups to print");
  w.document.title = "Resume"; const pre = w.document.createElement("pre"); pre.style.cssText = "font:12pt/1.45 Georgia,serif;white-space:pre-wrap;margin:2cm";
  pre.textContent = text; w.document.body.append(pre); w.focus(); w.print();
}

// ---------- analytics ----------
function bars(obj, total) {
  const entries = Object.entries(obj || {}); if (!entries.length) return el("p", { class: "muted" }, "No data in this range.");
  const max = Math.max(...entries.map(([, v]) => v), 1);
  return el("div", { class: "bars" }, entries.map(([k, v]) => el("div", { class: "bar" }, el("span", {}, k), el("span", { class: "track" }, el("span", { class: "fill", style: `width:${Math.round(100 * v / max)}%` })), el("span", { class: "v" }, v))));
}
const pct = v => v == null ? "n/a" : v + "%";
function viewAnalytics() {
  const box = el("div", {}, el("div", { class: "empty" }, el("span", { class: "spinner" }), " Calculating…"));
  const draw = a => box.replaceChildren(
    el("div", { class: "tiles" }, tile(a.total_discovered, "Jobs discovered"), tile(a.new_since_last_search ?? "n/a", "New since last search"),
      tile(a.by_status.Verified, "Verified"), tile(a.by_status["Needs Review"], "Needs review"), tile(a.by_status.Rejected + a.by_status.Closed, "Rejected / closed"),
      tile(a.applications, "Applications"), tile(a.assessments, "Assessments"), tile(a.interviews, "Interviews"), tile(a.offers, "Offers"), tile(a.rejections, "Rejections"),
      tile(pct(a.application_to_interview_pct), "Application → interview"), tile(pct(a.interview_to_offer_pct), "Interview → offer")),
    el("div", { class: "two" },
      el("section", { class: "panel" }, el("h2", {}, "By role"), bars(a.by_role)), el("section", { class: "panel" }, el("h2", {}, "By location"), bars(a.by_location)),
      el("section", { class: "panel" }, el("h2", {}, "By source"), bars(a.by_source)), el("section", { class: "panel" }, el("h2", {}, "By employment type"), bars(a.by_employment)),
      el("section", { class: "panel" }, el("h2", {}, "Posted (week starting)"), bars(a.by_posted_week)),
      el("section", { class: "panel" }, el("h2", {}, "Resume match"), a.match_distribution ? bars(a.match_distribution) : el("p", { class: "muted" }, "Add a resume profile to see match scores."))),
    el("section", { class: "panel" }, el("h2", {}, "Searches & API usage"),
      el("p", {}, `${a.searches.runs} search runs · ${a.searches.serpapi_used_estimated} SerpApi searches recorded by this app (estimated)`,
        a.searches.serpapi_used_confirmed_this_month != null ? ` · ${a.searches.serpapi_used_confirmed_this_month} used this month according to SerpApi (confirmed)` : " · confirmed usage unavailable")),
    el("section", { class: "panel" }, el("h2", {}, "Current application stages"), bars(a.current_stages)));
  const load = () => api("/api/analytics?range=" + S.range).then(draw).catch(e => box.replaceChildren(el("p", { class: "notice bad" }, e.message)));
  load();
  const seg = el("div", { class: "seg" });
  const drawSeg = () => seg.replaceChildren(...[["7", "7 days"], ["30", "30 days"], ["90", "90 days"], ["all", "All time"]].map(([v, l]) => el("button", { "aria-pressed": String(S.range === v), onclick() { S.range = v; drawSeg(); load() } }, l)));
  drawSeg();
  return [el("div", { class: "head" }, el("div", {}, el("h1", {}, "Analytics"), el("div", { class: "sub" }, "Calculated from your stored data only. n/a means there is not enough data.")), seg), box];
}

// ---------- settings ----------
function viewSettings() {
  const s = { ...S.data.settings }, b = S.data.budget || {};
  const list = (key, label, ph) => el("label", { class: "f" }, label, el("input", { type: "text", value: s[key].join(", "), placeholder: ph, oninput(e) { s[key] = e.target.value.split(",").map(x => x.trim()).filter(Boolean) } }));
  const types = ["full-time", "internship", "contract", "part-time", "graduate program"];
  return [el("div", { class: "head" }, el("div", {}, el("h1", {}, "Settings"), el("div", { class: "sub" }, "Used by the dashboard and by scheduled searches."))),
    el("section", { class: "panel" }, el("h2", {}, "Search preferences"),
      el("div", { class: "grid", style: "grid-template-columns:repeat(auto-fit,minmax(240px,1fr))" },
        list("roles", "Job roles (comma separated)", "Data Analyst, Data Engineer"),
        list("locations", "Locations (comma separated)", "Pune, Bengaluru"),
        el("label", { class: "f" }, "Work mode", el("select", { onchange(e) { s.mode = e.target.value } }, [["any", "Any (office/hybrid in locations + WFH in India)"], ["wfh", "Work from home only"], ["onsite", "Office / hybrid only"]].map(([v, l]) => el("option", { value: v, selected: s.mode === v || null }, l)))),
        el("label", { class: "f" }, "Posted within", el("select", { onchange(e) { s.max_age_days = Number(e.target.value) } }, [1, 3, 7, 14, 30].map(v => el("option", { value: v, selected: s.max_age_days === v || null }, v === 1 ? "24 hours" : v + " days")))),
        list("exclude", "Exclude keywords", "e.g. sales, BPO"), list("prefer", "Preferred companies", "e.g. Mastercard, Persistent"),
        el("label", { class: "f" }, "Follow up after (days)", el("input", { type: "number", min: 1, max: 30, value: s.follow_up_days, oninput(e) { s.follow_up_days = Number(e.target.value) } }))),
      el("fieldset", { style: "border:0;padding:0;margin:12px 0 0" }, el("legend", { class: "muted" }, "Employment types"),
        el("div", { class: "row" }, types.map(t => el("label", { class: "chk" }, el("input", { type: "checkbox", checked: s.employment_types.includes(t) || null, onchange(e) { s.employment_types = e.target.checked ? [...s.employment_types, t] : s.employment_types.filter(x => x !== t) } }), t)))),
      el("div", { class: "row", style: "margin-top:12px" }, el("button", { class: "btn primary", async onclick() { try { S.data.settings = await post("/api/settings", s); toast("Settings saved") } catch (e) { fail(e) } } }, "Save settings"))),
    serpapiPanel(b), sheetPanel(), accountPanel(),
    el("section", { class: "panel" }, el("h2", {}, "Privacy"),
      el("p", { class: "muted" }, "Resume files are parsed in memory and discarded; only the extracted profile is stored (hidden _profile tab). Tailored drafts and resume text live only in this browser and can be deleted in Resume Lab. Nothing is ever sent to employers or recruiters automatically."))];
}

function serpapiPanel(b) {
  const box = el("section", { class: "panel" }, el("h2", {}, "SerpApi key"), el("p", { class: "muted" }, el("span", { class: "spinner" }), " Checking…"));
  const input = el("input", { type: "password", autocomplete: "off", placeholder: "Paste a SerpApi key", "aria-label": "SerpApi key", style: "flex:1 1 260px" });
  const draw = st => {
    const line = { own: `Using your key ${st.hint}.`, server: "Using the server's key (SERPAPI_KEY).", none: "No key yet: searches are disabled until you add one.",
      error: st.error }[st.source];
    box.replaceChildren(el("h2", {}, "SerpApi key"),
      el("p", {}, line, st.searches_left != null ? ` ${st.searches_left} searches left (confirmed by SerpApi)${st.used_this_month != null ? `, ${st.used_this_month} used this month` : ""}.` : ""),
      el("div", { class: "row" }, input,
        el("button", { class: "btn primary", async onclick() {
          if (!input.value.trim()) return toast("Paste a key first");
          try { draw(await post("/api/serpapi", { key: input.value.trim() })); input.value = ""; toast("Key saved and verified with SerpApi") } catch (e) { fail(e) }
        } }, st.source === "own" ? "Replace key" : "Save & test key"),
        st.source === "own" ? el("button", { class: "btn danger", async onclick() {
          if (!confirm("Remove your saved SerpApi key?")) return;
          try { draw(await post("/api/serpapi", { action: "remove" })); toast("Key removed") } catch (e) { fail(e) } } }, "Remove") : ""),
      el("p", { class: "muted" }, "The key is checked with SerpApi (free, no search used), stored encrypted, and never shown again in full. Get one at serpapi.com/manage-api-key. ",
        `Per-run limit ${b.per_run}, monthly safety limit ${b.monthly_limit}.`));
  };
  api("/api/serpapi").then(draw).catch(e => box.replaceChildren(el("h2", {}, "SerpApi key"), el("p", { class: "notice bad" }, e.message)));
  return box;
}
function sheetPanel() {
  const u = S.data.user || {};
  if (!u.multi_user) return "";
  const box = el("section", { class: "panel" }, el("h2", {}, "My Google Sheet tab"), el("p", { class: "muted" }, el("span", { class: "spinner" }), " Checking…"));
  api("/api/sheet").then(st => {
    if (!st.configured) return box.replaceChildren(el("h2", {}, "My Google Sheet tab"), el("p", { class: "muted" }, "The admin hasn't connected a Google spreadsheet."));
    const toggle = el("input", { type: "checkbox", checked: st.enabled || null, async onchange(e) {
      try { S.data.settings = await post("/api/settings", { ...S.data.settings, sheet_mirror: e.target.checked }); toast(e.target.checked ? "Your jobs will be copied to your tab" : "Copying to the sheet is off") } catch (err) { fail(err) } } });
    box.replaceChildren(el("h2", {}, "My Google Sheet tab"),
      el("p", {}, "Your jobs are copied to your own tab ", el("b", {}, `“${st.tab}”`), " in the admin's Google spreadsheet after every search. It's one-way: editing the tab doesn't change the app, and nothing is deleted from it."),
      el("p", { class: "muted" }, "Note: the spreadsheet's owner (the admin) can see every user's tab. Turn this off if you don't want that."),
      el("div", { class: "row" }, el("label", { class: "chk" }, toggle, "Copy my jobs to my tab"),
        el("button", { class: "btn", async onclick(e) {
          e.target.disabled = true;
          try { const r = await post("/api/sheet", { action: "sync" }); toast(`Synced: ${r.added} added, ${r.updated} updated`) } catch (err) { fail(err) } finally { e.target.disabled = false }
        } }, "Sync now")));
  }).catch(e => box.replaceChildren(el("h2", {}, "My Google Sheet tab"), el("p", { class: "notice bad" }, e.message)));
  return box;
}
function accountPanel() {
  const u = S.data.user || {};
  if (!u.multi_user) return el("section", { class: "panel" }, el("h2", {}, "Account"), el("p", { class: "muted" }, "Single-user mode: the dashboard password is set on the server (DASHBOARD_PASSWORD)."));
  const cur = el("input", { type: "password", autocomplete: "current-password", "aria-label": "Current password" });
  const nw = el("input", { type: "password", autocomplete: "new-password", "aria-label": "New password" });
  return el("section", { class: "panel" }, el("h2", {}, "Account"),
    el("p", {}, `Signed in as ${u.email}${u.role === "admin" ? " (admin)" : ""}. Your jobs, applications, resume profiles and keys are visible only to you.`),
    el("div", { class: "row" }, el("label", { class: "f" }, "Current password", cur), el("label", { class: "f" }, "New password (10+)", nw),
      el("button", { class: "btn", async onclick() {
        try { await post("/api/account", { action: "change_password", current: cur.value, new: nw.value }); toast("Password changed. Please sign in again."); store.set("session", null, sessionStorage); showGate() } catch (e) { fail(e) } } }, "Change password")),
    el("div", { class: "row", style: "margin-top:12px" },
      el("button", { class: "btn", async onclick() { try { await post("/api/account", { action: "sign_out_everywhere" }); store.set("session", null, sessionStorage); showGate("Signed out on all devices.") } catch (e) { fail(e) } } }, "Sign out everywhere"),
      el("button", { class: "btn danger", async onclick() {
        const pw = prompt("This permanently deletes your account and ALL your data (jobs, applications, resume profiles, saved key). Type your password to confirm:");
        if (!pw) return;
        try { await post("/api/account", { action: "delete", password: pw }); store.set("session", null, sessionStorage); showGate("Your account and data were deleted.") } catch (e) { fail(e) } } }, "Delete my account")));
}

// ---------- archive ----------
function viewArchive() {
  const rows = S.data.archive, picked = new Set();
  const clear = async scope => {
    if (!confirm(scope === "all" ? "Move ALL current jobs to the Archive tab? (Nothing is deleted; you can restore them here.)" : "Move jobs found yesterday to the Archive tab?")) return;
    try { const r = await post("/api/action", { action: "clear", scope }); toast(`Archived ${r.archived} job(s)`); load() } catch (e) { fail(e) }
  };
  const restore = async ids => { try { const r = await post("/api/application", { action: "restore", job_ids: ids }); toast(`Restored ${r.count} job(s)`); load() } catch (e) { fail(e) } };
  return [el("div", { class: "head" }, el("div", {}, el("h1", {}, "Archive"), el("div", { class: "sub" }, "Archived jobs are kept in the sheet's Archive tab and never re-added by searches.")),
    el("div", { class: "row" }, el("button", { class: "btn", onclick() { clear("yesterday") } }, "Archive yesterday's jobs"), el("button", { class: "btn danger", onclick() { clear("all") } }, "Archive all jobs"))),
    rows.length ? el("section", { class: "panel" }, el("div", { class: "row", style: "margin-bottom:8px" }, el("button", { class: "btn small", onclick() { if (picked.size) restore([...picked]) } }, "Restore selected")),
      el("table", {}, el("tr", {}, el("th", {}, ""), el("th", {}, "Job"), el("th", {}, "Location"), el("th", {}, "Found"), el("th", {}, "Status"), el("th", {}, "")),
        rows.map(r => el("tr", {}, el("td", {}, el("input", { type: "checkbox", "aria-label": "Select " + r.title, onchange(e) { e.target.checked ? picked.add(r.id) : picked.delete(r.id) } })),
          el("td", {}, `${r.title} · ${r.company}`), el("td", {}, r.location), el("td", { class: "mono" }, r.found), el("td", {}, r.status),
          el("td", {}, el("button", { class: "btn small", onclick() { restore([r.id]) } }, "Restore")))))) : el("div", { class: "empty" }, "The archive is empty.")];
}

// ---------- render ----------
function render() {
  renderNav();
  if (!S.data) return;
  const v = { dashboard: viewDashboard, find: viewFind, saved: viewSaved, apps: viewApps, follow: viewFollow, resume: viewResume, analytics: viewAnalytics, settings: viewSettings, archive: viewArchive }[S.view] || viewDashboard;
  $("#main").replaceChildren(...v());
  if ($("#list")) renderList();
}
S.view = (location.hash || "#dashboard").slice(1);
if (!VIEWS.some(([k]) => k === S.view)) S.view = "dashboard";
if (store.get("session", sessionStorage)) { $("#app").hidden = false; load() } else showGate();
