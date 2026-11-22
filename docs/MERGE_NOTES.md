# MERGE_NOTES.md: our plan vs the teammates' Tripwire handoff (22 Nov 13:50)
Sources: our repo docs and `probe/REPORT.md` vs `docs/tripwire_handoff.md`; Crustdata docs fetched 22 Nov. Tejas decides (see DECISIONS.md D18 to D28).

## A. Facts that conflict (check these first)
| # | Claim | Ours | Theirs | Evidence |
|---|---|---|---|---|
| 1 | Company Identify cost | 0.2 credit per match (probe: 18 calls, 3.6 credits) | free | **Resolved:** `GET /account/endpoints` lists 0.2 credits for `/company/identify` on our account. The docs say Free, so docs prices are not reliable. Record the cost each response reports |
| 2 | Company refresh date | none at company level (probe) | Enrich has top-level `updated_at` | **Open:** the probe never requested `fields: ["metadata"]`, so the field was not asked for, not shown empty. Test on one company (about 2 credits) |
| 3 | Rate limits | 5/min company, person, job; 10/min web | about 5/min, unsure if per endpoint or overall | **Resolved:** per endpoint (5 for company, person and job endpoints incl. Identify; 10 for web; 300 autocomplete) plus an account-wide `token_limit_rpm` of 100. Engine v2 enforces both |
| 4 | Headcount time series | `headcount.timeseries[]` has 155 to 365 dated points (probe) | unsure | Docs do not describe it; the probe saw it in real responses. Trust the probe |
| 5 | Keys | one key per builder (handbook FAQ: each builder gets their own account and 15,000 credits) | one shared key for 3 people | Handbook; three keys give three times the limit and credits |
| 6 | Adverse-media dates | no dates in web results (probe) | Company Enrich `news` and Web Search `sources:["news"]` with `start_date`/`end_date` | **Tested (3 companies):** every article had a URL and a publish date, and `news` costs nothing extra (2.0 base). But it is noisy (stock-quote pages), news attaches by name and can be about a different company (one hit was about SS Innovations, not SS International), and the key is omitted when there is none. So: use it for discovery, compute `names_target` ourselves from the fetched text, and never count a missing `news` key as "searched, nothing found" |

## B. Design disagreements
7. **Scope.** Tripwire is continuous monitoring with 13 novel elements, two pipelines, a graph, a planner, overrides and a UI. We are one request in, one sourced verdict out. Neither event rubric scores monitoring or expiry; both score correct sourced results on an unseen request, restart safety, ethics and cost. 4 hours remain. Hybrid proposed (D19).
8. **Verdicts.** Per-claim Holds/Drifted/Contradicted/Unverifiable with NOT_FOUND/NO_DATA/STALE (theirs) vs four verdicts with unknown/unreachable (ours). Theirs has no timeout state; the rules say a timeout is never an answer. Ours has no per-claim detail or staleness. Merge (D20).
9. **Aggregator pages.** We proposed them for CIN, status and directors. Theirs: mirrors, never count toward grade A or B; registry portals "need human check"; offline GSTIN/PAN/CIN structure checks. A valid checksum proves format only. (D21)
10. **Ledger.** Theirs: hash-chained, graded, with half-life decay. Ours: plain table with source passage and date. Compatible; decay changes verdicts and its numbers are guesses (D23).
11. **Cache.** Ours never expires, which breaks "right for the day it is used" and person-data retention. Theirs: 24h, person data 7 days. Our flaw (D24).
12. **Reliability.** Theirs has no crash-resume or exactly-once design; ours does. The kill-on-stage and screening restart score on this.
13. **Ethics and finance.** Each is worth 25 in the problem-statement finals. Theirs: a privacy bullet and a credit log. Ours: planned, not built. Gap for both.
14. **Stack.** Python, FastAPI and SQLite agree. Next.js conflicts with your not knowing JS (D26).
15. **Tests.** Theirs: Attack Lab of real public companies with scripted claims, SIMULATED labels, injectable clock, 10 archetypes. Ours: synthetic plus real fixtures. Adopt their archetypes as the case list. Neither covers hidden cases dated after 1 Sept 2026.
16. **Cost per vendor.** Theirs 10 to 13 credits (up to 7 fetches); ours 5 to 6. Quote neither: finance judges want measured cost from the ledger.
17. **Roles and name.** Their A/B/C split vs D1; "Tripwire" vs "Vendor Clearance Desk".
18. **Prior art.** They studied earlier ContextCon repos. Ideas are fine; the rule says teams build their own work, so do not copy code without declaring it.

## C. Adopt now (cheap, high value)
Batch enrich 25 per call; Company Enrich `news` and `updated_at`; Web Search date filters; Job Search `limit:0` counts; offline ID structure checks; source independence grades; claim harvest with fixed-schema extraction and quote-grounding; injectable clock; sentence validator; hash chain; `GET /account/endpoints` first; decode `google.com/goto?url=` links.

## D. Defer
Network graph, sanctions screening, overrides drawer, planner, exposure ranking, half-life decay, deep-tier scheduler, watchers, Next.js UI.
