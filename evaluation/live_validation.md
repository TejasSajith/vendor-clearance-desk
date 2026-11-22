# Live validation: the real pipeline on 10 vendors (22 Nov 2026)

Live Crustdata, every call through `core.cached_call`; no parameter changed; nothing tuned. Raw responses: `probe/raw/live/` (gitignored). Scripts: `probe/live_validation.py`, `checks/live.py`. Results: `probe/live/*.json`.

**Scope limits.** No claimed director was supplied (no person names are used or stored), so the director check is `unknown` for every vendor and **no vendor can reach `CLEARED`**. No run produced an action. Adverse media ran 2 web searches per vendor; hits carry no resolvable URL, so a rejection is impossible by construction here.

## 1. Results (first run)

| Vendor | Verdict | exists | active | director | adverse | Why not a pass (unknown checks) | Missing | Credits | Seconds | Tejas's expected verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| Delhivery (large) | CANNOT_VERIFY | pass | pass | unknown | unknown | adverse_media: 10 possible adverse reports, not enough to reject; rejection needs a dated, resolved report: missing a date; a | director_match, adverse_media, claimed_director (not supplied in the request) | 4.43 | 39.5 |  |
| DTDC Express Limited (large) | CANNOT_VERIFY | pass | pass | unknown | unknown | adverse_media: 7 possible adverse reports, not enough to reject; rejection needs a dated, resolved report: missing a date; a | director_match, adverse_media, claimed_director (not supplied in the request) | 4.43 | 27.3 |  |
| Everest Fleet Pvt. Ltd. (mid) | CANNOT_VERIFY | pass | pass | unknown | unknown | adverse_media: 3 possible adverse reports, not enough to reject; rejection needs a dated, resolved report: missing a date; a | director_match, adverse_media, claimed_director (not supplied in the request) | 3.4 | 44.1 |  |
| ProConnect Supply Chain Solutions Ltd (mid) | CANNOT_VERIFY | pass | pass | unknown | pass |  | director_match, claimed_director (not supplied in the request) | 3.4 | 59.2 |  |
| Xtrans Logistics Pvt Ltd (small) | CANNOT_VERIFY | pass | unknown | unknown | pass | active: only 1 of 2 activity signals | active, director_match, claimed_director (not supplied in the request) | 3.4 | 38.6 |  |
| LorryCare (small) | CANNOT_VERIFY | pass | pass | unknown | pass |  | director_match, claimed_director (not supplied in the request) | 3.4 | 22.2 |  |
| Ecom Express Ltd (lookalike A) | CANNOT_VERIFY | unknown | unknown | unknown | pass | exists: several records tie for this name and the domain does not settle it; active: only 1 of 2 activity signals | exists, active, director_match, claimed_director (not supplied in the request) | 4.4 | 26.1 |  |
| Ecom Express Delivery Center (lookalike B) | CANNOT_VERIFY | pass | unknown | unknown | unknown | active: only 0 of 2 activity signals; adverse_media: 4 possible adverse reports, not enough to reject; rejection needs a dated, resolved report: missing a date; a | active, director_match, adverse_media, claimed_director (not supplied in the request) | 3.2 | 38.8 |  |
| Zentrovia Cargo Solutions Pvt Ltd (invented) | CANNOT_VERIFY | unknown | unknown | unknown | unknown | exists: several records tie for this name and the domain does not settle it; active: only 1 of 2 activity signals; adverse_media: 3 possible adverse reports, not enough to reject; rejection needs a dated, resolved report: missing a date; a | exists, active, director_match, adverse_media, claimed_director (not supplied in the request) | 3.2 | 42.0 |  |
| Future Supply Chain Solutions Limited (wrong domain) | CANNOT_VERIFY | unknown | unknown | unknown | pass | exists: input domain belongs to a different company; active: only 1 of 2 activity signals | exists, active, director_match, claimed_director (not supplied in the request) | 4.2 | 27.2 |  |

First run: 10 runs, 0 actions, 57 paid calls, 37.46 credits.

## 2. Rerun of the same 10 vendors

New credits: **0.0**. Ledger before and after: {'runs': 10, 'actions': 0, 'calls': 57, 'credits': 37.46, 'cache': 57} vs {'runs': 10, 'actions': 0, 'calls': 57, 'credits': 37.46, 'cache': 57}. Verdicts and per-check states identical to the first run: yes. Runs 10 before and after, actions 0 before and after (no duplicates).

## 3. Spelling variants (same vendor, one run)

| Submitted | Run | Existing |
|---|---|---|
| Delhivery Ltd | r_802554c1cb2b | True |
| M/s Delhivery Limited | r_802554c1cb2b | True |
| Delhivery | r_802554c1cb2b | True |
| Xtrans Logistics Ltd | r_1a0867479523 | True |
| M/s Xtrans Logistics Limited | r_1a0867479523 | True |
| Xtrans Logistics | r_1a0867479523 | True |

