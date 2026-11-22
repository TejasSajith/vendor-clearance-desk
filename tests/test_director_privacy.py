import json, logging, sys, pytest; sys.path.insert(0, ".")
from pathlib import Path
import core, pipeline
from tests.fakes import FakeSources

NAME = "Zorblax Quimbly"
REQ = {"vendor_name": "Acme Logistics Pvt Ltd", "website": "acme.in", "claimed_director": NAME}

def _all_bytes(folder):
    return b"".join(p.read_bytes() for p in Path(folder).rglob("*") if p.is_file())

def test_name_is_never_in_db_logs_or_output_files_and_raw_person_response_is_purged(tmp_path, caplog, capsys):
    caplog.set_level(logging.DEBUG)
    dbfile = tmp_path / "t.db"; db = core.connect(str(dbfile))
    res = pipeline.run_request(db, REQ, FakeSources())
    out = json.dumps(res)
    assert res["checks"]["director_match"]["status"] == "pass" and res["verdict"] == "CLEARED"
    assert NAME not in out and NAME.lower() not in out.lower()
    # the call log holds a redacted hash, never the params
    params = [r[0] for r in db.execute("SELECT params FROM calls WHERE endpoint='/person/enrich'")]
    assert len(params) == 1 and "redacted" in params[0] and NAME not in params[0] and "Quimbly" not in params[0]
    # raw person response purged from the cache at the end of the run
    assert db.execute("SELECT COUNT(*) FROM sensitive_keys").fetchone()[0] == 0
    assert all(NAME not in (r[0] or "") for r in db.execute("SELECT response FROM cache"))
    # only a salted hash and the match result are stored
    row = db.execute("SELECT salted_hash, result FROM director_checks").fetchone()
    import hashlib
    assert row[1] == "pass" and len(row[0]) == 64 and row[0] != hashlib.sha256(NAME.lower().encode()).hexdigest()
    assert row[0] == core.salted_hash(db, NAME) and row[0] == core.salted_hash(db, "  zorblax   QUIMBLY ")
    db.close()
    blob = _all_bytes(tmp_path)                                # database file(s) and anything else written next to it
    assert b"Zorblax" not in blob and b"Quimbly" not in blob and b"zorblax" not in blob.lower()
    assert NAME not in caplog.text and NAME not in capsys.readouterr().out

def test_other_tables_never_hold_the_name(tmp_path):
    db = core.connect(str(tmp_path / "t.db")); pipeline.run_request(db, REQ, FakeSources())
    for (t,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
        for row in db.execute(f"SELECT * FROM {t}"): assert "Quimbly" not in json.dumps(row, default=str), t

def test_different_claimed_director_is_a_different_request_but_same_one_dedupes(tmp_path):
    db = core.connect(str(tmp_path / "t.db")); src = FakeSources()
    a = pipeline.run_request(db, REQ, src); b = pipeline.run_request(db, REQ, src)
    c = pipeline.run_request(db, {**REQ, "claimed_director": "Someone Else"}, src)
    assert a["run_id"] == b["run_id"] and b["existing"] and c["run_id"] != a["run_id"]

def test_cli_takes_the_name_at_runtime_and_prints_no_name(tmp_path, capsys, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    db = str(tmp_path / "cli.db")
    rc = pipeline.main(["run", "--vendor", "Acme Logistics Pvt Ltd", "--website", "acme.in", "--db", db, "--claimed-director", NAME], sources=FakeSources())
    cap = capsys.readouterr()
    assert rc == 0 and json.loads(cap.out)["verdict"] == "CLEARED"
    assert NAME not in cap.out and NAME not in cap.err and NAME not in caplog.text and b"Quimbly" not in _all_bytes(tmp_path)
    monkeypatch.setenv("CLAIMED_DIR", NAME)
    rc = pipeline.main(["run", "--vendor", "Acme Logistics Pvt Ltd", "--website", "acme.in", "--db", db, "--claimed-director-env", "CLAIMED_DIR"], sources=FakeSources())
    assert rc == 0 and NAME not in capsys.readouterr().out

def test_cli_invalid_vendor_is_a_clean_exit(tmp_path, capsys):
    rc = pipeline.main(["run", "--vendor", "  ", "--db", str(tmp_path / "x.db")], sources=FakeSources())
    assert rc == 2 and json.loads(capsys.readouterr().out)["field"] == "vendor_name"

def test_missing_director_stores_nothing(tmp_path):
    db = core.connect(str(tmp_path / "t.db"))
    pipeline.run_request(db, {**REQ, "claimed_director": None}, FakeSources())
    assert db.execute("SELECT COUNT(*) FROM director_checks").fetchone()[0] == 0

def test_live_director_uses_a_sensitive_call_and_returns_only_booleans(tmp_path, monkeypatch):
    from checks import live
    seen = {}
    def fake_post(path, body, timeout=90, save_raw=True):
        seen.update(path=path, save_raw=save_raw)
        return {"credits": 0.1, "body": {"profiles": [{"basic_profile": {"headline": f"{NAME}, director at Acme Logistics"},
                "experience": {"employment_details": {"current": [{"crustdata_company_id": 7, "start_date": "2020-01-01T00:00:00+00:00"}]}}}]}}
    monkeypatch.setattr(live, "_post", fake_post)
    db = core.connect(str(tmp_path / "t.db")); run = core.start_run(db, "x")
    src = live.LiveSources(); src.records = {7: {"id": 7, "name": "Acme Logistics Pvt Ltd"}}
    sig = src.director(pipeline.Ctx(db, run), 7, NAME)
    assert seen == {"path": "/person/search", "save_raw": False}
    assert sig["found"] and sig["company_id_match"] and sig["discriminators_agree"] and NAME not in json.dumps(sig)
    assert "Quimbly" not in db.execute("SELECT params FROM calls").fetchone()[0]
    assert core.purge_sensitive(db, run) == 1
