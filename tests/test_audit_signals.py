import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "evaluation"))
import audit_signals as a, build_real_cases as b

TS = [{"date": "2026-01-01", "employee_count": 100}, {"date": "2026-05-01", "employee_count": 120}, {"date": "2026-11-02", "employee_count": 90}]
def _raw(**kw):
    r = {"headcount_total": 90, "timeseries": TS, "status": "active", "primary_domain": "x.example", "n_candidates": 3,
         "top_ties": 1, "domain_n": 1, "jobs_90d": 0, "traffic_present": False}; r.update(kw); return r
def _sig(**kw):
    s = {"identify": {"status": "active", "top_ties": 1, "domain_match": True},
         "profile": {"headcount_total": 90, "headcount_trend_pct": b.headcount_trend(TS), "series_age_days": 20, "jobs_90d": 0, "traffic_present": False}}
    for k, v in kw.items(): s["profile"][k] = v
    return s

def test_consistent_signals_have_no_mismatch():
    assert not [m for m in a.mismatches(_raw(), _sig()) if m.startswith("MISMATCH")]

def test_wrong_trend_and_age_are_flagged():
    flags = a.mismatches(_raw(), _sig(headcount_trend_pct=5.0, series_age_days=99))
    assert any("headcount_trend_pct" in f for f in flags) and any("series_age_days" in f for f in flags)

def test_independent_trend_matches_builder_and_formula():
    assert a.raw_trend(TS) == -25.0 == round((90 - 120) / 120 * 100, 1)

def test_real_blocks_contain_no_person_names_when_raw_exists():
    raw_dir = ROOT / "probe" / "raw"
    if not (raw_dir / "step2_enrich_5798.json").exists(): return       # raw is gitignored; skip on a clean clone
    for case in b.build():
        text = "\n".join(a.block(case, a.read_raw(case["crustdata_company_id"], raw_dir))[0]).lower()
        assert "linkedin" not in text and "http" not in text
