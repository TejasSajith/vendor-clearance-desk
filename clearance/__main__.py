"""python -m clearance <command> [--db clearance.db]

  run       --vendor NAME [--website URL] [--tier low|medium|high]
            [--claimed-director NAME | --claimed-director-env VAR | --claimed-director-prompt]   (never stored, logged or printed)
  queue     pending actions with the explanation a person will see
  approve   KEY --by STAFF_ID        reject  KEY --by STAFF_ID     (a person's decision; approval is recorded locally only)
  explain   RUN_ID                   the stored explanation (reasons, sources with dates, missing evidence)
  contest   RUN_ID --challenge TEXT [--website URL] [--by vendor]   records the challenge, creates a linked re-check run
  recheck   RECHECK_RUN_ID [--claimed-director...]                   runs the checks again; never changes the original verdict
  audit     [--run RUN_ID] [--limit N]
  purge     [--older-than-days N]    remove person-level data past retention (ops_config.json, PROPOSED)
  doctor    health: database, keys present (never their values), rate-limit headroom, last reconciliation, recent alerts
Live runs read CRUSTDATA_API_KEY from the environment or the gitignored .env.
"""
import argparse, getpass, json, os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

def _claimed(a):
    if getattr(a, "claimed_director", None): return a.claimed_director
    if getattr(a, "claimed_director_env", None): return os.environ.get(a.claimed_director_env)
    if getattr(a, "claimed_director_prompt", False): return getpass.getpass("Claimed director (not echoed, not stored): ")
    return None

def _director_args(p):
    g = p.add_mutually_exclusive_group()
    g.add_argument("--claimed-director"); g.add_argument("--claimed-director-env"); g.add_argument("--claimed-director-prompt", action="store_true")

def _live_sources():
    import llm
    llm.load_dotenv()
    from checks import live
    return live.LiveSources()

def main(argv=None, sources=None, out=None):
    out = out or sys.stdout
    ap = argparse.ArgumentParser(prog="python -m clearance", description="Vendor clearance service")
    ap.add_argument("--db", default="clearance.db")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run"); r.add_argument("--vendor", required=True); r.add_argument("--website"); r.add_argument("--tier", default="low"); _director_args(r)
    sub.add_parser("queue")
    for c in ("approve", "reject"):
        p = sub.add_parser(c); p.add_argument("key"); p.add_argument("--by", required=True, help="staff ID or role, not a name")
    p = sub.add_parser("explain"); p.add_argument("run_id")
    p = sub.add_parser("contest"); p.add_argument("run_id"); p.add_argument("--challenge", required=True); p.add_argument("--website"); p.add_argument("--by", default="vendor")
    p = sub.add_parser("recheck"); p.add_argument("recheck_run_id"); _director_args(p)
    p = sub.add_parser("audit"); p.add_argument("--run"); p.add_argument("--limit", type=int, default=50)
    p = sub.add_parser("purge"); p.add_argument("--older-than-days", type=float)
    sub.add_parser("doctor")
    a = ap.parse_args(argv)
    from clearance import audit, doctor, explain, retention, service
    if a.cmd == "doctor":
        rep = doctor.check(a.db); print(doctor.render(rep), file=out); return 0 if rep["ok"] else 1
    db = service.open_db(a.db)
    def show(x): print(json.dumps(x, indent=1, ensure_ascii=False, default=str), file=out)
    try:
        if a.cmd == "run":
            res = service.run_vendor(db, {"vendor_name": a.vendor, "website": a.website, "risk_tier": a.tier, "claimed_director": _claimed(a)},
                                     sources or _live_sources())
            show(res); return 2 if res.get("status") == "invalid" else 0
        if a.cmd == "queue": show(service.queue(db)); return 0
        if a.cmd in ("approve", "reject"):
            show(service.decide(db, a.key, a.cmd == "approve", a.by)); return 0
        if a.cmd == "explain":
            e = explain.get(db, a.run_id); show(e or {"error": f"no explanation stored for {a.run_id}"}); return 0 if e else 1
        if a.cmd == "contest": show(explain.contest(db, a.run_id, a.challenge, actor=a.by, website=a.website)); return 0
        if a.cmd == "recheck": show(explain.run_recheck(db, a.recheck_run_id, sources or _live_sources(), claimed_director=_claimed(a))); return 0
        if a.cmd == "audit": show(audit.entries(db, run_id=a.run, limit=a.limit)); return 0
        if a.cmd == "purge": show(retention.purge_personal(db, a.older_than_days)); return 0
    except (audit.AuditError, explain.ContestError) as e:
        show({"error": str(e)}); return 2
    finally:
        db.close()

if __name__ == "__main__": raise SystemExit(main())
