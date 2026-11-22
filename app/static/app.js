// Plain JS, no frameworks. All text is inserted with textContent (never innerHTML) so fetched or typed text cannot run as code.
// The page decides nothing: it shows what the server returns and sends a person's Approve or Reject.
"use strict";
const $ = (id) => document.getElementById(id);
const el = (tag, attrs = {}, ...kids) => {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) { if (k === "class") e.className = v; else e.setAttribute(k, v); }
  for (const k of kids) if (k !== null && k !== undefined) e.append(typeof k === "string" ? document.createTextNode(k) : k);
  return e;
};
const CONTROL_LABELS = {
  strictness: { lenient: "Lenient", balanced: "Balanced", strict: "Strict" },
  rejection_evidence: { standard: "Standard", high: "High (2 sources)" },
  freshness_days: { policy: "Policy default (60)", "30": "30", "90": "90", "180": "180" },
};
const STEPS = [["parse", "Reading the request"], ["exists", "Company exists"], ["active", "Company is active"],
               ["director", "Claimed director"], ["adverse", "Adverse media"], ["memo", "Writing the memo"]];
let STATUS = null;

async function api(path, opts = {}) {
  let r;
  try { r = await fetch(path, { credentials: "same-origin", headers: { "content-type": "application/json" }, ...opts }); }
  catch (e) { throw new Error("Can't reach the server. Is it still running?"); }
  const body = await r.json().catch(() => ({}));
  if (r.status === 401 && path !== "/api/login") { showLogin(); throw new Error("Please sign in"); }
  if (!r.ok) { const e = new Error(body.error || `Server error (HTTP ${r.status})`); e.status = r.status; throw e; }
  return body;
}

function showLogin() { $("login").hidden = false; $("main").hidden = true; }

$("login-form").addEventListener("submit", async (ev) => {
  ev.preventDefault(); $("login-error").textContent = "";
  try { await api("/api/login", { method: "POST", body: JSON.stringify({ password: $("pw").value }) }); $("pw").value = ""; await start(); }
  catch (e) {
    $("login-error").textContent = e.status === 401 ? "That password is not right. Ask the person who runs the server for it."
      : e.status === 429 ? "Too many wrong attempts. Wait a minute and try again." : e.message;
    $("pw").focus();
  }
});

const mode = () => document.querySelector('input[name="mode"]:checked').value;

function badges() {
  const st = STATUS, c = st.caps, b = $("badges"); b.replaceChildren();
  b.append(el("span", { class: "badge" }, mode() === "demo" ? "Demo mode: no cost" : "Live data"),
           el("span", { class: "badge" }, `Model: ${st.model[mode()]}`));
  if (mode() === "live") b.append(el("span", { class: "badge" }, `Session: ${c.session_spent} of ${c.credits_per_session} credits`));
  $("demo-banner").hidden = mode() !== "demo";
  $("demo-banner").textContent = st.modes.demo.label || "";
  const li = $("live-info");
  if (mode() === "live") {
    li.hidden = false;
    li.textContent = `Live: each run is capped at ${c.credits_per_run} credits and ${c.seconds_per_run} seconds; ` +
      `this session can spend ${c.credits_per_session} credits in all (${c.session_spent} used). You will be asked to confirm before credits are spent.`;
  } else li.hidden = true;
}

async function start() {
  STATUS = await api("/api/status");
  $("login").hidden = true; $("main").hidden = false;
  const live = STATUS.modes.live;
  $("mode-live").disabled = !live.available;
  if (!live.available) $("mode-live").parentElement.title = live.reason;
  $("mode-live").parentElement.append(live.available ? "" : el("small", { class: "note" }, ` (off: ${live.reason})`));
  if (STATUS.default_mode === "live" && live.available) $("mode-live").checked = true;
  for (const [k, o] of Object.entries(STATUS.controls)) {
    const s = $(k); s.replaceChildren();
    for (const c of o.choices) { const opt = el("option", { value: c }, (CONTROL_LABELS[k] || {})[c] || c); if (c === o.default) opt.selected = true; s.append(opt); }
  }
  $("control-notes").textContent = STATUS.control_notes.join(" · ");
  badges();
  await loadRuns();
}
document.querySelectorAll('input[name="mode"]').forEach((r) => r.addEventListener("change", badges));

