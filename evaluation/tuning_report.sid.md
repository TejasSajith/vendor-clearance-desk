# Tuning report — autonomous collection run (SiD, parallel)

Agent-run live data collection for policy tuning. **No labels are written here** (Tejas labels blind).
Every small decision the agent took is logged below with its reason. The agent never wrote to
`policy.py` or `config.json`, never wrote an `expected_*` label, and wrote no person names to any file.

Started 2026-11-22. Budgets (this run): **600-credit sub-budget** (see T7), 45 min wall clock for live
collection, then offline work.

## Context: this is a second, parallel collection by design

While starting, the agent found that the repo owner **Tejas** had, ~2 minutes earlier (commit `b61bbd1`,
17:37 IST, with Claude Sonnet 5.5), pushed the **same** task to `main`: `evaluation/collect_signals.py`
(phase-1 collector, 4 adverse searches, 12-row stability), a 66-row `evaluation/cases_real.csv`, plus
`config.json`/`core.py`/`checks` edits and new `llm.py`/`nl.py`. That run targets the same 1500-credit cap
on the same shared Crustdata account. The user was shown this and chose **"run in parallel anyway"** with a
separate sub-budget and separate output files. This report and the files below are that independent run.

To avoid clobbering the parallel run, this run writes only namespaced files and uses its own ledger:
`evaluation/signals_real.sid.json`, `evaluation/stability_real.sid.json`, `evaluation/tuning_progress.sid.md`,
`evaluation/collect_real_sid.py`, and `probe/live/tuning_sid.db` (gitignored).

## Decisions log

| # | Decision | Choice | Reason |
|---|---|---|---|
| T1 | Force UTF-8 for tests | Run pytest with `PYTHONUTF8=1` (env only, no code change) | A pre-existing test reads a fixture with `read_text()` and no encoding; Windows cp1252 fails. UTF-8 mode fixes it without editing shipped code. 107/107 pass. |
| T2 | Reconcile the duplicate `cases_real.csv` | Adopt Tejas's committed `evaluation/cases_real.csv`; drop my own duplicate builder/CSV | PHASE 0 says "if it does not exist, create it" — it now exists on `main`. Running both collectors against the **same** rows makes the two signal sets directly comparable, and avoids a second, conflicting case file. |
| T3 | Namespaced outputs + own DB | `*.sid.json`, `tuning_progress.sid.md`, `probe/live/tuning_sid.db` | The user chose a parallel run; namespacing means my files never overwrite Tejas's `signals_real.json`/`collect_signals.py`/`tuning_progress.md`, and a separate SQLite ledger keeps the two cost/throttle ledgers independent. |
| T4 | No `claimed_director` anywhere | Director check is always "not_requested"; `/person/search` is never called | Rule: no person names in any file, and collect only what a check needs. With no claimed director there is zero person data to store or purge. |
| T5 | `expected_*` labels | Left exactly as Tejas shipped them (blank) | Rule: never write labels. |
| T6 | Four distinct adverse searches | web: `fraud/scam/default/FIR/blacklisted`; web: `FIR/arrested/police complaint/chargesheet`; news: `insolvency/NCLT/bankruptcy/default/struck off`; news: `blacklisted/banned/penalty/scam` | Four non-overlapping angles (general, criminal, financial-distress, regulatory) widen discovery while staying name-scoped via `checks/adverse.build_hits` (full-name phrase or supplied domain only). |
| T7 | Credit sub-budget | **600 credits** hard cap for this run (of the 1500 account cap) | The parallel run already uses the account toward 1500; carving a 600 sub-budget leaves Tejas the bulk and keeps the worst-case shared spend bounded. A full pass + 12-row stability is estimated ~470 credits, so 600 has headroom without risking the shared account. |
| T8 | Resume / exactly-once | Fresh `run_id` per (row, process); skip rows already terminal (`done`/`no_record`/`ambiguous`) in the output; rely on `core.cached_call`'s global response cache so a paid call is never repeated across restarts | A fresh per-vendor `run_id` gives each vendor a fresh 300 s per-run window (so a resume is not killed instantly by a stale `started`), while the global cache (keyed on endpoint+params) guarantees previously-succeeded paid calls return from cache and are not billed again. |
| T9 | Stability: force a real re-fetch through `cached_call` | Each repeat passes a `_repeat` marker in the **logged** params only (the marker is not sent to the API) | Keeps every call going through `core.cached_call` (the rule) while giving each repeat its own cache key, so repeats are genuine paid re-fetches rather than cache hits — the only way to actually measure hit/date stability. |
| T10 | A timed-out adverse search | The whole adverse stage becomes `unreachable` (row state `unreachable`), never an empty "nothing found" | Rule: a timeout is never read as an answer. `checks/live` raises `RateLimited`/`TransientError`; after retries `core` raises `SourceUnreachable`, which the collector records as unreachable. |
| T11 | Console hygiene | Console/logs print only aggregate counts + credits + elapsed; per-vendor state goes to files only | PHASE 1: the labeller works blind and must not see per-vendor outcomes. |
