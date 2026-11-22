# handover.md: for teammates' AI agents
You are joining a hackathon build in progress. Read `AGENTS.md` first (rules), then `DECISIONS.md`, `plan.md`, `probe/REPORT.md`. **Tejas decides every large design and parameter choice; log a PROPOSED entry and ask.**

## The project
ContextCon 05 (BITS Pilani, with Crustdata), theme "Services, Replaced", track **Trust and compliance**. We build an agent service that clears a new carrier or supplier for a mid-size Indian 3PL: it checks the vendor exists, is active, is run by the claimed director, and has no adverse media, then returns a sourced recommendation held for a person's approval. Code freeze 6:00 PM; demo video 5:30 PM.

## What exists
- `core.py`: SQLite state, `run_step` (resume), `add_fact` (refuses unsourced facts), `tracked_call`, `cached_call` (throttle plus cache plus ledger), `propose_action` / `set_approval` / `execute_action` (exactly once), `finalize`.
- `decision.py`: four verdicts from check results; unreachable gives `HOLD_FOR_APPROVAL`; a rejection needs sources.
- `policy.py`: signals to checks using `PROPOSED_PARAMS` (not final).
- `evaluation/`: `run_eval.py` (metrics, `--compare` report-only, `--sweep`), synthetic cases.
- `tests/`: run `python -m pytest -q`.

## What to build (see plan.md)
Check modules in `checks/` that turn raw live data into the signals `policy.py` expects; the pipeline and CLI; chaos tests; real eval fixtures; ethics and cost reporting; README and diagram.

## Crustdata facts (from the probe)
Base `https://api.crustdata.com`, headers `authorization: Bearer $CRUSTDATA_API_KEY`, `x-api-version: 2025-11-01`. **Account limits: company, person and job 5/min; web 10/min.** Balance: `GET /account/credits` (free).
- Identify (0.2/match): name search returns up to 25 candidates; ties at confidence 1.0 happen; the score is not an auto-accept signal. A domain can resolve to a different company. `basic_info.status` is `active` or `deleted`.
- Company Enrich (2): `headcount.total`, `headcount.timeseries[]` (dated), `people.cxos/founders`, `web_traffic`, `locations`. No registry IDs (CIN, GSTIN, DIN) and no company-level refresh date. Revenue is useless.
- Job Search (0.03/row): `metadata.date_added`; `total_count` gives the count. Small firms show none, so no jobs does not mean inactive.
- Person Enrich (1): `experience.employment_details.current[]` with title, `start_date`, `crustdata_company_id` (machine-checkable link). "Current" roles can be stale. Not a director of record.
- Web Search (1) and Fetch (1): result URLs are often `google.com/goto?url=...`: decode `url=` and fetch the target. No date field; dates only sometimes in snippets. Snippets are not verified passages.
Raw responses are gitignored. Probe findings are summarised in `probe/REPORT.md`; the report omits person names on purpose.

## How to work
1. Pick a task from `plan.md`; if it needs a **[D#]**, check `DECISIONS.md`. If PROPOSED, ask Tejas and work on something else.
2. Use `cached_call` for every external call, `add_fact` for every fact.
3. Write tests; run `python -m pytest -q`; commit small with the prefixes in AGENTS.md; push.
4. Report back: what changed, tests, credits spent, decisions needed.

## Do not
Commit keys, raw data or personal data; read a timeout as "nothing found"; reject or clear without the approval queue; use model memory as a source; contact anyone outside the team; change a parameter default or verdict meaning without a DECIDED entry.
