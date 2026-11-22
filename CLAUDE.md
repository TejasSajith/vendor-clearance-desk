# CLAUDE.md
Read `AGENTS.md` first: it is the authoritative rule set, including the rule that **Tejas decides every large design and parameter choice** (log it in `DECISIONS.md` as PROPOSED and stop to ask). Then read `DECISIONS.md`, `plan.md` and `handover.md`.

Claude Code specifics:
- Python 3, SQLite, CLI first. Run `python -m pytest -q` before every commit; commit in small steps and push (prefixes in AGENTS.md section 4).
- Before using a Crustdata endpoint, check `probe/REPORT.md` for the real field names and cost. Use `core.cached_call` for every external call.
- Report back to Tejas after each task: what changed, tests run, credits spent, and any decision you need.
