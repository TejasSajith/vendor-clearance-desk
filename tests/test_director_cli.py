import sys, pytest; sys.path.insert(0, "."); sys.path.insert(0, "probe")
from pathlib import Path
import director_test as dt
from tests.fakes import FakeSources

NAME = "Zorblax Quimbly"

class Stats(FakeSources):
    def director(self, ctx, cid, claimed):
        self.stats = {"results": 1, "total_count": 1, "with_current_role_at_company": 1, "fields_present": ["basic_profile"], "basic_profile_fields": ["headline"], "current_role_fields": ["title"]}
        return super().director(ctx, cid, claimed)

def test_director_test_outputs_no_name_and_reports_counts(tmp_path, capsys):
    rc = dt.main(["--case", "Acme Logistics Pvt Ltd", "acme.in", NAME, "--case", "Acme Logistics Pvt Ltd", "acme.in", "env:WRONG_ONE", "--db", str(tmp_path / "d.db")], sources=Stats())
    out = capsys.readouterr().out
    assert rc == 0 and "| Acme Logistics Pvt Ltd | pass |" in out and "Quimbly" not in out
    assert b"Quimbly" not in b"".join(p.read_bytes() for p in tmp_path.rglob("*") if p.is_file())

def test_env_form_reads_the_name_from_the_environment(monkeypatch):
    monkeypatch.setenv("DIRX", NAME)
    assert dt.resolve("env:DIRX") == NAME and dt.resolve("Plain") == "Plain" and dt.resolve("env:UNSET_VAR_X") == ""
