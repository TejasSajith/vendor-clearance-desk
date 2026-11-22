# DECISIONS.md: Tejas decides; agents only propose
Status: PROPOSED (waiting for Tejas) / DECIDED (Tejas filled in the Decision column). Do not build on a PROPOSED row.
Proposed values live in `policy.PROPOSED_PARAMS`. Test alternatives with `evaluation/run_eval.py --compare`.

| # | Decision | Options and trade-offs | Proposed (not binding) | Affects | Status | Decision |
|---|---|---|---|---|---|---|
| D1 | Team roster and roles | Who builds checks, pipeline, approvals, docs/demo | Tejas: owner, approvals UI, ethics review, README and demo | all | PROPOSED | |
| D2 | Does `CLEARED` need approval too? | Yes (safer, matches "cannot take back") / only `REJECTED` | Yes, both | ethics, robustness | PROPOSED | |
| D3 | Crustdata `status=deleted` | Treat as unknown (needs registry) / treat as fail | Unknown | exists | PROPOSED | |
| D4 | Input domain resolves to another company | Unknown / fail | Unknown | exists | PROPOSED | |
| D5 | `name_sim_min` | 0.8 / 0.9 / 0.95: lower accepts more lookalikes | 0.90 | exists | PROPOSED | |
| D6 | `active_min_signals` and tier extras | 1 / 2 / 3 of headcount, jobs, traffic; small firms rarely have jobs or traffic | 2; +1 for high risk | active | PROPOSED | |
| D7 | Activity thresholds | min headcount, max decline, series age, jobs window | 5, 30%, 60 days, 90 days | active | PROPOSED | |
| D8 | Adverse media: severity scale and minimum; what makes a hit "confirmed" | Needs date + names target + discriminator + resolvable source | min severity 2 of 3 | adverse | PROPOSED | |
| D9 | Registry source (CIN, status, directors) | A: aggregator pages via Web Search+Fetch (probe: 0/3 companies, one site blocked by Cloudflare, the other needs a CIN) / B: KYC or MCA API (new vendor, not probed) / C: none, report CANNOT_VERIFY. See `probe/REPORT_registry_news.md` | None. Tejas to choose | exists, director | PROPOSED | |
| D10 | News source | A: Crustdata Web Search news (probe: 0 to 9 results, off-target, no dates, redirect links) / B: news API (not probed) / C: RSS or court and regulator feeds (not probed); optional free redirect resolving. See `probe/REPORT_registry_news.md` | None. Tejas to choose | adverse | PROPOSED | |
| D11 | Error cost weights in the eval | wrong, abstain, hold-vs-cnv | 3, 1, 0.5 | tuning | PROPOSED | |
| D12 | Risk tiers: how a vendor gets low, medium or high | By payment value / by category / manual input | Manual input per request | policy | PROPOSED | |
| D13 | Model per step and per-run limits | Cheaper model for extraction, stronger for disambiguation; credit and time caps | TBD | cost, finance | PROPOSED | |
| D14 | Approval interface | CLI only / small local web page | CLI first | demo, ethics | PROPOSED | |
| D15 | Stretch features | quote-verification and injection test, document-request drafts, ring detection, Watcher re-checks | First two before the others | value | PROPOSED | |
| D16 | Credits to rupees and our price per vendor check | From Crustdata pricing page vs manual KYC cost | TBD | finance | PROPOSED | |
| D17 | Which event document governs | Handbook (dashboard) vs problem-statement PDF; ask organisers | Satisfy both | scoring | PROPOSED | |
| D18 | Crustdata MCP use | Exploration only (Claude Code, probes) / also inside the service. The service must call the API itself through `core.cached_call` so every call is throttled, cached and ledgered | Exploration only, never inside the service | cost, robustness, ledger | PROPOSED | |
| D19 | Product framing and scope | (a) Vendor Clearance Desk: one request in, verdict out. (b) Tripwire: continuous monitoring, decay, exposure ranking, graph. (c) Hybrid: Clearance Desk core plus a few Tripwire ideas. 3 hours left; neither rubric scores monitoring | (c) | all | PROPOSED | |
| D20 | Verdict vocabulary | Ours: 4 verdicts, per-check pass/fail/unknown/unreachable. Theirs: per-claim Holds/Drifted/Contradicted/Unverifiable (NOT_FOUND/NO_DATA/STALE), tiers Clear/Watch/Hold/Unknown. Theirs has no timeout state, which the rules require | Per-claim states plus UNREACHABLE, rolled up to our 4 verdicts | policy, decision | PROPOSED | |
| D21 | Source independence grades (A/B/C) and whether aggregator pages count | Aggregators copy registry data: useful, but mirrors. Counting them lifts "partial" checks; not counting leaves more CANNOT_VERIFY | Use them, labelled mirror, never above grade C alone | exists, director | PROPOSED | |
| D22 | Harvest claims from the vendor's website and verify each | More coverage, more calls and credits (up to 7 fetches per vendor) | Yes, limited to load-bearing claims | active, exists | PROPOSED | |
| D23 | Confidence decay with half-lives | Adds "right for the day it is used"; numbers are hand-set guesses and change verdicts | As-of date and freshness window now; decay later | policy | PROPOSED | |
| D24 | Cache TTL and person-data retention | Mechanism now in engine v2 and OFF. Options: forever / 24h; person data 7 days | 24h; person-level 7 days; purge at end of run for person data | ethics, correctness | PROPOSED | |
| D25 | API keys and shared throttle | Handbook: each builder has their own account, credits and limits; teammates assume one shared key | One throttle per key; spread work across keys | cost, speed | PROPOSED | |
| D26 | Front end | CLI / plain HTML served by FastAPI / Next.js (you have not learned JS) | CLI first, plain HTML for the approval screen | demo | PROPOSED | |
| D27 | Defer list | Network graph, sanctions, overrides drawer, planner, exposure ranking, deep-tier scheduler, watchers | Defer all until the core is solid | scope | PROPOSED | |
| D28 | Record and replay mode for development | Saves credits and rate limit; replayed data must be labelled and never used for live decisions or the demo | Yes, labelled | cost, rules | PROPOSED | |
| D29 | Personal data in probe files and history | (1) Redact the unpushed history, dates unchanged. (2) Pseudonymise going forward only. (3) Delete the probe files | (1). Tejas ran it at 14:26 IST; organisers not asked. Declared in NOTES.md | ethics | DECIDED (executed 14:26 IST) | Option 1 |
| D30 | Retry policy for rate limits and timeouts | Attempts and back-off in config.json: proposed 3 attempts, 2s doubling; then the check reports unreachable and the case is held | 3 attempts, 2s | robustness, cost | PROPOSED | |
| D31 | Crustdata `news` handling | Use for discovery only; our code decides whether an article names the target; a missing `news` key is not a clean result | As described | adverse | PROPOSED | |
