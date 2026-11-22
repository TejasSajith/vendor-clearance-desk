import csv, json, sqlite3, sys; sys.path.insert(0, "."); sys.path.insert(0, "evaluation")
import rebuild_adverse_signals as R
import core
from checks import adverse

def seed_cache(db, name, results_by_query, repeat=0):
    for (suffix, src), rs in zip(R.QUERIES, results_by_query):
        body = {"query": f"{name}{suffix}", "sources": [src], "location": "IN"}
        db.execute("INSERT INTO cache VALUES(?,?,?)", (R.cache_key(body, repeat), json.dumps({"credits": 1.0, "body": {"results": rs}}), 0))

def test_rebuild_from_saved_responses_with_no_calls_and_no_text(tmp_path):
    db = core.connect(str(tmp_path / "t.db"))
    seed_cache(db, "Acme Freight Services", [[{"title": "Acme Freight Services fraud case", "snippet": "10 April 2024 — x", "url": "https://www.livemint.com/a", "position": 1, "source": "web"}], [], [], []])
    seed_cache(db, "Acme Freight Services", [[], [], [], []], repeat=1)
    csvp = tmp_path / "c.csv"; csvp.write_text("case_id,vendor_name,website\nc001,Acme Freight Services,acme.in\n")
    doc = {"rows": {"c001": {"adverse": {"old": True}, "profile": {"headcount_total": 10}}}, "repeats": {"c001": {"t": 0}}}
    n = R.rebuild(doc, list(csv.DictReader(open(csvp))), sqlite3.connect(str(tmp_path / "t.db")))
    a = doc["rows"]["c001"]["adverse"]
    assert n == 1 and "old" not in a and a["searches_run"] == 4 and a["results_scanned"] == 1 and a["rules_version"] == doc["rules_version"]
    f = a["per_search"][0]["results"][0]
    assert f["cls"] == "news_outlet" and f["phrase"] and f["dated"] and "url" not in f and "title" not in f and "snippet" not in f
    assert doc["repeats"]["c001"]["1"]["results_scanned"] == 0 and doc["rebuilt_with"].endswith("rebuild_adverse_signals.py")
    assert db.execute("SELECT COUNT(*) FROM calls").fetchone()[0] == 0                       # no paid call was made
    sig = adverse.derive_signals(a["per_search"], "Acme Freight Services", None, 10)
    assert len(sig["hits"]) == 1 and sig["hits"][0]["source_class"] == "news_outlet"

def test_rebuild_leaves_rows_without_saved_responses_alone(tmp_path):
    db = core.connect(str(tmp_path / "t.db"))
    doc = {"rows": {"c001": {"adverse": {"keep": True}}}}
    R.rebuild(doc, [{"case_id": "c001", "vendor_name": "Nobody", "website": ""}], sqlite3.connect(str(tmp_path / "t.db")))
    assert doc["rows"]["c001"]["adverse"] == {"keep": True}
