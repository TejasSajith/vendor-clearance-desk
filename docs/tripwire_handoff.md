# Handoff: Crustdata ContextCon hackathon, Theme 5 "Tripwire"

Written 22 Nov 2026 for continuing this project in a new chat. Everything marked **[VERIFY]** is an assumption or untested. Treat it as unverified until checked against the docs or a real API call. All thresholds, half-lives and weights are hand-set starting guesses to be tuned on the test set.

## 0. How to use this file
Paste it as the first message in a new chat and say: "Continue from this handoff. We are a team of 3 building Tripwire." Then pick a next task from section 12. The user wants a practical build plan, novelty beyond the template, minimal time and credits, and honest (not overclaimed) behaviour.

## 1. Situation
- Hackathon: ContextCon, run by Crustdata (BITS Pilani 2026 edition). Build an agent that does a paid-today job with no one at the keyboard, using Crustdata's API and data.
- Team: 3 people. They know little about underwriting or supply chain. They had an earlier supply-chain + trust idea and **scrapped it**. They chose **Theme 5, Trust and compliance**, and want the "Tripwire" idea (continuous vendor monitoring) with real novelty, not just the template.
- Constraint: their key is limited to **about 5 API calls per minute** [VERIFY whether that is per endpoint or overall via `GET /account/endpoints`, which returns `effective_rate_limit_rpm` per endpoint and `token_limit_rpm`]. Goal: one vendor check should take **no more than about 1 minute**.

## 2. The themes (from the brief)
Hiring (1.1 Search Desk, 1.2 Career Check), Investing (2.1 Pre-Round Scout, 2.2 Diligence Desk), Research and markets (3.1 Market Map, 3.2 Research Desk), Insurance (4.1 Underwriting Desk), **Trust and compliance (5.1 Vendor Check, 5.2 Adverse Media Screen)**, Buying and paying (6.1 Payables Desk), Agents that spend (7.1 Research Buyer), Supply chain (8.1 Sourcing Desk), Revenue (9.1 Outbound, 9.2 Inbound), Infrastructure for agents (10.1 Evidence Ledger, 10.2 Sign-Off Gate).

**Theme 5 in brief.** Compliance analysts at banks, payment firms and large buyers decide whether a business or person is who they claim to be before money moves. Hard because: records share no common key, a slow source looks like a missing one, and a front company can carry genuine papers.
- 5.1 Vendor Check: a new vendor proven real, active and run by its director.
- 5.2 Adverse Media Screen: directors screened against the news, namesakes cleared.
- Sample request: "Here is a new vendor's name and website. Tell me whether it is a real, trading business: who runs it, how long it has existed, and anything that looks off."
- Suggested APIs: Company Identify, Person Enrich, Web Search and Fetch.
- **Judging line: "fronts caught with evidence, while honest firms and innocent namesakes pass."**

## 3. Crustdata API knowledge (from docs.crustdata.com, fetched Nov 2026)
Auth: `Authorization: Bearer <key>` and header `x-api-version: 2025-11-01` on every call. Base `https://api.crustdata.com`. Docs index: `https://docs.crustdata.com/llms.txt`.

