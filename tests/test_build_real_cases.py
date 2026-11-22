import json, re, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "evaluation"))
import build_real_cases as b
import policy, decision

def test_headcount_trend_uses_point_about_180_days_back():
    ts = [{"date": "2026-01-01", "employee_count": 100}, {"date": "2026-05-01", "employee_count": 120}, {"date": "2026-11-01", "employee_count": 90}]
    assert b.headcount_trend(ts) == -25.0      # 2026-05-01 is the latest point at least 180 days before 2026-11-01 (184 d): 120 -> 90
    assert b.headcount_trend(ts[:1]) is None and b.headcount_trend([]) is None

def test_series_age():
    assert b.series_age_days([{"date": "2026-11-02", "employee_count": 1}]) == 20 and b.series_age_days([]) is None

def _ident(items): return [{"matches": [{"confidence_score": s, "company_data": {"basic_info": {"crustdata_company_id": i, "name": n}}} for i, n, s in items]}]

def test_identify_ties_and_domain_match():
    by_name = _ident([(1, "Acme Freight", 1.0), (2, "Acme Freight", 1.0), (3, "Acme Cargo", 0.6)])
    sig = b.identify_signals("Acme Freight", "acme.example", by_name, _ident([(2, "Other", 1.0)]), "active")
    assert sig["top_ties"] == 2 and sig["domain_match"] is False and sig["name_similarity"] == 1.0
    assert b.identify_signals("Acme Freight", None, by_name, None, "active")["domain_match"] is None
    assert b.identify_signals("X", None, [{"matches": []}], None, None)["found"] is False

def test_director_signals_without_probe_are_not_found():
    assert b.director_signals(None, 1, "Acme")["found"] is False
    pd = {"basic_profile": {"headline": "CEO at Acme Freight"}, "experience": {"employment_details": {"current": [
          {"crustdata_company_id": 1, "start_date": "2020-01-01T00:00:00+00:00"}]}}}
    d = b.director_signals(pd, 1, "Acme Freight")
    assert d["company_id_match"] and d["start_date_plausible"] and d["discriminators_agree"]
    assert not b.director_signals(pd, 2, "Acme Freight")["found"]

def test_hit_flags_never_claim_confirmation():
    h = b.hit_from_result({"title": "Acme blacklisted", "snippet": "10 April 2024 — x", "url": "https://news.example/a"}, "Acme Freight")
    assert h["severity"] == 3 and h["dated"] and h["names_target"] and h["url_host"] == "news.example"
    assert h["discriminator"] is False and h["source_ok"] is False

REAL = json.loads((ROOT / "evaluation" / "cases_real.json").read_text())

def test_real_cases_shape_and_no_personal_data():
    assert len(REAL) == 10 and all(c["synthetic"] is False and c["expected"] == "" for c in REAL)
    assert all(c["proposed_expected"] and c["basis"] for c in REAL)
    text = (ROOT / "evaluation" / "cases_real.json").read_text().lower()
    assert "linkedin" not in text and "http" not in text and "snippet" not in text

def test_real_cases_run_through_policy():
    for c in REAL:
        assert decision.decide(policy.evaluate(c["signals"], policy.PROPOSED_PARAMS, c["risk_tier"])).verdict
