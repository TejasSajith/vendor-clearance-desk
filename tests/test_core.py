import sys, pytest; sys.path.insert(0, ".")
import core, decision as d

@pytest.fixture
def db(tmp_path): return core.connect(str(tmp_path / "t.db"))

def test_unsourced_fact_refused(db):
    rid = core.start_run(db, "x")
    with pytest.raises(core.UnsourcedFact):
        core.add_fact(db, rid, "Acme", "founded", 2010, "", "", "web", "2026-11-22")

def test_resume_skips_done_step(db):
    rid = core.start_run(db, "x"); calls = []
    core.run_step(db, rid, "identify", lambda: calls.append(1) or {"id": 1})
    core.start_run(db, "x", run_id=rid)                       # "restart"
    assert core.run_step(db, rid, "identify", lambda: calls.append(1) or {"id": 2}) == {"id": 1}
    assert len(calls) == 1

def test_action_runs_once_after_approval(db):
    rid = core.start_run(db, "x"); sent = []
    k1 = core.propose_action(db, rid, "email", {"to": "a@b.c"})
    k2 = core.propose_action(db, rid, "email", {"to": "a@b.c"})   # retry => same key
    assert k1 == k2
    assert not core.execute_action(db, k1, lambda *a: sent.append(a))  # not approved yet
    core.set_approval(db, k1)
    assert core.execute_action(db, k1, lambda *a: sent.append(a))
    assert not core.execute_action(db, k1, lambda *a: sent.append(a))  # second time: no-op
    assert len(sent) == 1

def test_cost_limit(db, monkeypatch):
    monkeypatch.setitem(core.CONFIG, "max_cost_credits_per_run", 1)
    rid = core.start_run(db, "x")
    core.tracked_call(db, rid, "company/identify", {}, lambda: 1, credits=0.8)
    with pytest.raises(core.LimitExceeded):
        core.tracked_call(db, rid, "company/enrich", {}, lambda: 1, credits=0.5)
    assert core.run_cost(db, rid) == pytest.approx(0.8)

ok = lambda: {"status": "pass", "reason": "r", "sources": ["u"], "confidence": 1.0}
def test_decisions():
    all_ok = {c: ok() for c in ["exists", "active", "director_match", "adverse_media"]}
    assert d.decide(all_ok).verdict == d.CLEARED
    assert d.decide({**all_ok, "active": {"status": "fail", "reason": "closed", "sources": ["u"]}}).verdict == d.REJECTED
    assert d.decide({**all_ok, "director_match": {"status": "unknown", "reason": ""}}).verdict == d.CANNOT_VERIFY
    low = {**all_ok, "exists": {**ok(), "confidence": 0.5}}
    assert d.decide(low).verdict == d.CANNOT_VERIFY