| Area | Endpoints | Notes |
|---|---|---|
| Company | `/company/search`, `/company/search/autocomplete` (free), `/company/identify` (free), `/company/enrich`, batch | Enrich takes up to 25 companies per request, one identifier type per request (`domains`, `names`, `crustdata_company_ids`, or profile URLs). `fields` selects sections: basic_info, headcount, funding, locations, taxonomy, revenue, hiring, followers, seo, competitors, social_profiles, web_traffic, employee_reviews, people (founders, decision_makers, cxos), news, software_reviews, public_launches, market_intel, technographics (gated), social_posts (gated beta). Omitting `fields` returns basic_info only. `exact_match:true` for strict domain match; multiple matches carry `confidence_score`. Enrich headcount growth keys are `mom/qoq/six_months/yoy/two_years`; search uses `1m/3m/6m/12m`. Enrich has top-level `updated_at`. |
| Person | `/person/search`, `/person/enrich`, `/person/contact/enrich`, `/person/identify`, `/batch/person/verify` | Search filters on title, employer (by name, domain or profile URL), location (incl. geo radius), education, skills, `recently_changed_jobs`, current-role `start_date`, etc. Operators: `=`, `in`, `(.)` (all words, any order, typo-tolerant), `[.]` (exact phrase), `not_in`, `(!)`. Semantic search (beta) via `search.query`. Person Enrich takes up to 25 profile URLs. Identify accepts profile URLs, emails or scholar URLs only (not names), 25 per call. Batch Verify checks work-history genuineness: verdicts clearly_genuine, probably_genuine, cannot_verify, probably_fabricated, clearly_fabricated, reclassified_employment, non_person; max 10 profiles per job; 10 credits per verdict; **enabled per account**. |
| Job | `/job/search`, batch, live (one company) | ~48M listings. `metadata.date_added` = posted date. Aggregations (`count`, `group_by`) with `limit:0` return no rows. |
| Web | `/web/search/live`, `/web/enrich/live` (fetch) | Search sources: web, news, scholar-articles, scholar-author, ai, social; `site`, `start_date`/`end_date` (Unix seconds). Fetch: up to 10 URLs per request, returns title and HTML. `fetch_content` flag was removed. |
| Social | `/social_post/search` | 0.5 credit per post, enabled on request. |
| Watchers | `/watch/{dataset}` (entity), `/watch/{dataset}/search` (discovery) | Entity watcher on companies: 30-day SLA only, 5 credits per changed company; person entity watcher 5 credits (30-day) up to 150 (1-day). First run is a free baseline. Alerts via webhook, Slack, email. Management calls limited to 10/min. |
| Account | `/account/endpoints`, `/account/credits`, `/account/usage/*` | Free. Show what the key can use and what it costs. **Run these first.** |
| Agent tooling | MCP server `https://install.crustdata.com/mcp` (OAuth, or bearer API key), CLI, Claude Code and Codex plugins | Same API. |

**Credits (list prices; read `X-Credits-Used` response header for actuals).** Person search 0.03/result + premium groups (experience, education, skills +0.1 each; default fields = 0.23/result). Company search 0.03/result + premium groups. Company enrich 2 (4 with technographics). Person enrich 1 (to 9 with add-ons). Person identify 1 per match. Company identify free. Job search 0.03/result (no rows = no cost). Web search 1/page, web fetch 1/page. Entity watchers as above.

**Rate limits (defaults).** person enrich 15 rpm, person search 30, person identify 30, company enrich 15, company search 30, job search 30, web search/fetch 10, watch management 10, autocomplete 300, batch concurrency 5 active jobs. **This team has about 5 rpm, so everything below is designed around it.**

**Freshness.** Indexed records refresh every 1 to 30 days (`updated_at`). Live endpoints fetch from the web but are plan-gated. Do not claim real-time monitoring.

**Gotchas.**
- Many endpoints are gated per account (verify, contact enrich, social posts, technographics, preview, live, batch). Another team's work-email enrichment returned 403.
- `=` and `in` are whole-string matches. `(.)` over-matches short acronyms.
- Country strings are not normalized in job data.
- The data is a snapshot, with no point-in-time history [VERIFY whether enrich returns per-section timeseries, mentioned in a docs note].
- **Missing data does not mean contradicted.** Coverage of small Indian firms may be thin.
- Purchased credits expire after 12 months.

## 4. Lessons from earlier ContextCon projects (repos the user shared)
- **Sourced + Agaxes** (ContextCon 03, IIT Bombay x Crustdata x YC): hiring agent; every claim labelled Verified, Contradicted or Unverifiable with its source; Ed25519 agent "passports" tied to a human sponsor; "Send Guard" blocks drafts with false claims; hash-chained ledger; MCP server; modes live/cache/replay/dev; seeded fake resumes as a test set.
- **SignalGate** (Trust and Compliance track, same event): decides invest/lend. Company Identify, Enrich, Person Search, Job Search, Web Search; fixed rules decide, the LLM only reads and writes; refuses to guess when 25 companies share a name ("Not enough evidence"); catches lookalike email domains and fake CFOs; per-case credit limit and 24h cache. **Closest prior art to Theme 5, so Tripwire must differ.**
- **Markit**: ICP to Crustdata company search, scored with evidence stripped by code if absent from the record; human approval before Gmail send to an allowlist; demo cache.
- **AfterDegree**: exact counts via count-only searches; per-run credit budget; disk cache; person data cached at most 7 days; anonymous aggregate output, never groups under 5; claims to follow Crustdata's data terms.
- **Outcome AI planning pack**: durable workflow with bounded model calls; LIVE/CACHED/FIXTURE/SIMULATED labelling; actions only through checked durable actions.
- **FINN** (not a Crustdata project; built for an ENAM challenge): daily portfolio briefing with cited numbers; code computes every number and the LLM only writes; a validator deletes any sentence without a source; "Promises" ledger checking claims against later outcomes.
- **Common winning habits**: code decides and LLM extracts; refuse to guess on ambiguity; every claim sourced; planted-trap test sets; credit budgets and caching; safe demo/replay modes honestly labelled. Hiring, trust, outbound sales and investing are well covered, so differentiate.

