import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "devconsole"))
import pytest, app

@pytest.fixture(autouse=True)
def fresh(tmp_path, monkeypatch):
    app.reset(); monkeypatch.setattr(app, "DB_PATH", str(tmp_path / "c.db")); app._db = None
    yield; app.reset()

def case(id): return next(c for c in app.cases() if c["id"] == id)

def test_evaluate_matches_expected_and_params_override():
    c = case("small_thin_data")
    assert app.api_evaluate({"signals": c["signals"], "risk_tier": "low"})["verdict"] == "CANNOT_VERIFY"
    r = app.api_evaluate({"signals": c["signals"], "params": {"active_min_signals": "1"}})
    assert r["checks"]["active"]["status"] == "pass"           # parameter changed here only

def test_eval_all_and_changed_vs_default():
    r = app.api_eval({"params": {"active_min_signals": "1"}})
    assert r["metrics"]["n"] >= 19 and any(x["id"] == "small_thin_data" or x["id"] == "high_tier_two_signals" for x in r["changed_vs_default"])

def test_run_approve_crash_recover_exactly_once():
    c = case("genuine_large")
    r = app.api_run_start({"signals": c["signals"], "risk_tier": "low", "label": c["id"]})
    assert r["credits"] > 0 and len(r["facts"]) >= 3 and r["facts"][0]["source_type"] == "SIMULATED"
    key = r["actions"][0][0]; assert r["actions"][0][2] == "pending"
    assert app.api_action({"key": key, "op": "execute"})["effects"] == []                  # not approved: nothing happens
    app.api_action({"key": key, "op": "approve"})
    r = app.api_action({"key": key, "op": "crash"})
    assert r["actions"][0][2] == "executing" and r["effects"] == []
    r = app.api_action({"key": key, "op": "recover"}); assert len(r["effects"]) == 1 and r["actions"][0][2] == "done"
    r = app.api_action({"key": key, "op": "recover"}); assert len(r["effects"]) == 1
    r = app.api_action({"key": key, "op": "execute"}); assert len(r["effects"]) == 1

def test_cannot_verify_creates_no_action():
    c = case("lookalike_tie")
    assert app.api_run_start({"signals": c["signals"]})["actions"] == []
