# NOTES.md: approaches, results and declarations

## Approaches considered
- **Track:** Trust and compliance (vendor clearance for a mid-size Indian 3PL). Supply chain sourcing and research/markets were considered and dropped.
- **Data first:** probe Crustdata for what each of the four checks (exists, active, director match, adverse media) can actually cite before writing check code (`probe/REPORT.md`).
- **Deterministic rules decide, the model only extracts and explains:** `policy.py` and `decision.py`; parameters are PROPOSED until decided in `DECISIONS.md`.
- **Report-only tuning:** new rules and thresholds run through `evaluation/run_eval.py --compare` before they become defaults.
- **Registry and news sources:** aggregator pages via Web Search and Fetch, a KYC or MCA API, or none (D9); Crustdata news search, a news API, or RSS and court feeds (D10).

## What worked
- Company Identify, Enrich, Job Search and Person Enrich return usable, dated signals for mid and large firms: headcount history (10/10), status, jobs with dates, a company-ID link from person to employer (6/6).
- Per-endpoint throttle and response cache in `core.py` keep calls inside the account limits (5 per minute for company, person and job; 10 for web).
- Real fixtures built from the probe (`evaluation/cases_real.json`) with pseudonymised people.

## What did not
- No registry IDs (CIN, GSTIN, DIN) in any Crustdata response (0/10).
- Aggregator registry pages: 0/3 companies. Search did not surface them, one site is behind a Cloudflare check, the other needs a CIN in the URL.
- Adverse media: result URLs are mostly `google.com/goto` redirects, 8 of 11 first fetches returned a Google interstitial, and 28 of 41 snippets had no date. News search returned 0 to 9 results, mostly off-target.
- Identify confidence is not an auto-accept signal: ties at 1.0 and one domain resolving to a different company.
- Every real probe case ends in `CANNOT_VERIFY` under the proposed parameters, so far.

## Left out to ship
TODO (fill in at the end of the build).

## Declarations
- The starter code (`core.py`, `decision.py`, `policy.py`, `evaluation/`) was written with Claude during the event (first commit 13:06 IST).
- The repo's history before the redaction was redacted for personal data with dates unchanged.