## 5. The idea: Tripwire (vendor trust that expires)
**Pitch:** "A vendor check that expires, knows what is at stake, and spends its limited budget where trust is decaying fastest." Inspired by FINN's daily briefing: a watched book of vendors, a ranked daily brief, every line cited, claims checked against later reality.

**Novel elements:**
1. **Claim half-life**: verdict confidence decays with age; old checks fade to Stale.
2. **Credit- and call-aware planner**: re-check the claims with the highest risk per call.
3. **Exposure-aware ranking**: risk x money at stake x days to payment; outputs "hold this payment".
4. **Three kinds of unknown**: NOT_FOUND, NO_DATA, STALE (thin data must not look like fraud).
5. **Independent website-claim verification**: harvest every claim on the vendor's site, verify against sources the vendor does not control.
6. **Two full pipelines**: company and people.
7. **Network graph, two layers**: shared people/addresses/domains/phones/registration IDs, plus company-to-company similarity.
8. **Sentinel lane + severity floors**: cheap checks on everything regardless of age; some events (sanctions or fraud hit, closure, acquisition, regulator action) jump to the top.
9. **Namesake court** with "what would settle this".
10. **Injection-proof reading**: fetched pages are untrusted data; extraction has no tools and emits a fixed schema; code decides.
11. **Manual overrides** for everything important (section 9).
12. **Look-back**: each fact has "happened on" and "learned on"; late discoveries list payments made in between.
13. **Attack Lab scorecard** and **audit replay / timeline scrubber**.

## 6. Onboarding: one box, no form
The user pastes a name and/or URL (a list also works). Company Identify (or Enrich by domain) resolves it. If ambiguous, show 2 to 4 tappable candidates and never guess. The agent answers the brief's four questions: **Is it real and trading? Who runs it? How long has it existed? Anything off?**, streamed, each line citing a ledger fact. The vendor joins the watched book automatically. Website claims are inferred, never typed. Exposure (contract value, next payment amount and date, criticality) is added later via a nudge or CSV import; until then rank by severity alone and say "exposure unknown". Defaults for half-lives and thresholds are editable in an overrides drawer. Tripwire never moves money; a payment hold is a proposed, human-approved action (simulated in the demo).

## 7. Pipelines
### 7a. Company pipeline
- **C0 Resolve**: Identify/Enrich; domain submitted vs matched domain (mismatch is a signal).
- **C1 Harvest claims**: fetch Home, About, Contact, Products, Careers, Terms, Privacy (up to 10 URLs per fetch call). Strip to text in code; schema-bound LLM extraction with no tools. Store each claim as type, value, exact quote, page URL. Types: founded year / "since", headcount, addresses and units, phone/email, GSTIN/CIN/PAN, certifications, named clients, awards/press, named leaders, capabilities.
- **C2 Verify each claim independently**: founded year (Crustdata `year_founded`, earliest Wayback snapshot, RDAP domain age [VERIFY], oldest news, CIN year); headcount/units (headcount, locations, job counts, search each unit address); address (locations, geocoding, search the address for co-working/residence/shared with unrelated firms); GSTIN/CIN/PAN (offline checksum and structure checks: GSTIN state code vs office state, PAN 4th letter vs entity type, CIN year/state; portal lookups are behind captchas, so mark "needs human check"); certifications (issuer database such as IAF CertSearch [VERIFY access], certificate-number search, else needs human check); clients (search the client side; logos with no outside confirmation stay grade C); awards/press (fetch the cited page and confirm it names the vendor); leaders (handed to the people pipeline).
- **Independence rule**: source classes are vendor-controlled; mirror/aggregator (does not count); independent structured record; independent third party. Reaching grade A or B needs at least one of the last two. Anything resting only on the vendor's own site stays C and can never produce "holds".
- **C3 Operating reality**: status and acquisition state; hiring flow from Job Search (role mix and trend, counts via `limit:0`); headcount growth; web traffic; news recency; website freshness from Wayback; email domain vs website domain; zombie pattern (old, genuine-looking, no hiring/news/live site).
- **C4 Company adverse screen**: news and sanctions-list name check with anchors.
- **C5 Verdict**: per claim Holds / Drifted / Contradicted / Unverifiable (reason NOT_FOUND / NO_DATA / STALE).
- **Website diff**: each refresh re-harvests the site and diffs claims (a director quietly removed, an address or certificate changed is a signal).

