import sys; sys.path.insert(0, ".")
import policy
from checks import crosschecks as X

def checks(e="pass", a="pass", v="pass"):
    r = lambda s: {"status": s, "reason": "r", "sources": ["u"]}
    return {"exists": r(e), "active": r(a), "director_match": r("unknown"), "adverse_media": r(v)}

def test_defaults_change_nothing():
    c = X.apply(checks(e="unknown", a="unknown"), {"results_scanned": 0}); assert c["adverse_media"]["status"] == "pass"

def test_adverse_pass_needs_exists_and_active_when_switched_on():
    p = {"adverse_pass_needs_exists": True}
    assert X.apply(checks(e="unknown"), {"results_scanned": 9}, p)["adverse_media"]["status"] == "unknown"
    assert X.apply(checks(a="unknown"), {"results_scanned": 9}, p)["adverse_media"]["status"] == "pass"
    assert X.apply(checks(a="unknown"), {"results_scanned": 9}, {"adverse_pass_needs_active": True})["adverse_media"]["status"] == "unknown"

def test_min_results_scanned():
    assert X.apply(checks(), {"results_scanned": 3}, {"adverse_min_results_scanned": 5})["adverse_media"]["status"] == "unknown"
    assert X.apply(checks(), {"results_scanned": 5}, {"adverse_min_results_scanned": 5})["adverse_media"]["status"] == "pass"

def test_only_a_pass_can_be_downgraded_and_never_to_pass_or_fail():
    for v in ("unknown", "fail", "unreachable"):
        c = X.apply(checks(e="unknown", v=v), {"results_scanned": 0}, {"adverse_pass_needs_exists": True, "adverse_min_results_scanned": 50})
        assert c["adverse_media"]["status"] == v
    for e in ("pass", "unknown", "fail"):
        for a in ("pass", "unknown"):
            out = X.apply(checks(e=e, a=a), {"results_scanned": 0}, {"adverse_pass_needs_exists": True, "adverse_pass_needs_active": True, "adverse_min_results_scanned": 99})["adverse_media"]["status"]
            assert out in ("pass", "unknown")
