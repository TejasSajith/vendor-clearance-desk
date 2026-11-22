# Vendor Clearance Desk

## The job and who pays

A mid-size Indian 3PL pays compliance and procurement staff or KYC firms to clear new carriers and suppliers before money moves.

## Input

A vendor clearance request: `{vendor_name, website, claimed_director, risk_tier, optional registry IDs}`. Risk tier is `low`, `medium` or `high` (set per request; D12 is still open).

## Finished result and pass mark

A recommendation for one vendor: `CLEARED`, `REJECTED`, `CANNOT_VERIFY` or `HOLD_FOR_APPROVAL`, with the four check results (exists, active, director match, adverse media), reasons that each link to a source record (exact passage or field, plus the record's date), what evidence is missing, and the cost in credits. `CLEARED` and `REJECTED` become pending actions held for a person's approval; nothing is sent or decided automatically.

Pass mark (proposed, Tejas to confirm): no wrong definitive verdict on the labelled cases (a wrong answer counts against us more than `CANNOT_VERIFY`); every claim is sourced or the output says what is missing; a timed-out source is held for a person, never read as clean; a run stays under its time and credit ceiling and resumes after a crash with each action happening once. Measured with `python evaluation/run_eval.py`. The real-vendor labels in `evaluation/cases_real.json` are still empty.

## Data sources

All from Crustdata (`probe/REPORT.md`, `probe/REPORT_registry_news.md`):
- **Company Identify and Enrich:** name, domain, status, founding year, HQ, headcount now and history, funding, leadership, web traffic. No registry IDs (CIN, GSTIN, DIN) and no company-level refresh date.
- **Job Search:** postings in the last 90 days with `metadata.date_added`; useful for large firms only.
- **Person Enrich and Search:** title, start date, employer link by company ID; separates same-name people. It is profile data, not a director of record.
- **Web Search and Fetch:** adverse-media discovery. Weak as shipped: redirect URLs, no dates, namesakes.
- **Open (D9, D10):** a registry source (CIN, directors, filings) and a better news source are not chosen yet.

## How to run

Web UI, demo mode (no cost, replayed fixtures), from the repo root after `pip install -r requirements.txt`:

```
APP_PASSWORD=choose-one uvicorn app.server:create_app --factory --port 8000
```

Then open http://127.0.0.1:8000. For live data add `APP_MODE=live` and `CRUSTDATA_API_KEY`; set `GEMINI_API_KEY` (environment or a gitignored `.env`) for model parsing and memos. Without it, templates are used. CLI: `python pipeline.py run --vendor NAME [--website URL] [--tier low|medium|high]`. Tests: `python -m pytest -q`.

## Architecture

```
English request ──> nl.parse_request ──> pipeline.run_request ──> policy.evaluate ──> decision.decide ──> core.finalize
   (browser)         scrub director/IDs    checks via core.cached_call   signals -> checks      4 verdicts         pending action
                     model: name/domain/tier  (throttle, cache, caps,     (controls.resolve                         (Approve / Reject
                     code validates            ledger, retry)              picks the params)                         by a person)
                                                                                                 │
                                      display.display_result (labels only) <────────────────────┘
                                      nl.write_memo (model rewrites a fact sheet; code verifies, else template)
```

- `core.py`: state, resume, evidence and cost ledger (model calls included, 0 credits), throttle, cache, idempotent actions and approvals.
- `pipeline.py`: one request end to end, resumable and deduplicated; takes an optional parameter set from `controls.py`.
- `policy.py` and `decision.py`: deterministic rules. They alone decide the verdict.
- `llm.py`: model adapter (`gemini` | `none`), 20 s timeout, one retry, cool-down after a failure; every call is ledgered with model and tokens.
- `nl.py`: English in (`parse_request`: director name and registry IDs are scrubbed by code before the model sees the text; values not in the sentence are dropped) and English out (`write_memo`: every figure, source, missing item and the verdict are checked against the decision).
- `display.py`: plain-English labels (Passed, Failed, Suspicious, Can't verify, Couldn't reach the source). Display only.
- `controls.py`: strictness, rejection evidence and freshness dials mapped to tunable parameters; hard rules are never exposed.
- `app/server.py`: FastAPI with one HTML page (`app/static`, plain JS). Password login, per-run and per-session credit caps, approve and reject buttons, past runs. `app/demo.py`: no-cost demo sources.

## Approaches tried (what worked / didn't)

## Limitations

- **Registry gap:** Crustdata has no CIN, GSTIN or director IDs. A vendor with no Crustdata record is `CANNOT_VERIFY`, naming "independent registry evidence (CIN/GSTIN/incorporation certificate)" as missing. It is never a rejection.
- **Adverse media is weak:** result URLs are often redirects, many snippets have no date, and namesakes are common. A rejection needs a dated, resolved, sourced, severe report (`reject_*` parameters, PROPOSED); anything weaker is `CANNOT_VERIFY`.
- **"Director" means listed at the company:** Person Enrich shows a person's own profile data, not a director of record.
- **Timeouts are not answers:** a source that stays unreachable after retries holds the case for a person; it is never read as "nothing found".
- **Caps stop the run:** at the credit or time cap the run stops cleanly, marks the remaining checks `not_run` and returns `CANNOT_VERIFY` listing them and the spend. A failure already found is shown as evidence for a person, not as a rejection.
- **Conflicting sources are not averaged:** when two sources disagree, the check is `unknown` and both sides are named.
- **Duplicates:** the same vendor submitted under different spellings returns the existing run and creates no second approval.
- **Names and domains:** non-Latin names are searched as given (no transliteration); a weak match is `unknown`. A missing website or director makes those checks `unknown`, named as missing.
- **Tuning:** all thresholds are PROPOSED until decided in `DECISIONS.md`; real-vendor labels are still empty, so nothing is tuned on real data yet.
- **The model only translates:** it never sees the claimed director's name or registry IDs, and nothing it returns can change a verdict. A model memo that states a figure, link or verdict not in the decision is replaced by the template memo. If the model API is slow or down, parsing and memos use templates (after one 20 s timeout and retry, then a 120 s cool-down, PROPOSED).
- **Template parsing is narrow:** without the model, the request must name the vendor after a verb ("check", "clear", "verify"...) or as "Vendor: ...". The director is found only in phrases like "director NAME" or "NAME is the director" (capitalised names). When a field is unclear, the UI asks instead of guessing.
- **Record dates:** Crustdata gives no record date for most fields, so sources show "record date not stated by the source" with the retrieval date.
- **Controls:** until presets are approved in `evaluation/presets_candidate.json`, lenient, balanced and strict give the same result, and the screen says so. Freshness choices 30/90/180 replace the 60-day default only when chosen.
- **Demo mode is not live:** it replays recorded identify and web responses where they exist and synthetic signals elsewhere, labelled on screen. It is never a live decision.
- **Web UI security:** one shared password (`APP_PASSWORD`), sessions in memory (a restart logs everyone out and resets session credit counts), no TLS of its own: put it behind HTTPS and set `APP_SECURE_COOKIE=1`. Runs are serialised, one at a time. Approving only records the decision locally; nothing is sent outside the app.
- **Rupee cost:** not shown until credits-to-rupees is decided (D16).