async function loadRuns() {
  const { runs } = await api("/api/runs");
  const tb = $("runs").querySelector("tbody"); tb.replaceChildren();
  if (!runs.length) tb.append(el("tr", {}, el("td", { colspan: "6", class: "note" }, "No runs yet.")));
  for (const r of runs) {
    const tr = el("tr", { tabindex: "0" }, el("td", {}, r.started.replace("T", " ").replace("+00:00", "")), el("td", {}, r.mode),
                  el("td", {}, r.vendor_name || ""), el("td", {}, r.overall || ""), el("td", {}, r.action || "none"), el("td", {}, String(r.credits)));
    const open = async () => {
      try { const j = await api(`/api/run/${encodeURIComponent(r.run_id)}?mode=${r.mode}`); $("progress").hidden = true; render(j.card); }
      catch (e) { showError(e.message); }
    };
    tr.addEventListener("click", open); tr.addEventListener("keydown", (e) => { if (e.key === "Enter") open(); });
    tb.append(tr);
  }
}

function showError(msg) { const box = $("result"); box.hidden = false; box.replaceChildren(el("p", { class: "error", role: "alert" }, msg)); }
function list(items) { return el("ul", {}, ...items.map((t) => el("li", {}, t))); }
const isUrl = (s) => /^https?:\/\//i.test(s);
const sourceNode = (s) => isUrl(s) ? el("a", { href: s, target: "_blank", rel: "noopener noreferrer" }, s) : el("code", {}, s);

function renderProgress(job) {
  const box = $("progress"); box.hidden = false; box.replaceChildren();
  const head = job.status === "queued" ? `Queued (position ${job.position}): one run at a time.` :
               job.status === "running" ? "Running checks…" : "Finished.";
  box.append(el("h2", {}, head));
  const ul = el("ul", { class: "steps" });
  for (const [k, label] of STEPS) {
    const st = (job.progress || {})[k] || "waiting";
    ul.append(el("li", { class: `step s-${st.replace(/[^a-z]/g, "")}` }, el("span", { class: "dot" }), `${label}: ${st}`));
  }
  box.append(ul);
}

function verdictState(s) {
  const t = (s || "").toLowerCase();
  if (/clear|onboard|\bpass/.test(t)) return "pass";
  if (/reject|fail/.test(t)) return "fail";
  if (/hold|held|suspicious|review|approval/.test(t)) return "warn";
  return "unknown";                                  // Cannot verify / in progress
}

function render(r) {
  const box = $("result"); box.hidden = false; box.replaceChildren();
  box.append(el("p", { class: `verdict v-${verdictState(r.overall)}` }, r.overall || "In progress"));
  if (r.demo_label) box.append(el("p", { class: "note" }, "DEMO: replayed fixtures, not a live check."));
  for (const n of r.notices || []) box.append(el("p", { class: "notice", role: "status" }, n));
  const chips = el("div", { class: "chips" });
  for (const c of r.checks || []) chips.append(el("div", { class: `chip st-${c.label.split(/[^A-Za-z]/)[0]}` }, `${c.title}: ${c.label}`));
  box.append(chips);
  if (r.memo) box.append(el("h3", {}, `Memo (${r.memo_writer})`), el("pre", { class: "memo" }, r.memo));
  box.append(el("h3", {}, "Reasons and sources"));
  const reasons = el("ul", {});
  for (const c of r.checks || []) {
    const li = el("li", {}, el("strong", {}, `${c.title}: `), c.reason || "no reason given");
    const srcs = el("div", { class: "src" });
    if (c.sources.length) c.sources.forEach((s, i) => { if (i) srcs.append(" · "); srcs.append(sourceNode(s)); });
    else srcs.append("no source record");
    srcs.append(` (record date ${c.record_date}; retrieved ${c.retrieved || "not recorded"})`);
    li.append(srcs); reasons.append(li);
  }
  box.append(reasons);
  box.append(el("h3", {}, "What is missing"), (r.missing || []).length ? list(r.missing) : el("p", { class: "note" }, "Nothing missing."));
  box.append(el("p", { class: "note" }, `Spent: ${r.credits} credits` + (r.seconds != null ? `, ${r.seconds} s for the checks` : "") +
    (r.total_seconds != null ? `, ${r.total_seconds} s in all` : "") + `. Run ${r.run_id} (${r.mode}).`));
  if ((r.control_notes || []).length) box.append(el("p", { class: "note" }, r.control_notes.join(" · ")));
  if (r.action) box.append(el("h3", {}, "Your approval"), approvalRow(r));
}

