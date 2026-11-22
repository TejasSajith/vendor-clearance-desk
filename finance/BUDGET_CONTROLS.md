# Budget controls

Four ceilings, one ledger, one alert. Values marked PROPOSED are not decided (`DECISIONS.md`).

## 1. The caps

| Cap | Value | Where defined | Enforced by | What happens when it is hit |
|---|---|---|---|---|
| Credits per run | 50 (PROPOSED, D13) | `config.json max_cost_credits_per_run` | `core.tracked_call`, before every external call | `core.LimitExceeded`; the stage and every later stage become `not_run`; the verdict is CANNOT_VERIFY naming the checks not run and the spend; no action is created; run status `stopped_at_cap` |
| Seconds per run | 300 (PROPOSED, D13) | `config.json max_seconds_per_run` | `core.tracked_call`, before every external call | Same as above |
| Credits per UI session | 100 (PROPOSED, D39) | `config.json session_credit_cap` | `app/server.py` | A run starts only if the session's spend plus the full per-run cap still fits; otherwise HTTP 402 with the amounts |
| Credits per day | 100 (PROPOSED, D50) | `ops_config.json max_cost_credits_per_day` | `clearance/guard.py Guard.call`, before every paid (non-cached) call | `core.LimitExceeded("daily cap: ...")`, handled exactly like the per-run cap |

Details that matter:
- **Overshoot is bounded by one call.** The per-run check compares the spend so far with the cap (a call may start while the spend is not above it), so a run can end above its cap by at most the cost of its last call. The largest call in a vendor run in the ledger is 2 credits, so the worst case is 52 credits per vendor (`finance/UNIT_ECONOMICS.md` section 6). The daily cap refuses a call once the day's total has reached the cap.
- **The daily cap counts the whole database.** It sums `calls.credits` since midnight (the machine's local time) across all runs in that SQLite file. The web UI in demo mode uses its own `demo.db`, so it has its own day count (and spends 0 credits).
- **The daily cap applies through the guard.** Runs made with `python -m clearance run` or through `clearance.service` go through `GuardedSources`. Runs made directly with `pipeline.py run` or the web UI (`app/server.py`) are bound by the per-run, time and session caps but not by the daily cap, because those files belong to other work in progress and were not changed here.
- **Cached responses are free and never refused.** A cache hit has no ledger row and no credits, so the daily cap does not block it.
- **Model calls** are ledgered with 0 credits and their token counts (`llm.extract`), so they count toward the run's time cap but not its credit caps.

## 2. The ledger

Every external call goes through `core.cached_call` -> `core.tracked_call`, which writes one row to `calls`: run id, endpoint, params (a redacted hash for person-data calls), status (`ok` or `error`), credits (from the API's `x-credits-used` header), milliseconds (including throttle waits and retries), timestamp. The row is written in a `finally` block, so a failed call is logged too.

Reading it:
- `python finance/cost_report.py DB ...` gives per-vendor credits and seconds by endpoint, mean, median, p90, model calls, cache savings, and credits spent by runs stopped at a cap.
- `python finance/cost_report.py DB --balance-before N --balance-after M` compares the account's balance change with the ledger total and records the result in the `reconciliations` table; `python -m clearance doctor` shows the latest one. A difference means a call was charged without a ledger row (for example a process killed during an HTTP request; see `docs/ARCHITECTURE_TECHNICAL.md` section 3).

## 3. The alert when a run hits a cap

`clearance/guard.py` catches `core.LimitExceeded` on its way out of a call, writes one row per run and kind to the `alerts` table (`run_cost_cap`, `run_time_cap` or `daily_cap`, with the message and the run's spend), prints `ALERT [kind] run <id>: ...` to stderr, and re-raises so the pipeline stops the run cleanly. The alert is local: it is not emailed or sent anywhere (no outbound messages, by design). `python -m clearance doctor` lists the most recent alerts.

Tests: `tests/test_daily_cap.py` (daily cap stops new paid calls, counts only today, alerts once per run and kind; per-run and time cap alerts), `tests/test_cap_midrun.py` (per-run and time caps stop cleanly and the ledger reconciles), `tests/test_cost_report.py` (report figures equal the ledger; reconciliation).
