import json, sys, time, pytest; sys.path.insert(0, ".")
import core, decision, pipeline
from clearance import guard, ops
from tests.fakes import FakeSources

REQ = {"vendor_name": "Acme Logistics Pvt Ltd", "website": "acme.in"}

@pytest.fixture
def db(tmp_path): return core.connect(str(tmp_path / "t.db"))

def test_daily_cap_is_in_config_and_marked_proposed():
    raw = json.loads(ops.PATH.read_text(encoding="utf-8"))
    assert isinstance(raw["max_cost_credits_per_day"], (int, float)) and "PROPOSED" in raw["_max_cost_credits_per_day_status"]

def test_daily_cap_stops_new_paid_calls_and_alerts(db, capsys):
    run = core.start_run(db, "earlier")
    core.tracked_call(db, run, "/company/enrich", {}, lambda: {}, credits=5.0)   # 5 credits already spent today
    src = FakeSources(cost=0.5)
    res = pipeline.run_request(db, REQ, guard.GuardedSources(src, guard.Guard(db, daily_cap=5)))
    assert src.calls == [] and res["status"] == "stopped_at_cap" and res["verdict"] == decision.CANNOT_VERIFY
    assert db.execute("SELECT COUNT(*) FROM actions").fetchone()[0] == 0
    a = db.execute("SELECT run_id, kind, message FROM alerts").fetchall()
    assert len(a) == 1 and a[0][0] == res["run_id"] and a[0][1] == "daily_cap" and "5 of 5" in a[0][2]
    assert "ALERT [daily_cap]" in capsys.readouterr().err

def test_daily_cap_counts_only_today(db):
    run = core.start_run(db, "yesterday")
    db.execute("INSERT INTO calls(run_id,endpoint,params,status,credits,ms,ts) VALUES(?,?,?,?,?,?,?)",
               (run, "/company/enrich", "{}", "ok", 100.0, 1, guard.day_start() - 3600))
    src = FakeSources(cost=0.5)
    res = pipeline.run_request(db, REQ, guard.GuardedSources(src, guard.Guard(db, daily_cap=5)))
    assert res["status"] == "done" and len(src.calls) == 3          # yesterday's 100 credits do not count against today
    assert guard.spent_today(db) == pytest.approx(1.5)

def test_daily_cap_stops_midway_and_cached_calls_still_free(db):
    src = FakeSources(cost=1.0)
    res = pipeline.run_request(db, REQ, guard.GuardedSources(src, guard.Guard(db, daily_cap=2)))
    assert src.calls == ["/company/identify", "/company/enrich"] and res["status"] == "stopped_at_cap"
    assert "adverse_media (not run: cap reached)" in res["decision"]["missing"] and res["verdict"] == decision.CANNOT_VERIFY
    assert guard.spent_today(db) == pytest.approx(2.0)

def test_per_run_cap_alert_once_per_run(db, monkeypatch, capsys):
    monkeypatch.setitem(core.CONFIG, "max_cost_credits_per_run", 0.5)
    res = pipeline.run_request(db, REQ, guard.GuardedSources(FakeSources(cost=0.4), guard.Guard(db, daily_cap=None)))
    assert res["status"] == "stopped_at_cap"
    rows = db.execute("SELECT kind FROM alerts WHERE run_id=?", (res["run_id"],)).fetchall()
    assert rows == [("run_cost_cap",)] and capsys.readouterr().err.count("ALERT [run_cost_cap]") == 1

def test_time_cap_alert(db, monkeypatch):
    monkeypatch.setitem(core.CONFIG, "max_seconds_per_run", -1)
    res = pipeline.run_request(db, REQ, guard.GuardedSources(FakeSources(), guard.Guard(db, daily_cap=None)))
    assert res["status"] == "stopped_at_cap"
    assert db.execute("SELECT kind FROM alerts").fetchall() == [("run_time_cap",)]

def test_guard_cache_key_matches_core(db):
    run = core.start_run(db, "x")
    core.cached_call(db, run, "/company/identify", {"names": ["A"]}, lambda: {"ok": 1})
    core.cached_call(db, run, "/person/search", {"n": "A"}, lambda: {"ok": 1}, sensitive=True)
    assert db.execute("SELECT 1 FROM cache WHERE key=?", (guard.cache_key(db, "/company/identify", {"names": ["A"]}),)).fetchone()
    assert db.execute("SELECT 1 FROM cache WHERE key=?", (guard.cache_key(db, "/person/search", {"n": "A"}, sensitive=True),)).fetchone()