function approvalRow(r) {
  const row = el("div", { class: "actions" });
  if (r.action.status !== "pending") { row.append(el("strong", {}, `Decision: ${r.action.status}`)); return row; }
  const what = r.action.kind === "onboard_vendor" ? "clear (onboard) this vendor" : "reject this vendor";
  row.append(el("span", {}, `The checks recommend that you ${what}. Nothing happens until a person decides.`));
  for (const [choice, label, cls] of [["approve", "Approve", "approve"], ["reject", "Reject", "reject"]]) {
    const b = el("button", { class: cls, type: "button" }, label);
    b.addEventListener("click", () => {
      row.replaceChildren(el("span", {}, `${label}: are you sure? This is recorded and cannot be undone.`));
      const yes = el("button", { class: cls, type: "button" }, `Yes, ${label.toLowerCase()}`);
      const no = el("button", { class: "secondary", type: "button" }, "Cancel");
      no.addEventListener("click", () => row.replaceWith(approvalRow(r)));
      yes.addEventListener("click", async () => {
        yes.disabled = no.disabled = true;
        try {
          const out = await api(`/api/action/${encodeURIComponent(r.action.key)}/${choice}?mode=${r.mode}`, { method: "POST" });
          r.action.status = out.status;
          row.replaceChildren(el("strong", {}, `Decision: ${out.status}. ${out.note}`)); loadRuns();
        } catch (e) { row.append(el("span", { class: "error" }, e.message)); }
      });
      row.append(yes, no);
    });
    row.append(b);
  }
  return row;
}

const sleep = (ms) => new Promise((res) => setTimeout(res, ms));

async function follow(job) {
  renderProgress(job);
  while (job.status === "queued" || job.status === "running") {
    await sleep(700);
    job = await api(`/api/run/${encodeURIComponent(job.job_id)}`);
    renderProgress(job);
  }
  if (job.note) $("progress").append(el("p", { class: "notice" }, job.note));
  if (job.status === "needs_input") {
    const box = $("result"); box.hidden = false;
    box.replaceChildren(el("h2", {}, "I need a little more before I can run this"), list(job.questions || []),
      el("p", { class: "note" }, "Add the missing detail to the description and press Run again."));
  } else if (job.status === "error") showError(job.error);
  else if (job.card) render(job.card);
  if (STATUS && job.mode === "live") { STATUS = await api("/api/status"); badges(); }
  loadRuns();
}

async function submit(confirmSpend) {
  const ctl = { strictness: $("strictness").value, rejection_evidence: $("rejection_evidence").value, freshness_days: $("freshness_days").value };
  $("run-btn").disabled = true; $("result").hidden = true;
  try {
    const job = await api("/api/ask", { method: "POST", body: JSON.stringify({ text: $("text").value, controls: ctl, mode: mode(), confirm_spend: confirmSpend }) });
    await follow(job);
  } catch (e) { $("progress").hidden = true; showError(e.message); }
  finally { $("run-btn").disabled = false; }
}

$("run-form").addEventListener("submit", (ev) => {
  ev.preventDefault();
  if (mode() !== "live") return submit(false);
  const c = STATUS.caps;
  $("confirm-text").textContent = `This live run calls Crustdata and spends real credits: up to ${c.credits_per_run} credits and ` +
    `${c.seconds_per_run} seconds. This session has used ${c.session_spent} of ${c.credits_per_session}. Go ahead?`;
  $("confirm").hidden = false; $("run-btn").disabled = true;
});
$("confirm-yes").addEventListener("click", () => { $("confirm").hidden = true; submit(true); });
$("confirm-no").addEventListener("click", () => { $("confirm").hidden = true; $("run-btn").disabled = false; });

start().catch((e) => { if (e.message !== "Please sign in") { $("main").hidden = false; showError(e.message); } });