All three spellings of each vendor resolved to one run (Delhivery `r_802554c1cb2b`, Xtrans `r_1a0867479523`). Runs 10 before and after, credits unchanged (37.46). Actions: 0 (these vendors end as `CANNOT_VERIFY`, so there was nothing to duplicate; the one-action case is covered by `tests/test_pipeline_dedupe.py`).

## 4. Cap of 2 credits (fresh database)

Everest Fleet Pvt. Ltd.: status `stopped_at_cap`, verdict **CANNOT_VERIFY**, no crash. Checks: {'exists': 'pass', 'active': 'not_run', 'director_match': 'unknown', 'adverse_media': 'not_run'}. Spent 2.4 credits in 14.5 s over 3 calls (the enrich call alone is 2.0, so the cap is crossed by one call, then the run stops). Message: "run stopped at its cost or time cap after 2.4 credits, 14.5 s; not run: active, adverse_media". Missing: ['active (not run: cap reached)', 'adverse_media (not run: cap reached)']. Actions: 0.

## 5. Kill after the 2nd call, then restart (fresh database, Xtrans Logistics)

`os._exit(137)` right after the 2nd call returned (exit code 137). Ledger before restart: 2 calls, 0.4 credits, 1 run, 0 actions. After restart: 6 calls, 3.4 credits, 1 run, 0 actions. Repeated paid calls (same endpoint and params logged twice): **0**. The two finished identify calls were replayed from the cache at no cost. Final verdict `CANNOT_VERIFY`, status `done`. Credit zero-rows (jobs, empty news search) are free results, not retries.

## 6. Credits by endpoint (all databases: main, cap, crash)

| Endpoint | Paid calls | Credits |
|---|---|---|
| /company/enrich | 12 | 24.0 |
| /web/search/live | 22 | 15.0 |
| /company/identify | 21 | 4.2 |
| /job/search | 11 | 0.06 |
| **Total** | **66** | **43.26** |

The account balance moved from 15083.65 to 15040.39: 43.26, which matches the ledger exactly. Budget was 60. Per vendor: 3.2 to 4.4 credits (about 2.0 enrich, 0.2 to 0.4 identify, 0 to 2.0 web search; searches with no results cost 0).

## 7. Surprises (verdicts are not wrong, but the reasons and spend are)

1. **The invented vendor never hit the "not found" path.** Identify has no "no match": for "Zentrovia Cargo Solutions Pvt Ltd" it returned 25 fuzzy candidates, all at 0.6 (an unrelated "Active Cargo Solutions" first). The pipeline took the first one, spent 2.2 credits enriching it, and reported `exists: several records tie for this name`. So the FIX 2 message ("No record found... independent registry evidence") did not fire, and the `active` signals describe an unrelated company. The verdict is still `CANNOT_VERIFY` (safe), but the reason is misleading and the credits were wasted. A low-score or low-similarity floor would be needed to treat this as "no record" (a threshold decision for you; nothing tuned).
2. **Invented-vendor adverse "hits" are look-alike scam-checker pages** ("zentroviaco.com", "zentrovian.de"...). The target-name test is a substring match on the first word, so a different domain that starts with the same letters counts as naming the target. It stays `unknown` (never a rejection), but the hits are noise.
3. **"Ecom Express Ltd" resolved to the wrong record.** Identify ranked "Ecom Express Pvt Ltd" and two others at 0.8 above the real "Ecom Express Limited" (0.6), apparently because of "Ltd" versus "Limited". The domain lookup returned the real record first (plus an "Ecom Express Support" record at 1.0), so `exists` is `unknown` (correct and safe), but the pipeline then profiled the wrong record (2 credits) and `active` is based on it. The reverse lookalike ("Ecom Express Delivery Center", no website) passes `exists` as itself, which is right but shows that without a domain the name alone cannot separate it from the real company.
4. **`adverse_media: pass` is a weak pass.** ProConnect, Xtrans, LorryCare, the wrong-domain vendor and the (wrong) Ecom Express Ltd record pass because 2 searches found nothing that names the target. For LorryCare the only result was an unrelated profile. Delhivery, DTDC, Everest Fleet and the delivery centre are `unknown`: 10, 7, 3 and 4 possible reports, mostly customer complaints, none dated and resolved.
5. **DTDC `exists` passes despite 2 records tied at 1.0**, because the client-supplied domain resolved to the same record. Good, but it depends on the domain being supplied and right.
6. **Wrong domain was caught** ("input domain belongs to a different company"), at the full cost of 4.2 credits.
7. **No vendor can be cleared in this run** (director unknown by design), and nothing produced an action. Whether the pipeline would clear a genuinely clean vendor end to end on live data is not shown here.

## 8. Nothing tuned

