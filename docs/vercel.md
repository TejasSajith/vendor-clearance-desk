# Deploying the web UI to Vercel

The Vendor Clearance Desk ships to Vercel as a **demo-only** site: the one-page UI plus the recorded,
no-cost replays. This is option (a) of DECISIONS.md **D46**.

## What runs on Vercel, and what does not
- **Demo mode** (default): recorded/synthetic fixtures replayed through the real pipeline, policy and decision
  code. No Crustdata key, no credits, no network to Crustdata.
- **Jobs run inline** inside each request (`app/server.py` sees `VERCEL=1` and switches to inline mode) because a
  serverless function cannot keep a background worker. The per-run time cap (`config.json` `max_seconds_per_run`,
  300 s) stays within Vercel's function limit.
- **Live mode is OFF on Vercel by design.** Vercel's only writable path is `/tmp`, which is wiped between
  invocations and not shared across instances. That would break the cost ledger, once-only approvals, the
  duplicate check and history — all of which the event rules require. Live runs belong on a host with a real
  disk (Render, Fly, Railway, a VM) or a hosted database (Turso/Neon); see D46.
- History shown on Vercel is **per-instance and ephemeral** (it lives in `/tmp`). That is fine for a demo.

## Files
- `api/index.py` — the serverless entry. Exposes `app = create_app(require_password=False)`.
- `vercel.json` — routes every path to the function and bundles the data files the app reads at runtime
  (`config.json`, `app/static/**`, `tests/fixtures/**`, the check modules).

## Deploy (needs a Vercel login — run these yourself)
```bash
npm i -g vercel          # if you don't have the CLI
vercel login             # interactive, one time
vercel                   # from the repo root: preview deploy
vercel --prod            # promote to the production URL
```
In this Claude Code session you can run them inline by prefixing with `!`, e.g. `!vercel`.

## Access control
- **Open demo (recommended for judges):** leave `APP_PASSWORD` unset. Anyone with the link can run the
  recorded demo; nothing is spent and no live data is touched.
- **Gated demo:** set `APP_PASSWORD` in the Vercel project (Project → Settings → Environment Variables). The
  page then asks for it, and the cookie is marked `Secure` automatically on Vercel.

## First-deploy checklist
1. `vercel` builds with `@vercel/python` and installs `requirements.txt`.
2. Open the preview URL — the demo banner should show and the four demo vendors should run.
3. If a demo run 500s with a missing-file error, widen `includeFiles` in `vercel.json` (the app reads
   `tests/fixtures/*.json` and `app/static/*`).
4. `vercel --prod` once the preview looks right.
