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