No parameter or rule was changed for this run. Fill in the blank column and I can run `evaluation/run_eval.py` against these labels.


## 9. Re-check after M1 to M4 (22 Nov, fresh database, 2 vendors, 4.6 credits)

Same pipeline with our own candidate matching (`candidate_name_sim_floor` 0.85, token-sort similarity on normalised names; Crustdata's confidence is ignored), full-name adverse relevance, and the limited-coverage wording. Nothing else changed. Raw: `probe/raw/live/` (gitignored); results: `probe/live/mcheck_results.json`.

| Vendor | Verdict | exists | active | director | adverse | Calls (paid) | Credits | Before (section 1) |
|---|---|---|---|---|---|---|---|---|
| Ecom Express Limited (domain ecomexpress.in) | CANNOT_VERIFY | pass | pass | unknown | unknown | 6 | 3.4 | n/a (earlier run used "Ecom Express Ltd": exists unknown, wrong record enriched, 4.4) |
| Zentrovia Cargo Solutions Pvt Ltd (invented) | CANNOT_VERIFY | unknown | unknown | unknown | pass | 3 | 1.2 | exists unknown "several records tie", unrelated company enriched, 3.2 |

- **Invented vendor:** all 25 Identify candidates were below the floor, so `exists` is `unknown` with "No record found. The vendor may be too new or too small for the data source", and the missing list includes "independent registry evidence (CIN/GSTIN/incorporation certificate)". **No enrich or jobs call was made** (3 calls, 1.2 credits instead of 3.2). Adverse: "no adverse reports found in 2 searches (limited coverage); 10 results scanned". The 10 scam-checker pages for look-alike domains are no longer counted as hits.
- **Ecom Express Limited:** the single record above the floor was chosen on the supplied domain, `exists` passes, and the right record was profiled (2 activity signals). Adverse is still `unknown`: 4 possible reports name the company, none can be resolved to it or verified, so nothing here can reject. The earlier wrong-record problem ("Ecom Express Ltd" resolving to "Ecom Express Pvt Ltd") is covered by the recorded-fixture test, not re-run live here.
- **Leftover found in this run and fixed (`76a8f52`):** for the invented vendor the director check said "claimed director not found at this company" although no director was supplied and there was no company. It now says "no claimed director in the request" (or "no company record to look for the claimed director in" when one is supplied).
- **Credits:** 4.6 for this check (budget 8). The account balance went 15040.39 to 15035.79.
- **Still true:** no claimed director was supplied, so no vendor can be `CLEARED`; the live director lookup (Person Search by name and employer) is written but has **not** been validated against the live API.

## 10. Diagnostics before the T2 collection

### 10a. Why Ecom Express Limited is `unknown` and the invented vendor passes

Offline, from the saved raw responses of the section 9 run (no credits). Both vendors had `searches_run` 2 and `results_scanned` 10 (web 10, news 0).

| | Ecom Express Limited | Zentrovia Cargo Solutions Pvt Ltd |
|---|---|---|
| Results naming the target (full-name phrase rule) | 5 of 10 | 0 of 10 |
| Of those, severity >= 2 (`adverse_min_severity`) | 4 (one is severity 1 and ignored) | 0 |
| Of those, dated | 4 of 4 | n/a |
| Dated, resolved to the target, source page verified, severity >= 3 | 0 | n/a |
| Result | `unknown`: "4 possible adverse reports, not enough to reject..." | `pass`: "no adverse reports found in 2 searches (limited coverage); 10 results scanned" |

**Cause: not a bug.** The real company has press and complaint pages that name it, so its hits exist and cannot be dismissed or confirmed (no discriminator, no verified page, severity below 3). The invented vendor has no pages that name it, so nothing is flagged. Most of its 10 results are scam-checker pages for other websites.

**Is the stricter phrase rule hiding real results? No, on this evidence.** Results the old first-word rule counted but the phrase rule dropped: Ecom Express #1 (a generic post about "ecom scamming") and #4 (a generic "eCommerce fraud" guide); Zentrovia #2, #5 and #9 (other websites). None refers to the company. I did not loosen the rule.

**A design point for you:** coverage works against the real vendor. A vendor with any press presence ends `unknown` on adverse media, while a non-existent one gets a `pass` (labelled limited coverage). The pass is harmless today because `exists` is `unknown` for it, but it shows that `pass` here means "nothing found", not "nothing wrong". Options: leave as is; make a limited-coverage pass not count as a pass; or require that `exists` passes before adverse can pass. Not changed.

### 10a-2. Person Search request shape (no real person)

The live director lookup (`checks/live.py`) had only been tested with fakes. One call with an invented placeholder name at a large company returned HTTP 200, zero results, zero credits: the filters (`basic_profile.name`, `experience.employment_details.current.name`) and the field list are accepted. The results key is `profiles`. Result fields for a real person are exercised in 10b.
