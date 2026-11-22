import sys, pytest; sys.path.insert(0, ".")
import core, pipeline, policy, decision
from tests.fakes import FakeSources

@pytest.fixture
def db(tmp_path): return core.connect(str(tmp_path / "t.db"))
REQ = {"vendor_name": "Brand New Carriers", "website": "newco.in", "claimed_director": "Dir One"}

def test_policy_no_candidate_is_unknown_never_a_fail():
    r = policy.evaluate({"identify": {"found": False, "sources": ["crustdata:/company/identify"]}})["exists"]
    assert r["status"] == "unknown" and r["reason"] == "No record found. The vendor may be too new or too small for the data source"
    assert "independent registry evidence (CIN/GSTIN/incorporation certificate)" in r["missing"]

def test_not_found_flows_to_cannot_verify_with_registry_missing(db):
    res = pipeline.run_request(db, REQ, FakeSources(candidates=[]))
    assert res["verdict"] == "CANNOT_VERIFY" and res["checks"]["exists"]["status"] == "unknown"
    assert "independent registry evidence (CIN/GSTIN/incorporation certificate)" in res["decision"]["missing"]
    assert db.execute("SELECT COUNT(*) FROM actions").fetchone()[0] == 0           # nothing to approve

@pytest.mark.parametrize("exc", [core.TransientError("timeout"), core.RateLimited(None)])
def test_timeout_is_unreachable_and_holds_never_not_found(db, monkeypatch, exc):
    monkeypatch.setitem(core._clock, "sleep", lambda s: None)
    res = pipeline.run_request(db, REQ, FakeSources(identify_exc=exc))
    assert res["checks"]["exists"]["status"] == "unreachable"
    assert res["verdict"] == decision.HOLD and res["status"] == "held"
    assert "No record found" not in str(res)

def test_held_run_retries_the_source_on_resubmission(db, monkeypatch):
    monkeypatch.setitem(core._clock, "sleep", lambda s: None)
    pipeline.run_request(db, REQ, FakeSources(identify_exc=core.TransientError("down")))
    res = pipeline.run_request(db, REQ, FakeSources(candidates=[{"id": 9, "name": "Brand New Carriers", "score": 1.0}]))   # source is back
    assert res["checks"]["exists"]["status"] == "pass"
