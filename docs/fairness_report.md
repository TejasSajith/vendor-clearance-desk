<!-- Generated 2026-11-22 18:01 IST by: python scripts/fairness_report.py probe/live/live.db probe/live/m.db probe/live/crash.db probe/live/cap.db probe/live/tuning.db --markdown (local ledgers are gitignored) -->
# Fairness report

Cases: 100 (run:live.db: 10, run:m.db: 2, run:crash.db: 1, run:cap.db: 1, run:tuning.db: 38, case:cases_real.json: 10, case:signals_real.json: 38). Rates are shown with counts; bands with fewer than 10 cases get no rate statement. The same vendor can appear in more than one source (a stored run and the tuning row collected from it), so the counts are not independent.

## By firm-size band (headcount)

| group | n | CLEARED | REJECTED | CANNOT_VERIFY | HOLD_FOR_APPROVAL | active unknown | exists unknown | adverse pass |
|---|---|---|---|---|---|---|---|---|
| no headcount data | 20 | 0 (0%) | 0 (0%) | 20 (100%) | 0 (0%) | 11 (55%) | 11 (55%) | 9 (45%) |
| 1-10 | 3 | 0 (0%) | 0 (0%) | 3 (100%) | 0 (0%) | 3 (100%) | 1 (33%) | 0 (0%) |
| 11-50 | 22 | 0 (0%) | 0 (0%) | 22 (100%) | 0 (0%) | 12 (55%) | 1 (5%) | 19 (86%) |
| 51-200 | 1 | 0 (0%) | 0 (0%) | 1 (100%) | 0 (0%) | 1 (100%) | 1 (100%) | 1 (100%) |
| 201-1000 | 10 | 0 (0%) | 0 (0%) | 10 (100%) | 0 (0%) | 2 (20%) | 0 (0%) | 4 (40%) |
| 1001+ | 44 | 0 (0%) | 0 (0%) | 44 (100%) | 0 (0%) | 6 (14%) | 2 (5%) | 16 (36%) |

## By stratum (tuning cases, cases_real.csv)

| group | n | CLEARED | REJECTED | CANNOT_VERIFY | HOLD_FOR_APPROVAL | active unknown | exists unknown | adverse pass |
|---|---|---|---|---|---|---|---|---|
| large_legit | 14 | 0 (0%) | 0 (0%) | 14 (100%) | 0 (0%) | 2 (14%) | 1 (7%) | 5 (36%) |
| mid | 12 | 0 (0%) | 0 (0%) | 12 (100%) | 0 (0%) | 5 (42%) | 3 (25%) | 7 (58%) |
| small_real | 11 | 0 (0%) | 0 (0%) | 11 (100%) | 0 (0%) | 4 (36%) | 0 (0%) | 8 (73%) |
| shut_down | 1 | 0 (0%) | 0 (0%) | 1 (100%) | 0 (0%) | 1 (100%) | 1 (100%) | 1 (100%) |

## Statement

What the rules do (policy.py): missing data is never a fail. A firm with no record, no headcount, no jobs or no web traffic gets 'unknown' (CANNOT_VERIFY), never REJECTED, and a rejection needs a dated, sourced, severe report. The activity check needs 2 of headcount, jobs and traffic, which small firms are less likely to have, so by design a small genuine firm is more likely to end in CANNOT_VERIFY than to be cleared; it is not rejected for being small.
What the data shows: 0 REJECTED verdict(s) in 100 cases.
Verdicts do not differ between bands: every case in every band with at least 10 cases ended CANNOT_VERIFY. So this data cannot show whether small firms are cleared less often; nothing was cleared in any band.
Where the bands do differ is the activity check: 'unknown' in 55% of no headcount data cases against 14% of 1001+ cases. That is the gap a small firm meets, and it is filled by a person collecting evidence, not by a rejection.
Too few cases for a rate statement: 1-10 (3), 51-200 (1).
Firm age is not in any stored signal, so new firms cannot be told apart from small ones here.
