import sys, pytest; sys.path.insert(0, ".")
import core, pipeline, decision
from tests.fakes import FakeSources

@pytest.fixture
def db(tmp_path): return core.connect(str(tmp_path / "t.db"))
REQ = {"vendor_name": "Acme Logistics Pvt Ltd", "website": "acme.in", "claimed_director": "Dir One"}

def test_cost_cap_stops_after_first_call_and_lists_unfinished_checks(db, monkeypatch):
    monkeypatch.setitem(core.CONFIG, "max_cost_credits_per_run", 1)
    src = FakeSources(cost=2.0)                       # the first call alone exceeds the cap
    res = pipeline.run_request(db, REQ, src)          # must not raise
    assert src.calls == ["/company/identify"]
    assert res["status"] == "stopped_at_cap" and res["verdict"] == decision.CANNOT_VERIFY
    d = res["decision"]
    assert {"active (not run: cap reached)", "director_match (not run: cap reached)", "adverse_media (not run: cap reached)"} <= set(d["missing"])
    assert "2 credits" in d["reasons"][0]["text"] and " s;" in d["reasons"][0]["text"] and "not run: active, director_match, adverse_media" in d["reasons"][0]["text"]
    assert db.execute("SELECT COUNT(*) FROM actions").fetchone()[0] == 0

def test_ledger_reconciles_after_cap(db, monkeypatch):
    monkeypatch.setitem(core.CONFIG, "max_cost_credits_per_run", 0.5)
    res = pipeline.run_request(db, REQ, FakeSources(cost=0.2))
    rows = db.execute("SELECT credits FROM calls WHERE run_id=?", (res["run_id"],)).fetchall()
    assert res["status"] == "stopped_at_cap" and len(rows) == 3
    assert sum(r[0] for r in rows) == pytest.approx(core.run_cost(db, res["run_id"])) == pytest.approx(res["decision"]["cost_credits"]) == pytest.approx(0.6)
    assert db.execute("SELECT status FROM runs WHERE id=?", (res["run_id"],)).fetchone()[0] == "stopped_at_cap"

def test_sourced_fail_in_finished_check_is_shown_but_a_person_decides(db, monkeypatch):
    monkeypatch.setitem(core.CONFIG, "max_cost_credits_per_run", 0.5)
    contradicted = {"found": True, "company_id_match": True, "start_date_plausible": True, "same_name_candidates": 1,
                    "discriminators_agree": True, "contradicted": True, "sources": ["https://registry.example/rec"]}
    res = pipeline.run_request(db, REQ, FakeSources(cost=0.2, director=contradicted))
    assert res["checks"]["director_match"]["status"] == "fail" and res["checks"]["adverse_media"]["status"] == "not_run"
    assert res["verdict"] == decision.CANNOT_VERIFY and res["status"] == "stopped_at_cap"
    texts = [r["text"] for r in res["decision"]["reasons"]]
    assert any("FAIL, evidence for a person" in t for t in texts)
    assert db.execute("SELECT COUNT(*) FROM actions").fetchone()[0] == 0

def test_time_cap_never_raises(db, monkeypatch):
    monkeypatch.setitem(core.CONFIG, "max_seconds_per_run", -1)
    src = FakeSources()
    res = pipeline.run_request(db, REQ, src)
    assert src.calls == [] and res["status"] == "stopped_at_cap" and res["verdict"] == decision.CANNOT_VERIFY
    assert "exists (not run: cap reached)" in res["decision"]["missing"]
