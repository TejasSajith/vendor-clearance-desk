# progress.md: state of the project as of Sun 22 Nov 2026, 13:45 IST

For a teammate's AI agent joining mid-build. Read this first, then `AGENTS.md` (rules), `DECISIONS.md`, `plan.md`, `docs/handover.md`, `probe/REPORT.md`. **Tejas is the owner and makes every large design decision and every parameter or threshold value.** Where this file says PROPOSED, nothing has been decided: ask Tejas, do not build on it.

## 1. The event
ContextCon 05 at BITS Pilani, run with Crustdata (YC F24). Theme "Services, Replaced": build an agent service that does a whole paid job from request to result. Build window starts 10:45 AM (one document says 10:15 AM; confirm with organisers, D17). Requirement change from the organisers expected at hour 3 (about 1:45 PM). Code freeze 6:00 PM. Demo video (2 minutes, one link) by 5:30 PM. Submission once early as a safety net, then final.

Two event documents exist and disagree in places (D17). The handbook scores five criteria (end-to-end 25, facts 20, robustness 20, customer value 20, demo 15); the problem-statement PDF describes a hidden test set, screening, a kill-on-stage, a live fix and finals scored on live run 20, robustness 15, design 15, ethics 25, financial feasibility 25. We design to satisfy both. No kickoff kit (client records, hidden tests) was received; we define our own scenario and tests. A message to the organisers was suggested to confirm.

Event rules that bind us (full list in `AGENTS.md`): build today; live data for at least one decision; every fact has a source link to the exact passage or field plus the record date, model memory is never a source; say `CANNOT_VERIFY` and name what is missing when nothing settles a question (a wrong answer costs more than abstaining); a person approves anything irreversible (sending, paying, ordering, rejecting); a time and credit limit per run with every call ledgered, model calls included; crash-safe and exactly-once after a restart; a timed-out source is retried or held, never read as "nothing found"; agents talk only to the team and organisers; keep notes of approaches tried.

## 2. What Tejas has decided
- **Track:** Trust and compliance only. Supply chain (sourcing manufacturers) and Research and markets were considered and dropped.
- **Storage:** SQLite.
- **Scenario and interface (accepted):** a mid-size Indian 3PL clears new carriers and suppliers. Input `{vendor_name, website, claimed_director, risk_tier, optional registry IDs}`. Output a recommendation (`CLEARED`, `REJECTED`, `CANNOT_VERIFY`, `HOLD_FOR_APPROVAL`) with sourced reasons, missing evidence and cost, held for a person's approval.
- **Process:** Tejas makes every large design and parameter decision; agents propose in `DECISIONS.md` and stop. New rules run in report-only mode before they become defaults. Commit in small steps at logical points.
- **Go-ahead** on the plan, the probe-driven approach, the evaluation harness and the repo docs.

## 3. Proposed but NOT decided (see `DECISIONS.md`, D1 to D18)
Team roster and roles (D1); whether `CLEARED` also needs approval (D2, proposed yes); how to treat `status=deleted` (D3) and a domain that resolves to another company (D4), both proposed "unknown"; thresholds `name_sim_min` 0.90, `active_min_signals` 2 (+1 for high risk), min headcount 5, max decline 30%, series age 60 days, jobs window 90 days, adverse severity minimum 2 of 3 (D5 to D8); registry source (D9) and news source (D10), pending a probe; error-cost weights 3 / 1 / 0.5 (D11); risk-tier scheme (D12); model per step and run limits (D13); approval interface, CLI first (D14); stretch features (D15); credits to rupees and price per check (D16); which event document governs (D17); Crustdata MCP for exploration only, never inside the service (D18).

## 4. Design as it stands
Deterministic rules decide the verdict (`policy.py`, `decision.py`); the LLM only extracts, disambiguates and explains. Four checks: exists, active, director match, adverse media. Every check result is one of pass, fail, unknown, or unreachable. A rejection needs sources, otherwise it is only unknown. Verdicts are recommendations: `CLEARED` and `REJECTED` become pending actions in an approval queue; `CANNOT_VERIFY` and `HOLD_FOR_APPROVAL` go to a person as they are. For every `CANNOT_VERIFY` the service names the missing evidence and drafts a document request held for approval ("what would settle it"). Facts are quote-grounded (the passage must appear in the fetched page) and fetched pages are treated as data, never as instructions.

## 5. What the Crustdata probe found (run by Tejas, 10 Indian logistics companies, 85 calls, 61 credits)
- **Account limits are tighter than the handbook:** company, person and job 5 per minute, web 10 per minute.
- **Identify:** top match correct 9 of 10 by name, but ties at confidence 1.0 are common and one domain resolved to a different company; the score is not an auto-accept signal. `basic_info.status` is `active` or `deleted`.
- **Company Enrich:** name, domain (8/10), HQ (messy), founding year, status, headcount now and a dated history (10/10), funding (4/10), leadership (6/10), web traffic (5/10). No registry IDs (CIN, GSTIN, DIN) at all, no company-level refresh date.
- **Jobs:** useful for large firms only; small firms show none, so "no jobs" does not mean inactive.
- **Director:** Person Enrich gives title, start date and a `crustdata_company_id` link (6/6), but "current" roles can be stale and it is not a director of record. Same-name people are told apart by person ID, company ID, title, start date, location.
- **Adverse media:** weak as shipped. Result URLs are mostly `google.com/goto?url=...` redirects (decode `url=` and fetch the target), most fetches were blocked, 28 of 41 snippets had no date, relevance poor, no court or FIR data.
- **Verdict:** all four checks are only "partial" from Crustdata alone. Expect many real vendors to land on `CANNOT_VERIFY`; the product's value is naming what is missing and drafting the request for it.

## 6. What exists in the code (delivered as `repo_docs_and_eval.zip`, `clearance_core.zip`; 14 tests pass)
- `core.py`: SQLite state, `run_step` (resume), `add_fact` (refuses unsourced facts), `tracked_call`, `cached_call` (per-endpoint throttle, response cache, limit check, ledger), `propose_action` / `set_approval` / `execute_action` (exactly once), `finalize`.
- `decision.py`: verdicts from check results; unreachable gives `HOLD_FOR_APPROVAL`.
- `policy.py`: raw signals to check results using `PROPOSED_PARAMS`.
- `evaluation/run_eval.py`: metrics, `--compare` (report-only), `--sweep`; 19 synthetic cases. The synthetic cases pass 19/19 only because the labels were written to match the rules, so they test logic, not whether the thresholds are right. Real fixtures from `probe/raw/` are needed before tuning means anything.
- Docs: `AGENTS.md`, `CLAUDE.md`, `DECISIONS.md`, `plan.md`, `docs/handover.md`.

## 7. Status and next steps
Not yet reported back by Tejas: placing the files in the GitHub repo and the first commits; the real-fixtures task; the registry and news probe. The checks modules (`checks/exists.py`, `active.py`, `director.py`, `adverse.py`), the pipeline and CLI, chaos tests, the ethics layer, the finance numbers, README and diagram are all still to build. Order and commit points are in `plan.md`. Do not start a task that depends on a PROPOSED decision.

## 8. Working with Tejas
He directs Claude Code from a chat, writes decisions himself, has not learned JavaScript or TypeScript, so keep the stack Python and CLI-first and explain code in plain terms. He wants a short report after each task: what changed, tests run, credits spent, and any decision needed. He previously shipped a mobile app the same way, with an `AGENTS.md` as the authority and "report-only before enforcing" as a habit.
