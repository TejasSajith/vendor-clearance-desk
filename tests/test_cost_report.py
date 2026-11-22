import json, sqlite3, sys, pytest; sys.path.insert(0, ".")
import core, pipeline
from finance import cost_report as cr
from clearance import guard
from tests.fakes import FakeSources

REQ = {"vendor_name": "Acme Logistics Pvt Ltd", "website": "acme.in"}
TODO_ASSUMPTIONS = {k: "TODO" for k in ("inr_per_credit", "analyst_cost_inr_per_check", "price_inr_per_check", "fixed_cost_inr_per_month",
                                        "analyst_review_cost_inr_per_check_with_service", "gemini_inr_per_1m_input_tokens", "gemini_inr_per_1m_output_tokens")}
TODO_ASSUMPTIONS.update(volumes_per_month=[100, 1000, 10000], credit_price_multipliers=[0.5, 1, 2])

def _ledger(tmp_path, name="l.db", cost=0.5):
    p = str(tmp_path / name); db = core.connect(p)
    pipeline.run_request(db, REQ, FakeSources(cost=cost))
    pipeline.run_request(db, {"vendor_name": "Bravo Freight", "website": "bravo.in"},
                         FakeSources(cost=cost, candidates=[{"id": 2, "name": "Bravo Freight", "score": 1.0}]))
    db.close(); return p

def test_per_vendor_credits_and_stats_come_from_the_ledger(tmp_path):
    p = _ledger(tmp_path)
    s = cr.summarize([p], assumptions=TODO_ASSUMPTIONS)
    assert s["per_vendor"]["n"] == 2
    db = sqlite3.connect(p)
    per_run = [r[0] for r in db.execute("SELECT SUM(credits) FROM calls GROUP BY run_id ORDER BY run_id")]
    assert sorted(v["credits"] for v in s["vendor_runs"]) == pytest.approx(sorted(per_run))
    assert s["per_vendor"]["mean"] == pytest.approx(sum(per_run) / 2)
    assert s["total_credits"] == pytest.approx(db.execute("SELECT SUM(credits) FROM calls").fetchone()[0])
    eps = s["vendor_runs"][0]["by_endpoint"]
    assert set(eps) == {"/company/identify", "/company/enrich", "/web/search/live"} and all(e["calls"] == 1 for e in eps.values())

def test_names_hidden_unless_asked(tmp_path, capsys):
    p = _ledger(tmp_path)
    cr.main([p]); out = capsys.readouterr().out
    assert "Acme" not in out and "(name hidden)" in out
    cr.main([p, "--names"]); assert "Acme Logistics" in capsys.readouterr().out

def test_reconciliation_match_and_difference_and_record(tmp_path, capsys):
    p = _ledger(tmp_path, cost=0.5)
    total = cr.summarize([p], assumptions=TODO_ASSUMPTIONS)["total_credits"]
    assert cr.reconcile({"total_credits": total}, 100, 100 - total)["result"] == "MATCH"
    assert "DIFFERENCE of 1" in cr.reconcile({"total_credits": total}, 100, 99 - total)["result"]
    assert cr.main([p, "--balance-before", "100", "--balance-after", str(100 - total)]) == 0
    assert "MATCH" in capsys.readouterr().out
    row = sqlite3.connect(p).execute("SELECT ledger_credits, difference FROM reconciliations").fetchone()
    assert row[0] == pytest.approx(total) and abs(row[1]) < 0.01