### 7b. People pipeline
- **P0 Who**: names from the website, Crustdata `people`, profile links; deduplicate; show "who runs it" with a source per person.
- **P1 Resolve identity**: Person Search on name + employer, score candidates on anchors (employer, city, school, career dates). A tie means "ambiguous", never a guess. Person Identify when the site links a profile URL.
- **P2 Employment**: currently at the vendor? since when? tenure vs claimed company age; title consistent with the site; overlapping full-time roles or full-time study. Optional second opinion: Batch Verify [VERIFY enabled].
- **P3 Background**: education claims vs record; past companies via Identify/Enrich (a pattern of closed companies is a weak contextual flag only, since startups fail often); plausibility of claimed expertise.
- **P4 Adverse media and namesake court**: build anchors (employer, city, past employers, school, career dates); search the name + each anchor, then name-only; fetch top articles; LLM extracts only what each article says about its subject into a fixed schema; code compares. Overlap = match; conflict = cleared (conflict shown); no anchors = unresolved with a "what would settle this" line (e.g. ask the vendor for date of birth or PAN holder city). Only matches raise signals. Sanctions/PEP screening here (OpenSanctions has licence terms [VERIFY]).
- **P5 People graph**: the same person across vendors; one director behind several "competing" vendors; unusual directorship counts.
- **P6 Privacy**: collect only what the check needs, show people only as evidence for the vendor decision, expire person-level cache after 7 days [VERIFY Crustdata data terms for your plan].

### 7c. Network graph
- **Layer 1, shared attributes**: people, addresses, domains, phones, registration IDs. Honest firms legitimately share business-park/co-working addresses and group directors, so use an address-popularity check and a "legitimate group" annotation (a manual override).
- **Layer 2, company similarity**: name similarity (token-set, edit distance, homoglyphs such as "rn" for "m"); domain similarity (TLD swaps, hyphens) against both the book and well-known companies; near-duplicate About/Products text; claim collisions (same address, same clients, same founded year + headcount, **same certificate number = hard flag**); impersonation (looks like a real company elsewhere under a different domain). Run within the book and against the world. Similarity alone is weak; a flag needs corroboration from another signal.

## 8. Engine, ledger, ranking, briefing
- **Fact ledger** (SQLite, append-only, hash-chained). Fact: id, subject, value, source_type, locator (field path or URL + quote), fetched_at, record_updated_at, content_hash, grade A/B/C, produced_by (code or model), rules_version, prev_hash. Reports may only cite fact IDs.
- **Grades**: A = two independent sources agree; B = one fresh structured record; C = vendor-asserted or one web page.
- **Confidence** = grade_weight x 0.5^(age / half_life); weights A 1.0, B 0.8, C 0.5; below about 0.4 shows as Stale.
- **Starting half-lives (guesses)**: company status 30d, headcount 30d, director currently employed 60d, address 180d, news screen 7d, certificates = hard expiry date.
- **Example rules (guesses)**: headcount within 25% holds, 25 to 60% drifted, over 60% contradicted; director found and current holds, found but left contradicted (with date), not found unverifiable; acquired/closed vs "independent and operating" contradicted.
- **Planner**: `priority = P(claim flipped) x impact x exposure / calls_needed`; probabilities are hand-set ordinal guesses and must be presented as such. Show what was skipped and why.
- **Sentinel lane**: reserve about 20% of budget for cheap news checks on every vendor and key person; use the free `news` section of Company Enrich as a first pass; severity floors jump to the top regardless of score; people appearing across several vendors are checked more often.
- **Ranking**: `risk = sum(severity of open signals) x exposure_weight x time_pressure`. Hard rule: contradicted director or status plus a payment within 7 days gives a **Hold recommendation**. Tiers: Clear, Watch, Hold, Unknown.
- **Briefing**: sections Act before money moves, New contradictions, Drifting, Cleared (namesakes with reasons), Stale (refreshed this run), Quiet, Footer (credits spent, claims not refreshed). The LLM sees only signals and writes one line each. **Validator** rejects any sentence with no ledger fact ID or with a number not in the cited evidence. A templated fallback runs if the model fails.
- **Action inbox (approval gate)**: read-only refreshes run on their own inside budget. Anything permanent (payment hold, clarification email, creating a watcher, tier change, export, raising the credit cap) is a proposed action with preview, evidence and cost. The decision goes into the ledger.
- **Tables**: vendors, exposure, claims, facts, checks, signals, actions, cohorts, credit_log, overrides.

