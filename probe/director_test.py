"""Live director test. The claimed director is taken from the command line at runtime and is never written to a file, log or output.
    python probe/director_test.py --case "VENDOR" "WEBSITE" "DIRECTOR NAME" --case "VENDOR2" "WEBSITE2" "OTHER NAME" [--append-md]
A director value of the form env:VAR reads the name from that environment variable instead (keeps it out of shell history).
Prints counts, field names, the director_match state and credits. Hard stop at 14 credits. Needs CRUSTDATA_API_KEY."""
import argparse, json, os, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import core, pipeline

LIMIT = 14.0

def resolve(value): return os.environ.get(value[4:], "") if value.startswith("env:") else value

def run_cases(cases, sources, db):
    out = []
    for vendor, site, director in cases:
        name = resolve(director)
        before = db.execute("SELECT COALESCE(SUM(credits),0) FROM calls").fetchone()[0]
        if before >= LIMIT: raise SystemExit("director test: credit guard")
        t0 = time.time()
        res = pipeline.run_request(db, {"vendor_name": vendor, "website": site, "risk_tier": "low", "claimed_director": name}, sources)
        calls = db.execute("SELECT endpoint, credits FROM calls WHERE run_id=?", (res["run_id"],)).fetchall()
        person = sum(c for e, c in calls if e == "/person/search")
        out.append({"vendor": vendor, "director_match": res["checks"]["director_match"]["status"], "reason": res["checks"]["director_match"]["reason"],
                    "verdict": res["verdict"], "person_search": getattr(sources, "stats", None), "credits_person_search": round(person, 4),
                    "credits_run": round(sum(c for _, c in calls), 4), "seconds": round(time.time() - t0, 1)})
        sources.stats = None
    return out

def markdown(rows):
    L = ["", "## 10b. Live director test (Person Search by name and employer)", "",
         "Claimed names were supplied on the command line at runtime and are not stored anywhere (the database keeps a salted hash and the match result). One correct name for a large vendor, one wrong name.", "",
         "| Vendor | director_match | Reason | Person Search results | With a current role at this company | Credits (person search / run) |", "|---|---|---|---|---|---|"]
    for r in rows:
        st = r["person_search"] or {}
        L.append(f"| {r['vendor']} | {r['director_match']} | {r['reason']} | {st.get('results')} (total_count {st.get('total_count')}) | {st.get('with_current_role_at_company')} | {r['credits_person_search']} / {r['credits_run']} |")
    fields = next((r["person_search"] for r in rows if r["person_search"] and r["person_search"].get("results")), None)
    if fields: L += ["", f"Fields returned per person: {fields['fields_present']}; `basic_profile`: {fields['basic_profile_fields']}; current-role fields: {fields['current_role_fields']}."]
    return "\n".join(L) + "\n"

def main(argv=None, sources=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--case", nargs=3, action="append", metavar=("VENDOR", "WEBSITE", "DIRECTOR"), required=True)
    ap.add_argument("--append-md", action="store_true"); ap.add_argument("--db", default=str(ROOT / "probe" / "live" / "director.db"))
    a = ap.parse_args(argv)
    if sources is None:
        from checks import live; sources = live.LiveSources()
    if Path(a.db).exists(): Path(a.db).unlink()
    db = core.connect(a.db)
    rows = run_cases(a.case, sources, db)
    md = markdown(rows); print(md)
    if a.append_md: (ROOT / "evaluation" / "live_validation.md").open("a").write(md)
    return 0

if __name__ == "__main__": raise SystemExit(main())
