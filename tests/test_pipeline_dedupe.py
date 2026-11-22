import sys, pytest; sys.path.insert(0, ".")
import core, pipeline
from checks import normalize as n
from tests.fakes import FakeSources

@pytest.fixture
def db(tmp_path): return core.connect(str(tmp_path / "t.db"))

def test_normalize_name():
    assert n.normalize_name("Acme Logistics Pvt Ltd") == "acme logistics"
    assert n.normalize_name("M/s ACME LOGISTICS PRIVATE LIMITED") == "acme logistics"
    assert n.normalize_name("acme logistics") == "acme logistics"
    assert n.normalize_name("Tata & Sons Inc.") == "tata and sons"
    assert n.normalize_name("  Messrs   Foo,  Bar LLP ") == "foo bar"

def test_normalize_domain():
    for v in ["https://www.Acme.in/about?x=1", "http://acme.in", "www.acme.in.", "acme.in/path", "ops@acme.in", "ACME.IN:443"]:
        assert n.normalize_domain(v) == "acme.in", v
    assert n.normalize_domain("") == "" and n.normalize_domain(None) == ""

def test_key_uses_company_id_after_resolution_and_name_before():
    assert n.request_key("c", company_id=7) == n.request_key("c", company_id=7)
    assert n.request_key("c", name="Acme Pvt Ltd", domain="www.acme.in") == n.request_key("c", name="M/s ACME PRIVATE LIMITED", domain="https://acme.in")
    assert n.request_key("c", company_id=7) != n.request_key("other", company_id=7)

def _actions(db): return db.execute("SELECT COUNT(*) FROM actions").fetchone()[0]

def test_three_spellings_give_one_run_and_one_action(db):
    src = FakeSources()
    results = [pipeline.run_request(db, {"vendor_name": v, "website": "acme.in", "claimed_director": "Dir One"}, src)
               for v in ["Acme Logistics Pvt Ltd", "M/s ACME LOGISTICS PRIVATE LIMITED", "acme logistics"]]
    assert len({r["run_id"] for r in results}) == 1
    assert results[0]["verdict"] == "CLEARED" and _actions(db) == 1
    assert [r["existing"] for r in results] == [False, True, True]
    assert db.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1

def test_same_company_under_different_name_is_caught_after_resolution(db):
    src = FakeSources()
    a = pipeline.run_request(db, {"vendor_name": "Acme Logistics Pvt Ltd", "website": "acme.in", "claimed_director": "Dir One"}, src)
    b = pipeline.run_request(db, {"vendor_name": "Acme Freight Services", "claimed_director": "Dir One"}, src)   # resolves to the same id
    assert b["existing"] and b["duplicate_of"] == a["run_id"] and _actions(db) == 1

def test_genuinely_different_companies_stay_separate(db):
    a = pipeline.run_request(db, {"vendor_name": "Acme Logistics", "website": "acme.in", "claimed_director": "D"},
                             FakeSources(candidates=[{"id": 1, "name": "Acme Logistics", "score": 1.0}]))
    b = pipeline.run_request(db, {"vendor_name": "Acme Logistic Services", "website": "acme-services.in", "claimed_director": "D"},
                             FakeSources(candidates=[{"id": 2, "name": "Acme Logistic Services", "score": 1.0}]))
    assert a["run_id"] != b["run_id"] and _actions(db) == 2