## 9. Manual overrides
An override changes how evidence is read, never the evidence. Each needs a reason and a name, is logged, shows on screen as "overridden by X, reason Y", and mostly expires. Scopes: half-life (per claim type or vendor), verdict thresholds, a single verdict, tier (force Watch/Hold/Clear with expiry), exposure, refresh priority (pin or snooze), per-run credit/call budget, severity weights, hard rules (disable or change windows), "legitimate group" annotation. Overriding hard evidence (e.g. an anchored sanctions hit) needs a second approver. Replay records which rules version and overrides applied.

## 10. Late discoveries
- At onboarding: the vendor goes to an onboarding decision (Accept / Accept with conditions such as "no advances until the director is confirmed" / Reject / Need more info). Accepting with open contradictions needs a written reason (a logged override).
- Later: the new signal jumps the ranking, proposes actions (hold payment, clarify, escalate, offboard), and flags other vendors sharing the same director or address. Earlier verdicts are annotated as superseded, never deleted; the timeline scrubber shows what was known when.
- Limit: it can only find what is published and indexed, and the daily check means up to a day's lag.

## 11. Rate-limit-aware design (about 5 calls/min, 1 minute per vendor)
### Fast tier: 5 calls, about 50 seconds, ends with a **Provisional** verdict
1. Company Enrich by domain (`exact_match`) with sections basic_info, headcount, funding, locations, hiring, revenue, people, taxonomy, news (skips Identify; multi-match list shows ambiguity).
2. Web Fetch, up to 10 URLs in one call.
3. Person Search: employer domain + senior titles, limit about 10 (returns leaders with histories). **[VERIFY the combined filter on a known company.]**
4. Web Search sources news+web (one adverse-media query).
5. Job Search with `limit:0` and group_by aggregations (hiring volume, role mix); this call drops first if time runs out ("hiring flow: pending").
Stream each result as it arrives. If per-endpoint limits apply, the five calls hit different endpoints and can run in parallel (about 15 seconds).
### Zero-Crustdata-call work (do as much as possible)
LLM claim extraction (parallel); GSTIN/PAN/CIN checks; name/domain/homoglyph similarity; address popularity against the book; RDAP and Wayback lookups [VERIFY reliability]; verdict engine; ranking; briefing and validator.
### Deep tier (background, at the limit), Provisional becomes Confirmed
Independent web verification of load-bearing site claims; per-director adverse media and namesake court; sanctions screening; world-similarity graph. Show a visible queue ("deep checks 14 of 30, about 6 min").
### Refreshing the book is cheap
Company Enrich takes 25 companies per call; Person Enrich 25 profiles per call; Job Search with `in` on company IDs + group_by covers the whole book in one call; use Company Entity Watchers (30-day SLA) on two or three vendors as an extra trigger. A 25-vendor daily refresh is roughly 3 calls plus news checks.
### Scheduler
The planner schedules calls and credits together. Sentinel lane about one news call per vendor per day.

