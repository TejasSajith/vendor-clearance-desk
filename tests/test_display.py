import copy, sys, pytest; sys.path.insert(0, ".")
import core, display, pipeline
from tests.fakes import FakeSources

@pytest.fixture
def db(tmp_path): return core.connect(str(tmp_path / "t.db"))

@pytest.mark.parametrize("status,label", [("pass", "Passed"), ("fail", "Failed"), ("unknown", "Can't verify"),
                                          ("not_run", "Can't verify"), ("unreachable", "Couldn't reach the source"),
                                          ("weird", "Can't verify")])
def test_check_states(status, label):
    assert display.check_label("exists", {"status": status, "reason": "r", "sources": []})["label"] == label

def test_cant_verify_always_says_what_is_missing():
    for c in ({"status": "unknown", "reason": "", "sources": []}, {"status": "not_run", "reason": "cap", "sources": []},
              {"status": "unknown", "reason": "x", "missing": ["CIN"], "sources": []}):
        out = display.check_label("exists", c, ["exists (not run: cap reached)"])
        assert out["label"] == "Can't verify" and out["missing"] and all(out["missing"])

def test_conflict_and_sourced_concern_are_suspicious():
    assert display.check_label("active", {"status": "unknown", "conflict": True, "reason": "sources conflict", "sources": ["a"]})["label"] == "Suspicious"
    c = {"status": "unknown", "reason": "2 possible adverse reports, not enough to reject", "sources": ["crustdata:/web/search/live"]}
    assert display.check_label("adverse_media", c)["label"] == "Suspicious"
    assert display.check_label("adverse_media", {**c, "sources": []})["label"] == "Can't verify"     # unsourced is not a concern

@pytest.mark.parametrize("v,label", [("CLEARED", "Cleared"), ("REJECTED", "Rejected (awaiting your approval)"),
                                     ("CANNOT_VERIFY", "Can't verify"), ("HOLD_FOR_APPROVAL", "Held for approval"), ("??", "Can't verify")])
def test_overall(v, label): assert display.overall_label(v) == label

def test_display_never_changes_the_result(db):
    res = pipeline.run_request(db, {"vendor_name": "Acme Logistics Pvt Ltd", "website": "acme.in", "claimed_director": "Dir One"}, FakeSources())
    before = copy.deepcopy(res)
    out = display.display_result(res)
    assert res == before and out["verdict"] == res["verdict"] == "CLEARED" and out["overall"] == "Cleared"
    assert [c["label"] for c in out["checks"]] == ["Passed"] * 4
