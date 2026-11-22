# plan.md: Trust and Compliance: Vendor Clearance Desk
Track: Trust and compliance (with Supply chain sourcing as a stretch only if data allows). Client: a mid-size Indian 3PL clearing new carriers and suppliers.
Input: `{vendor_name, website, claimed_director, risk_tier, optional registry IDs}`. Output: a recommendation (`CLEARED`, `REJECTED`, `CANNOT_VERIFY`, `HOLD_FOR_APPROVAL`) with sourced reasons, missing evidence, cost, held for a person's approval.
Time: code freeze 6:00 PM. Requirement change expected around 1:45 PM (hour 3). Demo video by 5:30 PM. Items marked **[D#]** need a decision from Tejas first (see DECISIONS.md). Commit points are marked 🔖.

## Done
- [x] Core: state, resume, evidence ledger, cost ledger, throttle, cache, idempotent actions, approvals 🔖
- [x] Decision rules (recommendations, unreachable holds) 🔖
- [x] Crustdata probe: `probe/REPORT.md`
- [x] Policy layer (signals to checks, proposed parameters) and evaluation harness with synthetic cases 🔖

## Now (13:30 to 15:00)
- [ ] Put these docs and the eval harness in the repo, commit in separate commits 🔖
- [ ] Registry probe: do aggregator pages fetch directly? CIN, status, directors, incorporation date? **[D9]**
- [ ] News probe: `sources:["news"]`; decode `google.com/goto?url=` links; dates present? **[D10]**
- [ ] Real eval fixtures from `probe/raw/` (pseudonymised), proposed labels for Tejas to confirm 🔖
- [ ] Tejas reviews D1 to D8 and D11, D12 and fills the Decision column
- [ ] `checks/exists.py` and `checks/active.py`: raw Crustdata to signals, through `cached_call` 🔖
- [ ] `checks/director.py` 🔖
- [ ] `checks/adverse.py` with quote-grounding and injection defence 🔖

## Next (15:00 to 16:30)
- [ ] `pipeline.py`: one request end to end with resume; CLI `run`, `status`, `approve`, `reject` **[D14]** 🔖
- [ ] Chaos tests: kill mid-run, timeouts, junk responses; show each action happens once 🔖
- [ ] Run the evaluation on real fixtures; sweep parameters; Tejas picks values **[D5 to D8, D11]** 🔖
- [ ] Handle the hour-3 requirement change (should be a config or schema edit) 🔖
- [ ] "What would settle it": for each `CANNOT_VERIFY`, name missing evidence and draft a document request held for approval **[D15]** 🔖

## Then (16:30 to 17:30)
- [ ] Ethics layer: data-minimisation log, purpose per data item, namesake safeguards, plain-language explanation per decision
- [ ] Finance: measured credits per vendor, rupee price, manual-KYC comparison **[D16]**
- [ ] Stretch, only if time and data allow: ring detection across vendors; Watcher re-checks
- [ ] README (job, who pays, input, result, pass mark, sources, how to run, approaches tried), architecture diagram, `NOTES.md` 🔖

## Submit (17:30 to 18:00)
- [ ] Practise the demo on an unseen request; kill the process mid-run on purpose
- [ ] Demo video (2 minutes, one link, plays in a private window)
- [ ] Repo is currently PRIVATE: make it public (or give judges access) before submission; history intact, no secrets; diagram link opens for anyone
- [ ] Submit once early as a safety net, then the final

## Roles (D1, to confirm)
- **Tejas:** product owner and every decision; approval flow and demo (he has shipped Photog end to end: UI, security hardening, release process); ethics and robustness review. He directs Claude Code and keeps the stack to Python and CLI rather than JS.
- **Teammates:** split by module: checks (data), pipeline and tests, docs and diagram. Fill in skills so the split fits.
