import json, subprocess, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "evaluation"))
import policy, run_eval

CASES = json.loads((Path(__file__).resolve().parent.parent / "evaluation" / "cases_synthetic.json").read_text())

def test_all_synthetic_cases_pass_with_proposed_params():
    m = run_eval.run(CASES, policy.PROPOSED_PARAMS)
    assert m["wrong_definitive"] == 0 and m["correct"] == m["n"], [r for r in m["results"] if r["got"] != r["expected"]]
    assert m["groups_consistent"] == m["groups"]

def test_rejection_without_source_is_not_a_rejection():
    s = {"identify": {"found": True, "name_similarity": 1, "top_ties": 1, "domain_match": True},
         "director": {"found": True, "contradicted": True, "sources": []}}
    assert policy.evaluate(s)["director_match"]["status"] == "unknown"

def test_candidate_params_change_is_reported_not_applied():
    out = subprocess.run([sys.executable, "evaluation/run_eval.py", "--compare", "evaluation/candidate.example.json"],
                         capture_output=True, text=True, cwd=Path(__file__).resolve().parent.parent).stdout
    assert "report-only" in out and "BASELINE" in out

def test_sweep_runs():
    out = subprocess.run([sys.executable, "evaluation/run_eval.py", "--sweep", "evaluation/sweep.example.json", "--top", "3"],
                         capture_output=True, text=True, cwd=Path(__file__).resolve().parent.parent).stdout
    assert "SWEEP: 27 combinations" in out
