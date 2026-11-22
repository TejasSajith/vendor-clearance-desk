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

def test_unreachable_is_hold_not_clean():
    all_ok = {c: ok() for c in ["exists", "active", "director_match", "adverse_media"]}
    r = d.decide({**all_ok, "adverse_media": {"status": "unreachable", "reason": "timeout"}})
    assert r.verdict == d.HOLD

def test_reject_and_clear_wait_for_approval(db):
    rid = core.start_run(db, "x")
    all_ok = {c: ok() for c in ["exists", "active", "director_match", "adverse_media"]}
    k = core.finalize(db, rid, d.decide(all_ok))
    assert db.execute("SELECT status FROM actions WHERE key=?", (k,)).fetchone()[0] == "pending"
    assert core.finalize(db, rid, d.decide({})) is None   # cannot verify => no action

def test_cost_from_response(db):
    rid = core.start_run(db, "x")
    core.tracked_call(db, rid, "company/enrich", {}, lambda: {"credits": 0.5}, credits_from=lambda o: o["credits"])
    assert core.run_cost(db, rid) == 0.5

def test_cache_hit_costs_nothing(db):
    rid = core.start_run(db, "x"); n = []
    f = lambda: n.append(1) or {"credits": 2}
    core.cached_call(db, rid, "/company/enrich", {"id": 1}, f, credits_from=lambda o: o["credits"])
    core.cached_call(db, rid, "/company/enrich", {"id": 1}, f, credits_from=lambda o: o["credits"])
    assert len(n) == 1 and core.run_cost(db, rid) == 2

def test_throttle_waits_at_limit(monkeypatch):
    t = {"v": 1000.0}; slept = []
    monkeypatch.setitem(core._clock, "now", lambda: t["v"])
    monkeypatch.setitem(core._clock, "sleep", lambda s: (slept.append(s), t.__setitem__("v", t["v"] + s)))
    core._windows.clear()
    for _ in range(5): core.throttle("/person/enrich")
    assert not slept
    core.throttle("/person/enrich")          # 6th call within a minute must wait
    assert slept and slept[0] > 59
