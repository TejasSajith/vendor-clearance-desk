# Unit economics

Every figure here comes from the ledger (via `finance/cost_report.py`, output committed in `finance/cost_report_output.txt`) or from `finance/assumptions.json`. Inputs the owner has not supplied are marked **ASSUMPTION - TODO**. To refresh the numbers after filling in the assumptions:

```
python finance/cost_report.py probe/live/live.db probe/live/m.db probe/live/crash.db probe/live/cap.db probe/live/tuning.db probe/live/director_shape.db probe/live/phase0.db --economics
```

## 1. What one vendor check costs (measured)

From 32 finished vendor runs in the local ledgers (`finance/cost_report_output.txt`; 7 more runs were still running or had been killed and are left out of the statistics):

| Measure | Credits |
|---|---|
| Mean per vendor | 4.65 |
| Median | 4.43 |
| p90 | 6.43 |
| Min / max | 1.20 / 6.43 |
| Largest single call in a vendor run | 2.00 (`/company/enrich`) |

Where the credits go, per run (same file): `/company/enrich` 2 credits once; `/company/identify` 0.2 per call, two calls (name and domain); `/job/search` 0 to 0.03; `/web/search/live` 0 to 1 per search. Runs in `live.db` made 2 web searches; runs in `tuning.db` (the signal collector) made 4, so they cost more. A vendor with no company record costs least (identify and the adverse searches only).

Seconds: the mean time inside calls is 106.77 s per vendor. This includes waiting for the throttle (5 calls per minute on company, person and job endpoints), so it is mostly queueing, not API time.

Model calls: 0 in these ledgers (`/llm/generate`). Gemini cost: free tier while `gemini_inr_per_1m_*_tokens` are TODO in `finance/assumptions.json`.

The same request submitted twice costs nothing the second time (dedupe returns the existing run). Cache savings on reruns are logged only for runs made through the clearance guard (`clearance/guard.py`, table `cache_hits`); none of the committed ledger runs went through it, so the report shows 0.

## 2. In rupees, versus the analyst

| Item | Value |
|---|---|
| Rupees per credit (`inr_per_credit`) | **ASSUMPTION - TODO** |
| Credits cost per vendor at the mean: 4.65 x rupees per credit | **ASSUMPTION - TODO** |
| Analyst cost per check today (`analyst_cost_inr_per_check`) | **ASSUMPTION - TODO** |
| Analyst review cost per check with the service (`analyst_review_cost_inr_per_check_with_service`) | **ASSUMPTION - TODO** |
| Proposed price per check (`price_inr_per_check`) | **ASSUMPTION - TODO** |
| Gross margin per check: price - credits cost - review | **ASSUMPTION - TODO** |

The analyst never leaves the loop: every CLEARED and REJECTED needs a person's approval, and every CANNOT_VERIFY goes to a person with a missing-evidence list. So the saving is the difference between the analyst's full manual check and their review of a sourced memo, not the whole analyst cost. In live validation every real vendor so far ended in CANNOT_VERIFY (`NOTES.md`), so today the review step still includes collecting registry evidence by hand.

## 3. Cost at volume

Credits are measured (mean 4.65 per vendor); rupees need the rate.

| Vendors per month | Credits | Rupees (credits) | Analyst cost today | Revenue at the price |
|---|---|---|---|---|
| 100 | 465.41 | ASSUMPTION - TODO | ASSUMPTION - TODO | ASSUMPTION - TODO |
| 1,000 | 4,654.10 | ASSUMPTION - TODO | ASSUMPTION - TODO | ASSUMPTION - TODO |
| 10,000 | 46,541.00 | ASSUMPTION - TODO | ASSUMPTION - TODO | ASSUMPTION - TODO |

Rate limits matter at volume: the throttle allows 5 calls per minute on each company endpoint (`config.json rate_limits_per_min`, applied per exact endpoint by `core.throttle`), and a vendor with a website needs 2 `/company/identify` calls, so one key clears at most 150 vendors per hour (5 x 60 / 2). 10,000 vendors a month is within that only if runs are spread across the month; bursts need several keys or a higher limit (D25).

## 4. Break-even

Break-even volume = `fixed_cost_inr_per_month` / (`price_inr_per_check` - credits cost per vendor - review cost per vendor).

Today: **ASSUMPTION - TODO** (needs `price_inr_per_check`, `inr_per_credit`, `analyst_review_cost_inr_per_check_with_service`, `fixed_cost_inr_per_month`). `cost_report.py --economics` computes it as soon as these are numbers.

## 5. Sensitivity to the credit price

Rupees per vendor = 4.65 x rupees per credit x multiplier. The multipliers (0.5, 1, 2) are scenarios in `finance/assumptions.json`, not data.

| Credit price | Rupees per credit | Rupees per vendor (mean) | Margin per check |
|---|---|---|---|
| 0.5 x | ASSUMPTION - TODO | ASSUMPTION - TODO | ASSUMPTION - TODO |
| 1 x | ASSUMPTION - TODO | ASSUMPTION - TODO | ASSUMPTION - TODO |
| 2 x | ASSUMPTION - TODO | ASSUMPTION - TODO | ASSUMPTION - TODO |

The margin falls by 4.65 rupees per check for every rupee added to the credit price (mean case), and by 6.43 rupees at p90.

## 6. Worst case per vendor, bounded by the per-run cap

`core.tracked_call` checks the cap before each call: a call may start only while the run's spend so far is not above `max_cost_credits_per_run` (50, PROPOSED, D13). So the most one vendor can cost is

  cap + the most expensive single call = 50 + 2.00 = **52.00 credits** (largest call seen in a vendor run, from the ledger).

In rupees: 52.00 x rupees per credit = **ASSUMPTION - TODO**.

Other bounds: the time cap (300 s) stops a run the same way; the UI session cap (100 credits, D39) lets a run start only if the full per-run cap still fits; the daily cap (100 credits, PROPOSED, D50, `ops_config.json`) refuses new paid calls once the day's ledger total reaches it. A run stopped at a cap returns CANNOT_VERIFY with what it spent; in the ledgers, 1 run stopped at a cap after 2.4 credits. See `finance/BUDGET_CONTROLS.md`.
