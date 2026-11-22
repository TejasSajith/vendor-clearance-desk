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
    core._windows.clear(); core._seeded.clear()
    for _ in range(5): core.throttle("/person/enrich")
    assert not slept
    core.throttle("/person/enrich")          # 6th call within a minute must wait
    assert slept and slept[0] > 59


# ---- engine v2 ----
def _fake_clock(monkeypatch, start=1000.0):
    t = {"v": start}; slept = []
    monkeypatch.setitem(core._clock, "now", lambda: t["v"])
    monkeypatch.setitem(core._clock, "sleep", lambda s: (slept.append(s), t.__setitem__("v", t["v"] + s)))
    core._windows.clear(); core._seeded.clear()
    return t, slept

def test_crash_after_claim_is_finished_once_on_recovery(db):
    rid = core.start_run(db, "x"); done = []
    k = core.propose_action(db, rid, "draft_request", {"to": "vendor"}); core.set_approval(db, k)
    def dying(kind, payload, key): raise KeyboardInterrupt()          # process killed mid-action
    try: core.execute_action(db, k, dying)
    except KeyboardInterrupt: pass
    assert db.execute("SELECT status FROM actions WHERE key=?", (k,)).fetchone()[0] == "executing"
    assert core.recover_actions(db, lambda kind, p, key: done.append(key)) == [k]    # restart finishes it
    assert core.recover_actions(db, lambda kind, p, key: done.append(key)) == []     # and only once
    assert done == [k]
    assert not core.execute_action(db, k, lambda *a: done.append(1))

def test_rerun_does_not_duplicate_facts(db):
    rid = core.start_run(db, "x")
    for _ in range(2): core.add_fact(db, rid, "Acme", "status", "active", "u", "status: active", "api", "2026-11-22")
    assert len(core.facts(db, rid)) == 1

def test_quote_grounding(db):
    rid = core.start_run(db, "x")
    core.add_fact(db, rid, "A", "c", 1, "u", "Founded in 2011", "web", "d", content="<p>We were  founded in 2011.</p>".replace("<p>", "").replace("</p>", ""))
    import pytest as _p
    with _p.raises(core.UngroundedQuote):
        core.add_fact(db, rid, "A", "c2", 1, "u", "Founded in 1990", "web", "d", content="We were founded in 2011.")

def test_throttle_survives_restart(db, monkeypatch):
    t, slept = _fake_clock(monkeypatch)
    for i in range(5):                                   # five calls logged 10s ago by the "previous process"
        db.execute("INSERT INTO calls(run_id,endpoint,params,status,credits,ms,ts) VALUES('r','/person/enrich','{}','ok',1,1,?)", (t["v"] - 10,))
    core.throttle("/person/enrich", db)                  # 6th call must wait for the window, not burst
    assert slept and 49 < slept[0] < 52

def test_exact_endpoint_limit_and_account_limit(db, monkeypatch):
    t, slept = _fake_clock(monkeypatch)
    for _ in range(50): core.throttle("/company/search/autocomplete", db)     # 300/min endpoint: no waiting
    assert not slept
    monkeypatch.setitem(core.CONFIG, "account_rpm", 3); core._windows.clear(); core._seeded.clear()
    for ep in ("/company/enrich", "/person/enrich", "/job/search"): core.throttle(ep, db)
    core.throttle("/web/search/live", db)                # 4th call across endpoints hits the account-wide cap
    assert slept

def test_retry_then_success_and_then_unreachable(monkeypatch):
    t, slept = _fake_clock(monkeypatch); n = {"i": 0}
    def flaky():
        n["i"] += 1
        if n["i"] < 3: raise core.TransientError("timeout")
        return "ok"
    assert core.call_with_retry(flaky) == "ok" and slept == [2, 4]
    import pytest as _p
    with _p.raises(core.SourceUnreachable): core.call_with_retry(lambda: (_ for _ in ()).throw(core.TransientError("down")))
    slept.clear()
    r = iter([core.RateLimited(7), "ok"])
    def limited():
        v = next(r)
        if isinstance(v, Exception): raise v
        return v
    assert core.call_with_retry(limited) == "ok" and slept == [7]

def test_cache_ttl_off_by_default_and_expires_when_set(db, monkeypatch):
    t, slept = _fake_clock(monkeypatch); n = []
    f = lambda: n.append(1) or {"v": 1}
    rid = core.start_run(db, "x")
    core.cached_call(db, rid, "/person/enrich", {"a": 1}, f); t["v"] += 10**6
    core.cached_call(db, rid, "/person/enrich", {"a": 1}, f); assert len(n) == 1       # no TTL: still cached
    monkeypatch.setitem(core.CONFIG, "cache_ttl_seconds", {"default": 100})
    core.cached_call(db, rid, "/person/enrich", {"a": 1}, f); assert len(n) == 2       # expired: refetched
    assert core.purge_cache(db, 0) >= 1
