import json, sys, pytest; sys.path.insert(0, ".")
from pathlib import Path
import core, pipeline, policy
from checks import exists
from tests.fakes import FakeSources

FIX = Path(__file__).parent / "fixtures"
ECOM = json.loads((FIX / "identify_ecom_express.json").read_text(encoding="utf-8"))
ZEN = json.loads((FIX / "identify_zentrovia.json").read_text(encoding="utf-8"))
FLOOR = policy.PROPOSED_PARAMS["candidate_name_sim_floor"]

@pytest.fixture
def db(tmp_path): return core.connect(str(tmp_path / "t.db"))

def test_token_sort_ratio_ignores_word_order_and_legal_suffixes():
    assert exists.token_sort_ratio("Logistics Acme Pvt Ltd", "M/s ACME LOGISTICS LIMITED") == 1.0
    assert exists.token_sort_ratio("", "x") == 0.0

def test_ecom_express_ltd_picks_the_limited_record_by_domain():
    m = exists.match("Ecom Express Ltd", "ecomexpress.in", ECOM["candidates"], ECOM["domain_ids"], FLOOR)
    assert m["outcome"] == "tie_broken_by_domain" and m["chosen"]["id"] == 5967 and m["chosen"]["name"] == "Ecom Express Limited"
    assert len(m["above"]) > 1                         # "Ecom Express Pvt Ltd" etc. were also above the floor; the domain decided
    assert m["domain_match"] is True and m["domain_note"] is None

def test_ecom_express_without_domain_is_ambiguous_and_lists_candidates():
    m = exists.match("Ecom Express Ltd", "", ECOM["candidates"], None, FLOOR)
    assert m["outcome"] == "ambiguous" and len(m["above"]) >= 2

def test_pipeline_ecom_express_resolves_and_enriches_the_right_record(db):
    src = FakeSources(candidates=ECOM["candidates"], domain_ids=ECOM["domain_ids"])
    res = pipeline.run_request(db, {"vendor_name": "Ecom Express Ltd", "website": "ecomexpress.in"}, src)
    assert res["checks"]["exists"]["status"] == "pass"
    assert db.execute("SELECT params FROM calls WHERE endpoint='/company/enrich'").fetchone()[0] == '{"id": 5967}'

def test_ambiguous_makes_no_enrich_call_and_lists_ids_and_names(db):
    src = FakeSources(candidates=ECOM["candidates"], domain_ids=None)
    res = pipeline.run_request(db, {"vendor_name": "Ecom Express Ltd"}, src)
    r = res["checks"]["exists"]
    assert r["status"] == "unknown" and r["reason"].startswith("ambiguous match: ") and "5967 Ecom Express Limited" in r["reason"]
    assert "/company/enrich" not in src.calls and "/job/search" not in src.calls and res["verdict"] == "CANNOT_VERIFY"

def test_invented_vendor_with_25_fuzzy_candidates_is_not_found_and_makes_no_enrich_call(db):
    assert len(ZEN["candidates"]) == 25 and {c["score"] for c in ZEN["candidates"]} == {0.6}
    src = FakeSources(candidates=ZEN["candidates"])
    res = pipeline.run_request(db, {"vendor_name": ZEN["input"]}, src)
    r = res["checks"]["exists"]
    assert r["status"] == "unknown" and r["reason"] == "No record found. The vendor may be too new or too small for the data source"
    assert "independent registry evidence (CIN/GSTIN/incorporation certificate)" in res["decision"]["missing"]
    assert "/company/enrich" not in src.calls and "/job/search" not in src.calls and "/person/enrich" not in src.calls

def test_crustdata_confidence_is_ignored_for_the_choice():
    cands = [{"id": 1, "name": "Zed Freight", "score": 1.0}, {"id": 2, "name": "Acme Freight", "score": 0.1}]
    assert exists.match("Acme Freight", "", cands, None, FLOOR)["chosen"]["id"] == 2

def test_domain_mismatch_note_when_supplied_domain_differs():
    cands = [{"id": 1, "name": "Acme Freight", "domain": "acme.in"}]
    m = exists.match("Acme Freight", "other.com", cands, None, FLOOR)
    assert m["chosen"]["id"] == 1 and m["domain_match"] is False and "domain_mismatch" in m["domain_note"]
    r = policy.evaluate({"identify": pipeline.identify_signals("Acme Freight", "other.com", {"candidates": cands})})["exists"]
    assert r["status"] == "unknown" and "domain_mismatch" in r["notes"][0]

def test_floor_is_a_parameter():
    cands = [{"id": 1, "name": "Acme Freight Lines", "domain": None}]
    assert exists.match("Acme Freight", "", cands, None, 0.85)["outcome"] == "none"
    assert exists.match("Acme Freight", "", cands, None, 0.5)["outcome"] == "one"

def test_director_wording_when_there_is_no_company_record(db):
    # no candidate: no director claimed -> "no claimed director", director claimed -> "no company record" (never "not found at this company")
    a = pipeline.run_request(db, {"vendor_name": ZEN["input"]}, FakeSources(candidates=ZEN["candidates"]))
    assert a["checks"]["director_match"]["reason"] == "no claimed director in the request"
    b = pipeline.run_request(db, {"vendor_name": ZEN["input"], "claimed_director": "Some Person"}, FakeSources(candidates=ZEN["candidates"]))
    assert b["checks"]["director_match"]["reason"] == "no company record to look for the claimed director in"
    assert "Some Person" not in str(b)
