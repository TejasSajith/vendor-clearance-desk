// Plain JS, no frameworks. All text is inserted with textContent (never innerHTML) so fetched or typed text cannot run as code.
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

async function api(path, opts = {}) {
  const r = await fetch(path, { credentials: "same-origin", headers: { "content-type": "application/json" }, ...opts });
  const body = await r.json().catch(() => ({}));
  if (r.status === 401 && path !== "/api/login") { showLogin(); throw new Error("Please sign in"); }
  if (!r.ok) throw new Error(body.error || `HTTP ${r.status}`);
  return body;
}

function showLogin() { $("login").hidden = false; $("main").hidden = true; }

$("login-form").addEventListener("submit", async (ev) => {
  ev.preventDefault(); $("login-error").textContent = "";
  try { await api("/api/login", { method: "POST", body: JSON.stringify({ password: $("pw").value }) }); $("pw").value = ""; await start(); }
  catch (e) { $("login-error").textContent = e.message; }
});

function badges(st) {
  const b = $("badges"); b.replaceChildren();
  const c = st.caps;
  b.append(el("span", { class: "badge" }, st.mode === "demo" ? "Demo mode (no cost)" : "Live data"),
           el("span", { class: "badge" }, `Cap: ${c.credits_per_run} credits and ${c.seconds_per_run} s per run`),
           el("span", { class: "badge", id: "session-badge" }, `Session: ${c.session_spent} of ${c.credits_per_session} credits`),
           el("span", { class: "badge" }, `Model: ${st.model}`));
}

async function start() {
  const st = await api("/api/status");
  $("login").hidden = true; $("main").hidden = false;
  badges(st);
  if (st.demo_label) { $("demo-banner").hidden = false; $("demo-banner").textContent = st.demo_label; }
  for (const [k, o] of Object.entries(st.controls)) {
    const s = $(k); s.replaceChildren();
    for (const c of o.choices) { const opt = el("option", { value: c }, (CONTROL_LABELS[k] || {})[c] || c); if (c === o.default) opt.selected = true; s.append(opt); }
  }
  $("control-notes").textContent = st.control_notes.join(" · ");
  await loadRuns();
}

async function loadRuns() {
  const { runs } = await api("/api/runs");
  const tb = $("runs").querySelector("tbody"); tb.replaceChildren();
  if (!runs.length) tb.append(el("tr", {}, el("td", { colspan: "5", class: "note" }, "No runs yet.")));
  for (const r of runs) {
    const tr = el("tr", { tabindex: "0" }, el("td", {}, r.started.replace("T", " ").replace("+00:00", "")), el("td", {}, r.vendor_name || ""),
                  el("td", {}, r.overall || ""), el("td", {}, r.action || "none"), el("td", {}, String(r.credits)));
    const open = async () => { try { render(await api(`/api/runs/${encodeURIComponent(r.run_id)}`)); } catch (e) { showError(e.message); } };
    tr.addEventListener("click", open); tr.addEventListener("keydown", (e) => { if (e.key === "Enter") open(); });
    tb.append(tr);
  }
}

function showError(msg) {
  const box = $("result"); box.hidden = false; box.replaceChildren(el("p", { class: "error" }, msg));
}

function list(items) { return el("ul", {}, ...items.map((t) => el("li", {}, t))); }

function render(r) {
  const box = $("result"); box.hidden = false; box.replaceChildren();
  if (r.status === "needs_input") {
    box.append(el("h2", {}, "I need a little more"), list(r.questions));
    return;
  }
  box.append(el("p", { class: "verdict" }, r.overall || "In progress"));
  if (r.demo_label) box.append(el("p", { class: "note" }, "DEMO: replayed fixtures, not a live check."));
  if (r.existing) box.append(el("p", { class: "note" }, "This vendor was already checked with these settings; showing the existing run."));
  const chips = el("div", { class: "chips" });
  for (const c of r.checks || []) {
    chips.append(el("div", { class: `chip st-${c.label.split(/[^A-Za-z]/)[0]}`, title: c.reason }, `${c.title}: ${c.label}`, el("small", {}, c.reason)));
  }
  box.append(chips);
  if (r.memo) box.append(el("h3", {}, `Memo (${r.memo_writer})`), el("pre", { class: "memo" }, r.memo));
  const src = [];
  for (const c of r.checks || []) for (const s of c.sources) src.push(`${c.title}: ${s} (record date ${c.record_date}; retrieved ${c.retrieved || "not recorded"})`);
  box.append(el("h3", {}, "Sources"), src.length ? list(src) : el("p", { class: "note" }, "No sources."));
  box.append(el("h3", {}, "Missing evidence"), (r.missing || []).length ? list(r.missing) : el("p", { class: "note" }, "Nothing missing."));
  box.append(el("p", { class: "note" }, `Spent: ${r.credits} credits` + (r.seconds != null ? `, checks ${r.seconds} s` : "") + (r.total_seconds != null ? `, total ${r.total_seconds} s` : "") + `. Run ${r.run_id}.`));
  if ((r.control_notes || []).length) box.append(el("p", { class: "note" }, r.control_notes.join(" · ")));
  if (r.action) {
    const row = el("div", { class: "actions" });
    if (r.action.status === "pending") {
      const what = r.action.kind === "onboard_vendor" ? "clearing" : "rejecting";
      row.append(el("strong", {}, `Your approval is needed for ${what} this vendor.`));
      for (const [choice, label, cls] of [["approve", "Approve", "approve"], ["reject", "Reject", "reject"]]) {
        const b = el("button", { class: cls, type: "button" }, label);
        b.addEventListener("click", async () => {
          row.querySelectorAll("button").forEach((x) => (x.disabled = true));
          try { const out = await api(`/api/actions/${encodeURIComponent(r.action.key)}/${choice}`, { method: "POST" });
                row.replaceChildren(el("strong", {}, `Decision recorded: ${out.status}. ${out.note}`)); loadRuns(); }
          catch (e) { row.append(el("span", { class: "error" }, e.message)); }
        });
        row.append(b);
      }
    } else row.append(el("strong", {}, `Approval: ${r.action.status}`));
    box.append(el("h3", {}, "Approval"), row);
  }
}

$("run-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const ctl = { strictness: $("strictness").value, rejection_evidence: $("rejection_evidence").value, freshness_days: $("freshness_days").value };
  $("run-btn").disabled = true; $("running").hidden = false;
  try {
    const r = await api("/api/run", { method: "POST", body: JSON.stringify({ text: $("text").value, controls: ctl }) });
    render(r);
    if (r.session_spent !== undefined) { const st = await api("/api/status"); badges(st); }
    loadRuns();
  } catch (e) { showError(e.message); }
  finally { $("run-btn").disabled = false; $("running").hidden = true; }
});

start().catch(() => showLogin());
