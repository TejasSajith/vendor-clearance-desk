# Vendor Clearance Desk — brief

**One line:** an agent that clears a new carrier/supplier for a mid-size Indian 3PL — it checks the vendor
exists, is active, is run by the claimed director, and has no adverse media, then returns a **sourced
recommendation held for a human's approval**.

## What it does today
- Takes a request in plain English ("Check Delhivery, delhivery.com, director X, high risk"), parses it to
  fields, and runs **four checks** on **live Crustdata data**: **Exists** (Identify + our own name-similarity
  match), **Active** (Enrich headcount history + Job Search + web traffic), **Director match** (Person Search →
  company-ID link), **Adverse media** (4 distinct, name-scoped web/news searches).
- **Deterministic rules decide the verdict** (`policy.py`/`decision.py`); the LLM only translates English↔fields
  and writes the memo — it never decides.
- Emits **CLEARED / REJECTED / CANNOT_VERIFY / HOLD**, every claim carrying its **source + record date**; where
  nothing settles a question it says `CANNOT_VERIFY` and names what is missing (a wrong answer costs more than an
  honest "can't verify").
- Enforces **a credit cap and time cap per run**, logs **every call in a ledger**, is **resumable and
  exactly-once** (survives a crash/timeout), and treats a **timeout as "unreachable," never "nothing found."**
- Ships a **one-page web UI** (demo mode = free recorded replays; live mode = real credits behind a confirm)
  and a CLI.

## Where it still needs a person
- **Every irreversible action:** clearing or rejecting a vendor is only a recommendation → queued for human
  Approve/Reject; nothing executes until a person decides.
- **CANNOT_VERIFY / HOLD** go straight to a person.
- **Ambiguous identity** (name ties, a domain pointing to a different company), **director-of-record** (no
  DIN/MCA data; "current" roles can be stale), and **adverse media** (namesakes, undated snippets, Google-redirect
  URLs) all defer to human judgment.
- **Registry facts** (CIN/GSTIN existence/closure) are not in the data source — flagged "needs registry check."

## Approaches considered → chosen
- **Framing:** continuous monitoring ("Tripwire") vs one-shot "Clearance Desk" → hybrid, Clearance-Desk core (D19).
- **Decider:** LLM-scored vs deterministic rules → deterministic rules, LLM translate-only (trust/auditability).
- **Registry source** (D9): aggregator pages / MCA-KYC API / none → aggregators blocked (Cloudflare, need a CIN)
  → currently none, report CANNOT_VERIFY.
- **Adverse source** (D10/D41): Crustdata web search for discovery only, with **source-class gating** — only
  regulator/court/news can push toward a fail; forums/UGC shown as "unverified chatter."
- **Tuning:** report-only (`run_eval --compare`) before any threshold becomes a default; Tejas decides every
  parameter (D1–D46).
- **Hosting** (D46): all-on-Vercel breaks the stateful ledger → static page + recorded demo on Vercel; live runs
  on a host with a disk.

## Models & tools used
- **Data:** Crustdata API — Company Identify / Enrich / Job Search / Person Search / Web Search Live.
- **LLM (translate-only):** Google **Gemini** (`gemini-3.8-flash`, proposed D36) via `llm.py`, with a **code
  fallback** (`nl.py`) so it runs with no key; every model call is ledgered.
- **Stack:** Python 3, **SQLite** (durable ledger/state), **FastAPI + vanilla JS** UI, **Docker**, **Vercel**
  (demo). Built with Claude Code (Claude Sonnet 5.5 and Opus 4.8) during the event.

## What we would build next
1. **Real registry integration** — MCA/GST (CIN/GSTIN/DIN, status, directors-of-record) to turn most
   `CANNOT_VERIFY`s into verifiable pass/fail.
2. **Stronger adverse media** — a news API + eCourts/NCLT/SEBI feeds with resolvable, dated sources; resolve the
   Google-redirect URLs.
3. **Tune the policy** on the live signals collected (29+ vendors) once labelled.
4. **Durable Vercel split** (hosted DB for live) + a multi-key shared throttle so a team does not starve one key.
5. **Lookalike/ring detection** (homoglyphs, shared address/certificate numbers) and confidence decay
   (freshness-aware verdicts).
