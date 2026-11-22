import sys, pytest; sys.path.insert(0, ".")
import core, pipeline, policy, decision
from tests.fakes import FakeSources

@pytest.fixture
def db(tmp_path): return core.connect(str(tmp_path / "t.db"))
REQ = {"vendor_name": "Acme Logistics Pvt Ltd", "website": "acme.in", "claimed_director": "Dir One"}
def hit(**kw): return {"dated": True, "names_target": True, "discriminator": True, "source_ok": True, "severity": 3, "url": "https://news.example/closed", "says": ["struck_off"], **kw}
def adv(*hits): return {"state": "searched", "searches_run": 3, "hits": list(hits), "sources": ["crustdata:/web/search/live"]}
GOOD = {"identify": {"found": True, "status": "active", "name_similarity": 1.0, "top_ties": 1, "domain_match": True, "sources": ["crustdata:/company/identify"]},
        "profile": {"headcount_total": 400, "headcount_trend_pct": 2.0, "series_age_days": 6, "jobs_90d": 5, "traffic_present": True, "sources": ["crustdata:/company/enrich"]}}

def test_dated_sourced_report_of_closure_conflicts_with_exists_and_active():
    checks = policy.evaluate({**GOOD, "adverse": adv(hit(severity=2))})       # severity 2: not a rejection, but a conflict
    for c in ("exists", "active"):
        r = checks[c]
        assert r["status"] == "unknown" and r["reason"].startswith("sources conflict:") and r["conflict"]
        assert "https://news.example/closed" in r["sources"] and len(r["sources"]) >= 2 and "struck_off" in r["reason"]

def test_conflict_makes_verdict_cannot_verify_not_cleared(db):
    res = pipeline.run_request(db, REQ, FakeSources(adverse=adv(hit(severity=2))))
    assert res["verdict"] == "CANNOT_VERIFY" and db.execute("SELECT COUNT(*) FROM actions").fetchone()[0] == 0

def test_undated_or_unsourced_report_is_not_a_conflict_trigger():
    for h in (hit(dated=False, severity=2), hit(url=None, severity=2), hit(names_target=False, severity=2), hit(says=[], severity=2)):
        checks = policy.evaluate({**GOOD, "adverse": adv(h)})
        assert not checks["exists"].get("conflict") and not checks["active"].get("conflict")
        assert checks["adverse_media"]["status"] in ("unknown", "pass")

def test_identify_says_deleted_but_profile_shows_activity():
    sig = {**GOOD, "identify": {**GOOD["identify"], "status": "deleted"}, "adverse": adv()}
    checks = policy.evaluate(sig)
    assert checks["active"]["status"] == "unknown" and checks["active"]["reason"].startswith("sources conflict: identify says status deleted")
    assert set(checks["active"]["sources"]) >= {"crustdata:/company/identify", "crustdata:/company/enrich"}

def test_identify_says_active_but_headcount_collapsed():
    sig = {**GOOD, "profile": {**GOOD["profile"], "headcount_trend_pct": -50.0}, "adverse": adv()}
    r = policy.evaluate(sig)["active"]
    assert r["status"] == "unknown" and "sources conflict" in r["reason"] and "-50.0%" in r["reason"]

def test_no_conflict_when_sources_agree():
    checks = policy.evaluate({**GOOD, "adverse": adv()})
    assert all(not c.get("conflict") for c in checks.values()) and checks["active"]["status"] == "pass"

def test_conflict_terms_are_a_parameter():
    p = {**policy.PROPOSED_PARAMS, "conflict_adverse_terms": "insolvent"}
    assert not policy.evaluate({**GOOD, "adverse": adv(hit(severity=2))}, p)["exists"].get("conflict")

def test_fail_without_enough_sources_downgrades():
    p = {**policy.PROPOSED_PARAMS, "reject_min_sources": 2}
    sig = {**GOOD, "director": {"found": True, "contradicted": True, "sources": ["https://registry.example/one"]}, "adverse": adv()}
    assert policy.evaluate(sig, p)["director_match"]["status"] == "unknown"
    assert policy.evaluate(sig)["director_match"]["status"] == "fail"
