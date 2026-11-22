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

## Architecture

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
