import sys, pytest; sys.path.insert(0, ".")
import core, pipeline, policy
from tests.fakes import FakeSources

@pytest.fixture
def db(tmp_path): return core.connect(str(tmp_path / "t.db"))
def adv(**kw): return {"adverse": {"state": "searched", "searches_run": 2, "results_scanned": 10, "hits": [], "sources": ["crustdata:/web/search/live"], **kw}}

def test_pass_says_limited_coverage_and_shows_counts():
    r = policy.evaluate(adv())["adverse_media"]
    assert r["status"] == "pass"
    assert r["reason"] == "no adverse reports found in 2 searches (limited coverage); 10 results scanned"

def test_pass_never_says_clean_or_verified():
    for sig in (adv(), adv(results_scanned=None), adv(searches_run=5, results_scanned=0)):
        reason = policy.evaluate(sig)["adverse_media"]["reason"].lower()
        assert "clean" not in reason and "verified" not in reason and "limited coverage" in reason

def test_memo_reasons_carry_the_same_wording(db):
    res = pipeline.run_request(db, {"vendor_name": "Acme Logistics Pvt Ltd", "claimed_director": "D"},
                               FakeSources(adverse={"state": "searched", "searches_run": 2, "results_scanned": 7, "hits": [], "sources": ["u"]}))
    memo = " ".join(r["text"] for r in res["decision"]["reasons"]).lower()
    assert "no adverse reports found in 2 searches (limited coverage); 7 results scanned" in memo
    assert "clean" not in memo and "all clear" not in memo

def test_too_few_searches_is_unknown_with_counts():
    r = policy.evaluate(adv(searches_run=1))["adverse_media"]
    assert r["status"] == "unknown" and "1 of the 2 needed" in r["reason"]
