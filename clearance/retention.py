"""Retention: purge_personal removes person-level data older than the retention period and keeps only hashes and results.

What it removes (older than `older_than_days`, default ops person_raw_retention_days, PROPOSED 0 = everything):
  1. raw person responses in `cache` listed in `sensitive_keys` (normally purged at the end of a run; left behind if the process died)
  2. person-endpoint (/person/...) calls whose params were logged in clear (older ledgers, probes): params become a salted hash,
     and the cached response for that request is deleted
  3. facts whose source is a person endpoint, whatever their age: passage and value become a hash
What it keeps: director_checks (salted hash + match result), the ledger rows (endpoint, status, credits, time), run results,
explanations and the audit log (none of which hold person data). secure_delete is on and the file is vacuumed afterwards, so the
deleted bytes do not stay in free pages (tests/test_retention.py scans the file).
    python scripts/purge.py --db clearance.db [--older-than-days N]
"""
import hashlib, json, time
import core
from clearance import audit, ops

def _h(db, text): return "sha256:" + hashlib.sha256((core.salt(db) + str(text)).encode()).hexdigest()[:16]

def purge_personal(db, older_than_days=None, now=None, vacuum=True, actor="retention"):
    days = ops.OPS.get("person_raw_retention_days", 0) if older_than_days is None else older_than_days
    now = time.time() if now is None else now
    cutoff = now - float(days) * 86400
    db.execute("PRAGMA secure_delete=ON")
    out = {"older_than_days": days, "raw_person_responses": 0, "person_call_params_redacted": 0, "person_facts_redacted": 0}
    for (key,) in db.execute("SELECT s.key FROM sensitive_keys s JOIN cache c ON c.key = s.key WHERE c.ts <= ?", (cutoff,)).fetchall():
        out["raw_person_responses"] += db.execute("DELETE FROM cache WHERE key=?", (key,)).rowcount
        db.execute("DELETE FROM sensitive_keys WHERE key=?", (key,))
    db.execute("DELETE FROM sensitive_keys WHERE key NOT IN (SELECT key FROM cache)")
    for cid, ep, params in db.execute("SELECT id, endpoint, params FROM calls WHERE endpoint LIKE '/person/%' AND ts <= ?", (cutoff,)).fetchall():
        try: p = json.loads(params or "null")
        except ValueError: p = params
        if isinstance(p, dict) and set(p) == {"redacted"}: continue
        if p is not None:
            k = hashlib.sha256(json.dumps([ep, p], sort_keys=True).encode()).hexdigest()
            db.execute("DELETE FROM cache WHERE key=?", (k,))
        db.execute("UPDATE calls SET params=? WHERE id=?", (json.dumps({"redacted": _h(db, params)}), cid))
        out["person_call_params_redacted"] += 1
    for fid, passage, value in db.execute("SELECT id, passage, value FROM facts WHERE (source_url LIKE '%/person/%' OR source_type='person') "
                                          "AND passage NOT LIKE 'sha256:%'").fetchall():
        db.execute("UPDATE facts SET passage=?, value=? WHERE id=?", (_h(db, passage), json.dumps(_h(db, value)), fid))
        out["person_facts_redacted"] += 1
    audit.append(db, actor, "purge_personal", None, None, out)
    if vacuum: db.execute("VACUUM")
    return out

def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="purge.py", description="Purge person-level data past the retention period")
    ap.add_argument("--db", default="clearance.db"); ap.add_argument("--older-than-days", type=float)
    a = ap.parse_args(argv)
    from clearance import service
    db = service.open_db(a.db)
    print(json.dumps(purge_personal(db, a.older_than_days)))
    return 0
