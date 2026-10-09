"use strict";
/* आपले जॉब्स आपल्या हातात dashboard. Plain JS, no framework. All data comes from /api/*; nothing is invented here.
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
  ["follow", "Follow-ups"], ["resume", "Resume Lab"], ["analytics", "Analytics"], ["settings", "Settings"], ["archive", "Archive"],
  ["admin", "Admin"]];
const isAdmin = () => !!(S.data && S.data.user && S.data.user.multi_user && S.data.user.role === "admin");
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

// ---------- sign in / create account ----------
const AUTH = { multi: false, registration: "closed", page: "login" };
function showGate(msg = "") {
  $("#app").hidden = true; $("#gate").hidden = false; $("#gateErr").textContent = msg;
  AUTH.page = location.hash === "#signup" ? "signup" : "login";
  fetch("/api/health").then(r => r.json()).then(h => {
    AUTH.multi = h.auth === "users"; AUTH.registration = h.registration || "closed"; drawGate();
  }).catch(drawGate);
}
function drawGate() {
  const signup = AUTH.multi && AUTH.page === "signup" && AUTH.registration !== "closed";
  $("#gateTitle").textContent = signup ? "Create your account" : "Sign in";
  $("#gateSub").textContent = !AUTH.multi ? "Enter the dashboard password. Your session lasts 12 hours."
    : signup ? "Your jobs, applications and resume stay private to your account." : "Welcome back. Sessions last 12 hours.";
  $("#nameField").hidden = !signup; $("#emailField").hidden = !AUTH.multi;
  $("#emailLabel").textContent = signup ? "Email" : "Email or username";
  $("#pw2Field").hidden = !signup; $("#inviteField").hidden = !(signup && AUTH.registration === "invite");
  $("#pw").autocomplete = signup ? "new-password" : "current-password";
  $("#pw").placeholder = signup ? "At least 10 characters" : "";
  $("#gateBtn").textContent = signup ? "Create account" : "Sign in";
  const sw = $("#gateSwitch");
  sw.hidden = !(AUTH.multi && AUTH.registration !== "closed");
  sw.replaceChildren(signup ? "Already have an account? " : "New here? ",
    el("a", { href: signup ? "#login" : "#signup", onclick(e) { e.preventDefault(); AUTH.page = signup ? "login" : "signup";
      history.replaceState(null, "", "#" + AUTH.page); $("#gateErr").textContent = ""; drawGate() } }, signup ? "Sign in" : "Create an account"));
  (AUTH.multi ? (signup ? $("#rname") : $("#email")) : $("#pw")).focus();
}
$("#gateForm").onsubmit = async e => {
  e.preventDefault();
  const signup = AUTH.multi && AUTH.page === "signup";
  const err = m => { $("#gateErr").textContent = m };
  const login = $("#email").value.trim();
  if (AUTH.multi && signup && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(login)) return err("Enter a valid email address");
  if (AUTH.multi && !signup && !login) return err("Enter your email or username");
  if (signup && $("#pw").value.length < 10) return err("Password must be at least 10 characters");
  if (signup && $("#pw").value !== $("#pw2").value) return err("The two passwords don't match");
  if (!$("#pw").value) return err("Enter your password");
  const btn = $("#gateBtn"); btn.disabled = true; err("");
  const body = signup ? { name: $("#rname").value.trim(), email: $("#email").value.trim(), password: $("#pw").value, invite_code: $("#invite").value.trim() }
    : AUTH.multi ? { email: $("#email").value.trim(), password: $("#pw").value } : { password: $("#pw").value };
  try {
    const r = await fetch(signup ? "/api/register" : "/api/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.error || (signup ? "Could not create the account" : "Sign-in failed"));
    store.set("session", d.token, sessionStorage); $("#pw").value = ""; $("#pw2").value = "";
    $("#gate").hidden = true; $("#app").hidden = false;
    if (signup) { S.view = "settings"; history.replaceState(null, "", "#settings");
      setTimeout(() => toast(`Welcome${d.name ? ", " + d.name : ""}! Add your SerpApi and Groq keys in “API keys” below to start.`, 9000), 600) }
    else if (["login", "signup"].includes(location.hash.slice(1))) history.replaceState(null, "", "#dashboard");
    load();
  } catch (x) { err(x.message) } finally { btn.disabled = false }
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
    archive: S.data ? S.data.archive.length : 0, admin: S.data && S.data.user ? S.data.user.pending_requests : 0 };
  const who = S.data && S.data.user && S.data.user.multi_user ? el("div", { class: "sub", style: "padding:0 10px 12px;margin-top:-10px" }, S.data.user.name || S.data.user.email) : "";
  $("#nav").replaceChildren(el("div", { class: "brand" }, "आपले जॉब्स आपल्या हातात"), who,
    ...VIEWS.filter(([k]) => k !== "admin" || isAdmin()).map(([k, label]) => el("button", { "aria-current": S.view === k ? "page" : null, onclick() { go(k) } },
      label, n[k] ? el("span", { class: "count" + (k === "admin" ? " alert" : ""), "aria-label": k === "admin" ? `${n[k]} pending requests` : null }, n[k]) : "")),
    el("div", { class: "foot" }, el("button", { class: "btn small", onclick: load }, "Refresh"), el("button", { class: "btn small", onclick: toggleTheme }, "Theme"),
      el("button", { class: "btn small", onclick() { store.set("session", null, sessionStorage); showGate() } }, "Sign out")));
}

// ---------- data ----------
async function load() {
  $("#main").replaceChildren(el("div", { class: "empty" }, el("span", { class: "spinner" }), " Loading your jobs…"));
  try {
    S.data = await api("/api/jobs"); render();
    const p = S.data.user && S.data.user.pending_requests;
    if (isAdmin() && p && S.view !== "admin") toast(`${p} user${p === 1 ? "" : "s"} asked to use your API keys`, 8000, { label: "Review", fn: () => go("admin") });
  }
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
    ? ext(j.apply_link, "✓ Apply now on company site ↗", "btn small verified", "Verified: employer, exact vacancy and open status confirmed")
    : ext(j.apply_link, { company: "Apply now – company listing (not verified) ↗", portal: "Apply now – job-board listing (not verified) ↗", careers: "Apply now – careers page (not verified) ↗" }[j.apply_kind] || "Apply now (not verified) ↗",
      "btn small unverified", "Not verified: check the role on the employer's own site before applying");
  const sk = j.skills || { required: [], preferred: [] };
  const detailsBlock = (j.responsibilities && j.responsibilities.length) || sk.required.length || sk.preferred.length
    ? el("div", { class: "skills" },
        j.responsibilities && j.responsibilities.length ? el("div", {}, el("span", { class: "lbl" }, "Key responsibilities:"),
          el("ul", { style: "margin:4px 0 0 18px;padding:0" }, j.responsibilities.slice(0, 4).map(x => el("li", {}, x)))) : "",
        sk.required.length ? el("div", {}, el("span", { class: "lbl" }, "Skills needed:"), el("span", { class: "tags" }, sk.required.map(x => el("span", { class: "tag acc" }, x)))) : "",
        sk.preferred.length ? el("div", {}, el("span", { class: "lbl" }, "Nice to have:"), el("span", { class: "tags" }, sk.preferred.map(x => el("span", { class: "tag" }, x)))) : "")
    : el("p", { class: "muted", style: "margin:6px 0 0" }, "No job description stored for this listing yet — open it to see the responsibilities and skills.");
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
      detailsBlock, matchBlock(j),
      el("div", { class: "actions" }, applyBtn,
        st === "Discovered" ? el("button", { class: "btn small", onclick() { setApp(j, { Stage: "Saved" }, "Saved") } }, "☆ Save") : "",
        el("label", { class: "f", style: "flex-direction:row;align-items:center" }, el("span", { class: "sr" }, ""),
          el("select", { "aria-label": "Application status", onchange(e) { setApp(j, { Stage: e.target.value }, "Status: " + e.target.value) } },
            S.data.stages.map(s => el("option", { value: s, selected: s === st || null }, s)))),
        st !== "Not Interested" ? el("button", { class: "btn small danger", onclick() { setApp(j, { Stage: "Not Interested" }, "Marked not interested") } }, "Not interested") : "",
        el("button", { class: "btn small", onclick() { openApp(j) } }, "Track / notes"),
        el("button", { class: "btn small", onclick() { S.tailorJob = j.id; go("resume"); setTimeout(() => { const p = $("#atsPanel"); if (p) p.scrollIntoView({ behavior: "smooth" }) }, 400) } }, "Check ATS fit / tailor"),
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
    (!minMatch || !S.data.profile || (j.match && j.match.overall >= minMatch)) &&   // no resume yet: no scores to filter on
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
    el("label", { class: "f", title: S.data.profile ? "" : "Upload a resume in Resume Lab to get match scores" }, S.data.profile ? `Match ≥ ${f.minMatch}%` : "Match (add a resume first)", el("input", { type: "range", min: 0, max: 100, step: 10, value: f.minMatch, disabled: !S.data.profile || null, oninput(e) { f.minMatch = e.target.value; e.target.previousSibling.textContent = `Match ≥ ${f.minMatch}%`; S.page = 25; renderList() } })),
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
    el("div", { class: "sub" }, "Upload a PDF or DOCX (max 3 MB). The file is read in memory and discarded; its text is saved (encrypted, private to you) in My resumes, and your Groq key turns it into an editable profile. Check any resume against a job with the ATS check."))),
    el("div", { class: "empty" }, el("span", { class: "spinner" }), " Loading profiles…"));
  loadProfiles().then(c => root.replaceChildren(root.firstChild, resumeBody(c))).catch(e => { root.lastChild.replaceWith(el("p", { class: "notice bad" }, e.message)) });
  return [root];
}
function resumeBody(c) {
  const p = c.profiles.find(x => x.id === c.active);
  const file = el("input", { type: "file", accept: ".pdf,.docx", hidden: true, async onchange(e) {
    const f = e.target.files[0]; if (!f) return;
    try {
      const name = prompt("Name for this resume (e.g. “Data Analyst – Oct 2026”)", f.name.replace(/\.(pdf|docx)$/i, "")) || "";
      toast("Reading and analysing your resume…", 30000);
      const res = await post("/api/resume", { file: await fileToBase64(f), filename: f.name, name });
      if (res.version) S.resumeId = res.version.id;
      delete res.text; S.profiles = res;
      if (res.profile_error) toast(`Saved as “${res.version ? res.version.name : "your resume"}” in My resumes, but the AI profile couldn't be built: ${res.profile_error}`, 12000);
      else toast(res.version ? `Saved as “${res.version.name}” in My resumes. Review the profile below.` : "Profile created. Review it below.");
      render(); load();
    } catch (err) { fail(err) } finally { e.target.value = "" }
  } });
  const head = el("section", { class: "panel" }, el("div", { class: "row" },
    c.profiles.length > 0 && el("label", { class: "f" }, "Active profile", el("select", { onchange(e) { saveProfile({ action: "activate", id: e.target.value }, "Profile switched").then(render) } },
      c.profiles.map(x => el("option", { value: x.id, selected: x.id === c.active || null }, x.name)))),
    el("button", { class: "btn primary", onclick() { file.click() } }, "Upload resume (PDF/DOCX)"), file,
    p ? el("label", { class: "chk" }, el("input", { type: "checkbox", checked: c.use_in_search || null, onchange(e) { saveProfile({ action: "use_in_search", value: e.target.checked }) } }), "Use this profile's roles in searches") : "",
    p ? el("button", { class: "btn danger", onclick() { if (confirm(`Delete profile "${p.name}"? Your saved resumes are kept.`)) saveProfile({ action: "delete", id: p.id }, "Deleted").then(render) } }, "Delete profile") : ""));
  const profilePanel = !p ? el("div", { class: "empty" }, "No resume profile yet. Upload your resume to get started.") : (() => {
    const edu = el("textarea", { rows: 3, "aria-label": "Education" }, (p.education || []).join("\n"));
    const certs = el("textarea", { rows: 2, "aria-label": "Certifications" }, (p.certifications || []).join("\n"));
    const years = el("input", { type: "number", min: 0, max: 40, step: 0.5, value: p.experience_years, "aria-label": "Years of experience" });
    return el("details", { class: "panel", open: !S.resumeId || null }, el("summary", {}, el("b", {}, "Profile (from your resume) — check and correct it")), el("p", { class: "muted" }, p.summary),
      el("div", { class: "two" }, listEditor(p, "roles", "Target roles"), listEditor(p, "locations", "Preferred locations"),
        listEditor(p, "programming_languages", "Programming languages"), listEditor(p, "data_tools", "Data tools"),
        listEditor(p, "databases", "Databases"), listEditor(p, "frameworks", "Frameworks / libraries / cloud"),
        listEditor(p, "skills", "Other skills"), listEditor(p, "employment_preferences", "Employment preferences")),
      el("div", { class: "two", style: "margin-top:12px" }, el("label", { class: "f" }, "Education (one per line)", edu), el("label", { class: "f" }, "Certifications (one per line)", certs)),
      el("div", { class: "row", style: "margin-top:10px" }, el("label", { class: "f" }, "Full-time experience (years)", years),
        el("button", { class: "btn", onclick() { saveProfile({ action: "update", id: p.id, education: edu.value.split("\n").filter(Boolean), certifications: certs.value.split("\n").filter(Boolean), experience_years: Number(years.value) }) } }, "Save education & experience")));
  })();
  return el("div", {}, head, libraryPanel(), atsPanel(), profilePanel);
}

// ----- My resumes (named collection, stored encrypted in the user's account) -----
async function resumeText(id) { return (await post("/api/resumes", { action: "get", id })).text }
function pasteDialog(title, onSave) {
  const dlg = $("#dlg"), name = el("input", { type: "text", placeholder: "Name, e.g. Data Analyst – Oct 2026", style: "width:100%" }),
    text = el("textarea", { rows: 14, placeholder: "Paste the full resume text" });
  dlg.replaceChildren(el("div", { class: "dh" }, el("h2", { style: "margin:0" }, title), el("button", { class: "btn small", onclick() { dlg.close() } }, "Close")),
    el("div", { class: "db" }, el("label", { class: "f" }, "Name", name), el("label", { class: "f", style: "margin-top:10px" }, "Resume text", text)),
    el("div", { class: "df" }, el("button", { class: "btn primary", async onclick() { if (await onSave(name.value.trim(), text.value)) dlg.close() } }, "Save")));
  dlg.showModal(); name.focus();
}
function libraryPanel() {
  const box = el("section", { class: "panel" }, el("h2", {}, "My resumes"), el("p", { class: "muted" }, el("span", { class: "spinner" }), " Loading…"));
  const legacy = Object.keys(localStorage).filter(k => k.startsWith("resumeText:"));
  const draw = vs => {
    if (!S.resumeId && vs.length) S.resumeId = vs[0].id;
    const SRC = { upload: "uploaded", pasted: "pasted", tailored: "tailored", edited: "edited" };
    box.replaceChildren(el("div", { class: "row", style: "justify-content:space-between" }, el("h2", { style: "margin:0" }, `My resumes (${vs.length})`),
        el("div", { class: "row" }, el("button", { class: "btn small", onclick() { pasteDialog("Add a resume version", async (name, text) => {
          try { const v = await post("/api/resumes", { action: "save", name, text, source: "pasted" }); S.resumeId = v.id; toast(`Saved “${v.name}”`); reload(); return true } catch (e) { fail(e); return false } }) } }, "+ Paste a version"))),
      el("p", { class: "muted" }, "Every upload, pasted version and approved tailored draft is kept here under its own name — pick any of them for an ATS check or tailoring. Stored encrypted; only you can see them."),
      legacy.length ? el("p", { class: "notice" }, "A resume from the earlier version is stored only in this browser. ",
        el("button", { class: "btn small", async onclick() {
          for (const k of legacy) { try { await post("/api/resumes", { action: "save", name: "Resume (from this browser)", text: localStorage.getItem(k), source: "pasted" }); localStorage.removeItem(k) } catch (e) { fail(e) } }
          reload() } }, "Save it to My resumes")) : "",
      vs.length ? el("table", {}, el("tr", {}, ["", "Name", "Type", "Saved", "Size", ""].map(h => el("th", {}, h))),
        vs.map(v => el("tr", {},
          el("td", {}, el("input", { type: "radio", name: "resumePick", "aria-label": "Use " + v.name, checked: S.resumeId === v.id || null, onchange() { S.resumeId = v.id; drawAts() } })),
          el("td", {}, el("b", {}, v.name), v.job ? el("div", { class: "muted" }, "for " + v.job) : ""),
          el("td", {}, el("span", { class: "tag" + (v.source === "tailored" ? " acc" : "") }, SRC[v.source] || v.source)),
          el("td", { class: "mono" }, v.created), el("td", { class: "muted" }, `${Math.round(v.chars / 100) / 10}k chars`),
          el("td", {}, el("span", { class: "row" },
            el("button", { class: "btn small", onclick() { const n = prompt("New name", v.name); if (n) post("/api/resumes", { action: "rename", id: v.id, name: n }).then(reload).catch(fail) } }, "Rename"),
            el("button", { class: "btn small", async onclick() { try { downloadDocx(await resumeText(v.id), v.name) } catch (e) { fail(e) } } }, "DOCX"),
            el("button", { class: "btn small danger", onclick() { if (confirm(`Delete “${v.name}”? This can't be undone.`)) post("/api/resumes", { action: "delete", id: v.id }).then(() => { if (S.resumeId === v.id) S.resumeId = null; reload() }).catch(fail) } }, "Delete"))))))
        : el("div", { class: "empty" }, "No resumes yet. Upload one above or paste a version."));
    S.resumes = vs; drawAts();
  };
  const reload = () => api("/api/resumes").then(r => draw(r.versions)).catch(e => box.replaceChildren(el("h2", {}, "My resumes"), el("p", { class: "notice bad" }, e.message)));
  reload();
  return box;
}

// ----- ATS check + AI suggestions -----
let drawAts = () => {};
function atsPanel() {
  const box = el("section", { class: "panel", id: "atsPanel" });
  const jobs = S.data.jobs.filter(j => !TERMINAL.includes(stageOf(j)) && j.priority !== "Hidden");
  const pick = el("select", { "aria-label": "Job" }, el("option", { value: "" }, "Paste a job description instead…"),
    jobs.map(j => el("option", { value: j.id, selected: j.id === S.tailorJob || null }, `${j.title} · ${j.company}`)));
  const jdTitle = el("input", { type: "text", placeholder: "Job title (e.g. Junior Data Analyst)" });
  const jd = el("textarea", { rows: 6, placeholder: "Paste the job description" });
  const jdBox = el("div", { class: "grid", style: "grid-template-columns:1fr;margin-top:8px" }, jdTitle, jd);
  const out = el("div", { "aria-live": "polite" });
  const target = () => pick.value ? { job_id: pick.value } : { job_text: jd.value, job_title: jdTitle.value };
  const label = () => pick.value ? `${job(pick.value).title} · ${job(pick.value).company}` : (jdTitle.value || "pasted job");
  pick.onchange = () => { jdBox.hidden = !!pick.value; S.tailorJob = pick.value || null };
  jdBox.hidden = !!pick.value;
  drawAts = () => {
    const v = (S.resumes || []).find(x => x.id === S.resumeId);
    box.replaceChildren(el("h2", {}, "ATS check & suggestions"),
      el("p", { class: "muted" }, v ? ["Resume: ", el("b", {}, v.name), " (change it in My resumes)"] : "Choose or add a resume in My resumes first."),
      el("div", { class: "row" }, pick,
        el("button", { class: "btn primary", disabled: !v || null, async onclick() {
          out.replaceChildren(el("p", { class: "muted" }, el("span", { class: "spinner" }), " Checking…"));
          try { out.replaceChildren(atsResult(await post("/api/ats", { resume_id: S.resumeId, ...target() }))) } catch (e) { out.replaceChildren(el("p", { class: "notice bad" }, e.message)) } } }, "Check ATS score"),
        el("button", { class: "btn", disabled: !v || null, async onclick() {
          out.replaceChildren(el("p", { class: "muted" }, el("span", { class: "spinner" }), " Asking the AI for truthful suggestions…"));
          try { out.replaceChildren(tailorResult(await post("/api/tailor", { resume_id: S.resumeId, ...target() }), pick.value ? job(pick.value) : null, label())) }
          catch (e) { out.replaceChildren(el("p", { class: "notice bad" }, e.message)) } } }, "AI suggestions & tailored draft")),
      jdBox, out);
  };
  drawAts();
  return box;
}
function atsResult(r) {
  const names = { keywords: "JD keywords", title: "Job title", sections: "Sections", impact: "Measurable results", verbs: "Action verbs", length: "Length", contact: "Contact details" };
  const tone = r.score >= 75 ? "ok" : r.score >= 50 ? "warn" : "bad";
  return el("div", { style: "margin-top:12px" },
    el("div", { class: "row" }, el("div", { class: `score ${r.score >= 75 ? "High" : r.score >= 50 ? "Medium" : "Low"}`, style: "width:90px;height:90px" }, "ATS score", el("small", {}, r.score)),
      el("div", { class: "bars", style: "flex:1 1 300px" }, Object.entries(r.components).filter(([, v]) => v != null).map(([k, v]) => el("div", { class: "bar" },
        el("span", {}, `${names[k]} (×${r.weights[k]})`), el("span", { class: "track" }, el("span", { class: "fill", style: `width:${Math.round(v * 100)}%` })), el("span", { class: "v" }, Math.round(v * 100) + "%"))))),
    el("div", { class: "skills" },
      r.matched_keywords.length ? el("div", {}, el("span", { class: "lbl" }, "Found in your resume:"), el("span", { class: "tags" }, r.matched_keywords.map(k => el("span", { class: "tag ok" }, k)))) : "",
      r.missing_required.length ? el("div", {}, el("span", { class: "lbl" }, "Required, missing:"), el("span", { class: "tags" }, r.missing_required.map(k => el("span", { class: "tag bad" }, k)))) : "",
      r.missing_preferred.length ? el("div", {}, el("span", { class: "lbl" }, "Nice to have, missing:"), el("span", { class: "tags" }, r.missing_preferred.map(k => el("span", { class: "tag warn" }, k)))) : ""),
    el("h3", { style: "margin-top:12px" }, "Suggestions"),
    r.suggestions.length ? el("ol", {}, r.suggestions.map(t => el("li", { style: "margin-bottom:6px" }, el("span", { class: "tag " + (t.priority === "high" ? "bad" : t.priority === "medium" ? "warn" : "") }, t.priority), " ", t.text)))
      : el("p", { class: "notice ok" }, "Nothing major to fix for this job."),
    el("p", { class: `muted` }, r.note), el("span", { class: `tag ${tone}` }, `${r.words} words · ${r.bullets} bullets · ${r.bullets_with_numbers} with numbers`));
}
function tailorResult(r, j, jobLabel) {
  const draft = el("textarea", { rows: 18, "aria-label": "Tailored draft" }, r.draft || "");
  return el("div", { style: "margin-top:12px" },
    r.warnings.map(w => el("p", { class: "notice" }, "⚠ " + w)),
    el("h3", {}, "Suggested summary"), el("p", {}, r.summary),
    el("div", { class: "two" }, el("div", {}, el("h3", {}, "Most relevant projects"), el("div", { class: "tags" }, r.relevant_projects.map(x => el("span", { class: "tag acc" }, x)))),
      el("div", {}, el("h3", {}, "Keywords from the job"), el("div", { class: "tags" }, r.keywords.map(k => el("span", { class: "tag " + (k.in_resume ? "ok" : "warn"), title: k.in_resume ? "Already in your resume" : "Not in your resume: add only if true" }, (k.in_resume ? "✓ " : "+ ") + k.keyword))))),
    r.bullet_suggestions.length ? el("div", {}, el("h3", { style: "margin-top:10px" }, "Bullet suggestions"), el("table", {}, el("tr", {}, el("th", {}, "Your bullet"), el("th", {}, "Suggestion"), el("th", {}, "Why")),
      r.bullet_suggestions.map(b => el("tr", {}, el("td", {}, b.original), el("td", {}, b.suggested), el("td", { class: "muted" }, b.reason))))) : "",
    el("h3", { style: "margin-top:10px" }, "Tailored draft — edit freely; it's only saved when you choose"), draft,
    el("div", { class: "row", style: "margin-top:8px" },
      el("button", { class: "btn primary", async onclick() {
        const name = prompt("Name for this resume version", `${jobLabel}`.slice(0, 70)); if (!name) return;
        try {
          const v = await post("/api/resumes", { action: "save", name, text: draft.value, source: "tailored", job: jobLabel });
          S.resumeId = v.id; toast(`Saved as “${v.name}” in My resumes`);
          if (j) setApp(j, { "Resume Version": v.name }, "Linked to this application");
          render();
        } catch (e) { fail(e) } } }, "Save as new resume version"),
      el("button", { class: "btn", onclick() { downloadDocx(draft.value, jobLabel) } }, "Download DOCX"),
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
    keysPanel(b), sheetPanel(), accountPanel(),
    el("section", { class: "panel" }, el("h2", {}, "Privacy"),
      el("p", { class: "muted" }, "Resume files are parsed in memory and discarded. Your resume texts (My resumes) and API keys are stored encrypted and visible only to you; delete any of them in Resume Lab or here. Nothing is ever sent to employers or recruiters automatically."))];
}

function keysPanel(b) {
  const box = el("section", { class: "panel", id: "keys" }, el("h2", {}, "API keys"), el("p", { class: "muted" }, el("span", { class: "spinner" }), " Checking…"));
  const INFO = {
    serpapi: { title: "SerpApi key — powers job search", get: "https://serpapi.com/users/sign_up", find: "https://serpapi.com/manage-api-key",
      steps: ["Create a free account at serpapi.com (250 searches/month free).", "Open “Your Private API Key” on the dashboard (or the manage-api-key page) and copy it.", "Paste it below and click Save & test."] },
    groq: { title: "Groq key — powers the resume AI (profile, tailoring)", get: "https://console.groq.com/login", find: "https://console.groq.com/keys",
      steps: ["Sign in at console.groq.com (free).", "Go to API Keys → Create API Key and copy it (it starts with gsk_).", "Paste it below and click Save & test. (Groq with a q — free; not xAI's Grok.)"] },
  };
  const card = (kind, st) => {
    const input = el("input", { type: "password", autocomplete: "off", placeholder: kind === "groq" ? "gsk_…" : "Paste your SerpApi key", "aria-label": INFO[kind].title, style: "flex:1 1 260px" });
    const line = { own: `Saved: your key ${st.hint}.`, server: isAdmin() || !(S.data.user || {}).multi_user ? "Using the server's key." : "Using the admin's key (approved).",
      none: "Not added yet.", error: st.error }[st.source];
    return el("div", { class: "mini", style: "padding:14px" },
      el("h3", {}, INFO[kind].title),
      el("p", { style: "margin:4px 0" }, line, kind === "serpapi" && st.searches_left != null ? ` ${st.searches_left} searches left this month (confirmed).` : ""),
      el("div", { class: "row" }, input,
        el("button", { class: "btn primary", async onclick(e) {
          if (!input.value.trim()) return toast("Paste a key first");
          e.target.disabled = true;
          try { await post("/api/keys", { kind, key: input.value.trim() }); input.value = ""; toast("Key verified and saved"); reload() } catch (x) { fail(x) } finally { e.target.disabled = false } } },
          st.source === "own" ? "Replace key" : "Save & test"),
        st.source === "own" ? el("button", { class: "btn danger", async onclick() { if (confirm("Remove this key?")) { try { await post("/api/keys", { kind, action: "remove" }); reload() } catch (x) { fail(x) } } } }, "Remove") : ""),
      el("ol", { class: "muted", style: "margin:8px 0 0 18px;padding:0" }, INFO[kind].steps.map(t => el("li", {}, t))),
      el("div", { class: "row", style: "margin-top:6px" }, ext(INFO[kind].get, "Get a free key ↗", "btn small"), ext(INFO[kind].find, "Find my key ↗", "btn small link")));
  };
  const accessBlock = () => {
    const u = S.data.user || {};
    if (!u.multi_user || u.role === "admin") return "";
    const wrap = el("div", { class: "mini", style: "padding:14px;margin-top:12px" }, el("h3", {}, "No keys of your own?"));
    const fill = st => {
      const ask = label => el("button", { class: "btn", async onclick() {
        const message = prompt("Optional message for the admin (why you need access):", "") ?? null;
        if (message === null) return;
        try { fill(await post("/api/access", { action: "request", message })); toast("Request sent to the admin") } catch (e) { fail(e) } } }, label);
      wrap.replaceChildren(el("h3", {}, "No keys of your own?"), ...({
        none: [el("p", { class: "muted" }, "You can ask the admin for permission to use their SerpApi and Groq keys. They'll see your request and approve or deny it."), ask("Request access to the admin's keys")],
        pending: [el("p", { class: "notice" }, `Request sent${st.requested_at ? " on " + st.requested_at.slice(0, 10) : ""}: waiting for the admin to approve.`)],
        approved: [el("p", { class: "notice ok" }, "Approved: when you haven't saved your own key, your searches and resume AI use the admin's keys. Please use them fairly.")],
        denied: [el("p", { class: "notice bad" }, "The admin declined your request. Add your own free keys above, or ask again."), ask("Ask again")],
      }[st.status] || []));
    };
    api("/api/access").then(fill).catch(() => wrap.remove());
    return wrap;
  };
  const reload = () => api("/api/keys").then(k => box.replaceChildren(el("h2", {}, "API keys"),
    el("p", { class: "muted" }, "Each user uses their own keys. They're checked with the provider (free, no searches used), stored encrypted, and never shown again in full. ",
      `SerpApi limits: up to ${b.per_run} searches per run, ${b.monthly_limit} per month.`),
    el("div", { class: "grid", style: "grid-template-columns:repeat(auto-fit,minmax(320px,1fr))" }, card("serpapi", k.serpapi), card("groq", k.groq)), accessBlock()))
    .catch(e => box.replaceChildren(el("h2", {}, "API keys"), el("p", { class: "notice bad" }, e.message)));
  reload();
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

// ---------- admin ----------
function viewAdmin() {
  if (!isAdmin()) return [el("div", { class: "empty" }, "Only admins can see this page.")];
  const box = el("div", {}, el("div", { class: "empty" }, el("span", { class: "spinner" }), " Loading…"));
  const act = async (action, u) => {
    if (action === "revoke" && !confirm(`Stop ${u.email} from using your keys?`)) return;
    try { await post("/api/access", { action, user_id: u.id }); toast({ approve: "Approved", deny: "Denied", revoke: "Access revoked" }[action]); load(); draw() } catch (e) { fail(e) }
  };
  const draw = () => api("/api/access").then(d => box.replaceChildren(
    el("section", { class: "panel" }, el("h2", {}, `Access requests (${d.pending.length})`),
      d.pending.length ? el("table", {}, el("tr", {}, ["User", "Message", "Requested", ""].map(h => el("th", {}, h))),
        d.pending.map(u => el("tr", {}, el("td", {}, el("b", {}, u.name || u.username || u.email), el("div", { class: "muted" }, u.email)),
          el("td", {}, u.message || el("span", { class: "muted" }, "—")), el("td", { class: "mono" }, u.requested),
          el("td", {}, el("span", { class: "row" }, el("button", { class: "btn small verified", onclick() { act("approve", u) } }, "Approve"),
            el("button", { class: "btn small danger", onclick() { act("deny", u) } }, "Deny"))))))
        : el("p", { class: "muted" }, "No pending requests.")),
    el("section", { class: "panel" }, el("h2", {}, `Using your keys (${d.approved.length})`),
      el("p", { class: "muted" }, "Approved users' searches and resume AI use your SerpApi and Groq keys when they haven't saved their own. Their usage counts against your SerpApi monthly limit."),
      d.approved.length ? el("table", {}, el("tr", {}, ["User", "Approved", "By", "Last search", ""].map(h => el("th", {}, h))),
        d.approved.map(u => el("tr", {}, el("td", {}, u.email), el("td", { class: "mono" }, u.decided), el("td", {}, u.decided_by), el("td", { class: "mono" }, u.last_search || "—"),
          el("td", {}, el("button", { class: "btn small danger", onclick() { act("revoke", u) } }, "Revoke")))))
        : el("p", { class: "muted" }, "Nobody yet.")),
    el("section", { class: "panel" }, el("h2", {}, `All users (${d.users.length})`),
      el("table", {}, el("tr", {}, ["Email", "Username", "Role", "Created", "Last search", "Key access"].map(h => el("th", {}, h))),
        d.users.map(u => el("tr", {}, el("td", {}, u.email), el("td", {}, u.username || "—"), el("td", {}, u.role), el("td", { class: "mono" }, u.created),
          el("td", { class: "mono" }, u.last_search || "—"), el("td", {}, el("span", { class: "tag" + (u.access === "approved" || u.role === "admin" ? " ok" : u.access === "pending" ? " warn" : "") }, u.role === "admin" ? "admin" : u.access))))),
      el("p", { class: "muted" }, "Create accounts or reset passwords with manage.py (see README).")))).catch(e => box.replaceChildren(el("p", { class: "notice bad" }, e.message)));
  draw();
  return [el("div", { class: "head" }, el("div", {}, el("h1", {}, "Admin"), el("div", { class: "sub" }, "Approve who may use your API keys."))), box];
}

// ---------- render ----------
function render() {
  renderNav();
  if (!S.data) return;
  const v = { dashboard: viewDashboard, find: viewFind, saved: viewSaved, apps: viewApps, follow: viewFollow, resume: viewResume, analytics: viewAnalytics, settings: viewSettings, archive: viewArchive, admin: viewAdmin }[S.view] || viewDashboard;
  $("#main").replaceChildren(...v());
  if ($("#list")) renderList();
}
S.view = (location.hash || "#dashboard").slice(1);
if (!VIEWS.some(([k]) => k === S.view)) S.view = "dashboard";
if (store.get("session", sessionStorage)) { $("#app").hidden = false; load() } else showGate();
