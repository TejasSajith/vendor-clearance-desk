import sys, pytest; sys.path.insert(0, ".")
import core, pipeline, policy, decision
from tests.fakes import FakeSources

@pytest.fixture
def db(tmp_path): return core.connect(str(tmp_path / "t.db"))
REQ = {"vendor_name": "Acme Logistics Pvt Ltd", "website": "acme.in", "claimed_director": "Dir One"}
HIT = {"dated": True, "names_target": True, "discriminator": True, "source_ok": True, "severity": 3, "url": "https://news.example/a"}
def adv(*hits): return {"state": "searched", "searches_run": 3, "hits": list(hits), "sources": ["crustdata:/web/search/live"]}

def test_single_undated_name_only_hit_is_cannot_verify(db):
    weak = {"names_target": True, "severity": 3, "url": "https://news.example/x", "dated": False, "discriminator": False, "source_ok": False}
    res = pipeline.run_request(db, REQ, FakeSources(adverse=adv(weak)))
    assert res["verdict"] == "CANNOT_VERIFY" and db.execute("SELECT COUNT(*) FROM actions").fetchone()[0] == 0
    why = res["checks"]["adverse_media"]["reason"]
    assert "a date" in why and "namesakes" in why and "rejection needs a dated, resolved report" in why

def test_dated_resolved_severe_sourced_hit_is_rejected_and_held_for_approval(db):
    res = pipeline.run_request(db, REQ, FakeSources(adverse=adv(HIT)))
    assert res["verdict"] == "REJECTED" and res["checks"]["adverse_media"]["sources"] == ["https://news.example/a"]
    assert db.execute("SELECT status FROM actions").fetchone()[0] == "pending"

@pytest.mark.parametrize("change,needle", [({"dated": False}, "a date"), ({"discriminator": False}, "match to the target"),
                                           ({"source_ok": False}, "verified source"), ({"severity": 2}, "severity >= 3")])
def test_each_missing_condition_blocks_rejection(change, needle):
    r = policy.evaluate({"adverse": adv({**HIT, **change})})["adverse_media"]
    assert r["status"] == "unknown" and needle in r["reason"]

def test_min_sources_and_dated_requirement_are_parameters():
    two = {**policy.PROPOSED_PARAMS, "reject_min_sources": 2}
    assert policy.evaluate({"adverse": adv(HIT)}, two)["adverse_media"]["status"] == "unknown"
    assert policy.evaluate({"adverse": adv(HIT, {**HIT, "url": "https://other.example/b"})}, two)["adverse_media"]["status"] == "fail"
    undated_ok = {**policy.PROPOSED_PARAMS, "reject_require_dated": False}
    assert policy.evaluate({"adverse": adv({**HIT, "dated": False})}, undated_ok)["adverse_media"]["status"] == "fail"

def test_hit_without_url_cannot_reject():
    assert policy.evaluate({"adverse": adv({**HIT, "url": None})})["adverse_media"]["status"] == "unknown"