## 12. Optimization: minimize time and credits, maximize score
**Calls and time**
- Count calls, not just credits. With 3 people on one key, put **one shared client** (global token bucket, one cache) in front of the API so teammates do not starve each other. About 300 calls per hour in total.
- **Develop against recorded fixtures.** Record real responses once, then build the whole app on replay mode and spend live calls only on Lab runs and the demo.
- Cache by endpoint + params with TTL about 24h (records refresh every 1 to 30 days, so this loses nothing); person-level data capped at 7 days.
- Batch: 25 companies per enrich, 25 profiles per person enrich, one aggregated job search for the whole book.
- Start the fetch while enrich is running; guess standard page paths; tolerate fetch failures.
- Early exit: stop spending on a vendor once a hard contradiction (identity mismatch, sanctions hit) is found.
- Incremental refresh: skip downstream work if a record's `updated_at` is unchanged; hash fetched pages and re-extract only changed ones.
**Credits**
- Fast tier is roughly 10 to 13 credits (enrich 2, up to 7 fetch pages, person search about 2.3, web search 1, job counts free); fetch 5 pages instead of 7 to save credits. 
- Use `fields` to trim; keep `limit` small; use `limit:0` for counts; search before enrich; Identify is free; avoid premium filter groups unless needed.
- Verify only load-bearing claims first (existence, address, registration, directors, size, age); cap marketing-claim checks per vendor.
- Tiering: cheap checks for all, deep checks for the top-ranked only.
- Per-run hard credit cap; log `X-Credits-Used` per call; check `GET /account/credits` before committing.
**LLM cost and speed**
- Small model for extraction, larger only for the brief; short prompts; structured output; run LLM calls in parallel with API calls.
**Team time**
- Contract first: agree JSON schemas for fact, claim, verdict, signal and action on day one so three people build in parallel against stubs.
- Build the Attack Lab early as the test harness. Freeze scope after P0.
- Pre-warm the demo vendors (cache full, deep tier done). Show one fresh vendor live to demonstrate the 50-second Provisional answer. Do not try 20 fresh vendors on stage (about 100 calls, over 20 minutes).
**Score**
- Map everything to the rubric: fronts caught with evidence, honest firms pass, namesakes cleared. Put the Lab scorecard front and centre (fronts caught, honest vendors wrongly flagged, namesakes cleared, injections resisted, credits spent).
- Be honest: label LIVE / CACHED / SIMULATED, show `updated_at`, say that thresholds are hand-set.

## 13. Attack Lab (test set)
Use real public companies with scripted claim sets that contradict their records. Never invent facts about real people, and use only consenting people if people data is needed. Include 4 to 5 honest controls.
1. Lookalike domain; 2. zombie (old, quiet); 3. borrowed director who never worked there; 4. acquired but claims independence; 5. shrinking vendor, outside peer range; 6. shell cluster (two vendors, one director); 7. innocent namesake of a news subject; 8. honest small firm with thin data (must not be flagged); 9. prompt-injection page (no effect on verdict); 10. stale record (refresh, no alert).
**Time problem**: you cannot wait 30 days for natural change. Use an injectable clock; run the real refresh twice and show the real diff; seed vendors with recent real changes (Company Search on negative growth or recent acquisitions); apply a scripted change to a copy of a real snapshot, labelled **SIMULATED**.

## 14. Stack, modules, build order
Python FastAPI + SQLite + APScheduler; front end Next.js or plain HTML (phone-friendly briefing). Modules: `client/` (throttle, cache, credit log, record/replay), `ledger/`, `checks/`, `company/`, `people/`, `graph/`, `planner/`, `news/`, `brief/` (with validator), `actions/`, `overrides/`, `lab/`, `web/`.
- **P0** (a complete product): one-box onboarding; company pipeline C0 to C3 with claim harvest and independent verification; people pipeline P0 to P2; ledger; verdict engine; briefing + validator; action inbox; overrides; Lab with 6 to 8 archetypes.
- **P1**: P3 and P4 (background, namesake court); exposure ranking and Hold rule; credit/call planner; sentinel lane; website diff.
- **P2**: network graph Layers 1 and 2; sanctions; injection test; watchers.
- Split: (A) client, scheduler, planner, snapshots, company pipeline; (B) ledger, verdict engine, ranking, Lab, people pipeline; (C) news/namesake court, briefing writer and validator, UI, demo mode.

## 15. First actions
1. Run `GET /account/endpoints` and `GET /account/credits` (free). Confirm Identify, Enrich, Person Search, Web and `people` access, and whether the 5 rpm limit is per endpoint.
2. By hand (or via the MCP server), run the five-call fast tier on one known company and record the responses as fixtures.
3. Confirm: Identify's exact request fields; the values `basic_info.status` holds; the combined Person Search leadership filter; RDAP and Wayback reliability.
4. Pick 10 to 12 Lab vendors early.
5. Agree the fact/claim/verdict JSON schemas, then split the work.

## 16. Open questions for the user
Language preference (Python vs TypeScript)? Hours left? Which pipeline starts first? Does the key have Batch Verify, live endpoints, or social access? Is the 5 rpm limit per endpoint or global?