def test_cap_stopped_runs_and_model_calls_are_reported(tmp_path, monkeypatch):
    monkeypatch.setitem(core.CONFIG, "max_cost_credits_per_run", 0.5)
    p = str(tmp_path / "c.db"); db = core.connect(p)
    res = pipeline.run_request(db, REQ, FakeSources(cost=0.4))
    assert res["status"] == "stopped_at_cap"
    run = core.start_run(db, json.dumps({"kind": "nl"}), run_id="nl_x")
    core.cached_call(db, run, "/llm/generate", {"model": "m", "task": "t"}, lambda: {"text": "{}", "tokens_in": 120, "tokens_out": 30},
                     credits_from=lambda o: 0.0, log_from=lambda o: {"tokens_in": o["tokens_in"], "tokens_out": o["tokens_out"]})
    db.close()
    s = cr.summarize([p], assumptions=TODO_ASSUMPTIONS)
    assert s["cap_stopped"]["runs"] == 1 and s["cap_stopped"]["credits"] == pytest.approx(core.run_cost(core.connect(p), res["run_id"]))
    assert s["model_calls"] == {"n": 1, "tokens_in": 120, "tokens_out": 30, "cost_inr": "free tier (no price in finance/assumptions.json)"}
    priced = {**TODO_ASSUMPTIONS, "gemini_inr_per_1m_input_tokens": 10.0, "gemini_inr_per_1m_output_tokens": 40.0}
    assert cr.summarize([p], assumptions=priced)["model_calls"]["cost_inr"] == pytest.approx(120 / 1e6 * 10 + 30 / 1e6 * 40)

def test_cache_savings_logged_by_the_guard_on_a_rerun(tmp_path):
    p = str(tmp_path / "g.db"); db = core.connect(p)
    src = guard.GuardedSources(FakeSources(cost=0.5), guard.Guard(db, daily_cap=None))
    a = pipeline.run_request(db, REQ, src)
    db.execute("DELETE FROM steps WHERE run_id=?", (a["run_id"],))     # force the stages to run again: every call is a cache hit
    pipeline.run_request(db, REQ, guard.GuardedSources(FakeSources(cost=0.5), guard.Guard(db, daily_cap=None)))
    db.close()
    s = cr.summarize([p], assumptions=TODO_ASSUMPTIONS)
    assert s["cache"]["hits_logged"] == 3 and s["cache"]["credits_saved"] == pytest.approx(1.5)

def test_todo_assumptions_never_become_numbers(tmp_path):
    p = _ledger(tmp_path)
    s = cr.summarize([p], assumptions=TODO_ASSUMPTIONS)
    eco = cr.economics(s, TODO_ASSUMPTIONS)
    d = dict(eco["per_vendor"])
    for k in ("rupees per vendor at the mean (credits x inr_per_credit)", "proposed price per check (assumption)",
              "gross margin per check: price - credits cost - review"):
        assert d[k] == cr.TODO
    assert eco["break_even"].startswith(cr.TODO)
    assert all(row[2] == cr.TODO and row[3] == cr.TODO for row in eco["volumes"])
    assert [row[1] for row in eco["volumes"]] == [f"{s['per_vendor']['mean'] * n:,.2f}" for n in (100, 1000, 10000)]   # credits are known

def test_economics_with_numbers_and_worst_case(tmp_path):
    p = _ledger(tmp_path, cost=1.0)
    s = cr.summarize([p], assumptions=TODO_ASSUMPTIONS)
    a = {**TODO_ASSUMPTIONS, "inr_per_credit": 2.0, "price_inr_per_check": 100.0, "analyst_review_cost_inr_per_check_with_service": 20.0,
         "fixed_cost_inr_per_month": 1000.0}
    eco = dict(cr.economics(s, a)["per_vendor"])
    assert eco["gross margin per check: price - credits cost - review"] == f"{100 - 3 * 2 - 20:,.2f}"
    assert eco["worst case credits per vendor: per-run cap + largest single call in a vendor run (ledger)"] == f"{core.CONFIG['max_cost_credits_per_run'] + 1.0:,.2f}"
    assert cr.economics(s, a)["break_even"] == f"{-(-1000 // 74):,} vendors per month"

def test_committed_assumptions_are_todo_or_documented():
    a = cr.load_assumptions()
    for k in ("inr_per_credit", "analyst_cost_inr_per_check", "price_inr_per_check", "fixed_cost_inr_per_month"):
        assert a[k] == "TODO" or isinstance(a[k], (int, float)), k
