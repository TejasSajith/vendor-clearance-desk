"""Build the six demo-mode fixtures for the static Vercel page (vercel_demo/fixtures/*.json).

    python scripts/build_demo_fixtures.py

Each fixture is the result card the web UI shows (app/server.py `/api/runs/{id}`), produced by the real server code:
  recorded   four live runs from the local, gitignored run databases of the live validation (evaluation/live_validation.md).
             The databases are copied to a temp folder first, so the originals are never written to.
  synthetic  two demo-mode runs (app/demo.py): Cleared and Held for approval. No live run produced either (no live run supplied a
             claimed director), so they are synthetic and labelled so on the page.
The memo is the template memo (no model call). Credits are the run's ledger total in its own database. No person names: the
recorded runs had no claimed director, and the synthetic runs use the placeholder "Test Director", which the card never shows.
"""
import importlib, json, os, shutil, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from fastapi.testclient import TestClient  # noqa: E402

OUT = ROOT / "vercel_demo" / "fixtures"
LIVE = ROOT / "probe" / "live"
PW = "build-only"

RECORDED = [   # (fixture id, kind shown on the page, database, run id)
    ("no-record", "Can't verify: no company record", "m.db", "r_8bebb5eca2f8"),
    ("director-missing", "Can't verify: director not supplied", "live.db", "r_a00cae49c494"),
    ("suspicious", "Suspicious: possible adverse reports", "live.db", "r_153a5a82044e"),
    ("cap-stopped", "Stopped at the credit cap", "cap.db", "r_9f2bd226f0bb"),
]
SYNTHETIC = [  # (fixture id, kind, sentence typed into the demo)
    ("cleared", "Cleared, waiting for a person's approval",
     "Check Acme Logistics Pvt Ltd, website acmelogistics.in, director Test Director, low risk."),
    ("held", "Held for approval: a source timed out",
     "Check Slowpoke Freight Pvt Ltd, director Test Director, medium risk."),
]
DROP = ("session_spent", "questions", "parser", "controls", "control_notes", "existing", "total_seconds")

def _server():
    sys.path.insert(0, str(ROOT))
    sys.modules.pop("app", None)
    return importlib.import_module("app.server")

def _sentence(req, card):
    s = f"Check {req['vendor_name']}"
    if req.get("website"): s += f", website {req['website']}"
    d = next((c for c in card["checks"] if c["check"] == "director_match"), {})
    given = "no claimed director" not in d.get("reason", "")
    return s + (", director [name not stored]" if given else "") + f", {req.get('risk_tier') or 'low'} risk." + ("" if given else " (No director given.)")

def _clean(card):
    for k in DROP: card.pop(k, None)
    card.pop("demo_label", None); card.pop("mode", None)
    return card

def build():
    server = _server()
    OUT.mkdir(parents=True, exist_ok=True)
    out = []
    with tempfile.TemporaryDirectory() as tmp:
        for fid, kind, dbname, run_id in RECORDED:
            db = Path(tmp) / f"{fid}.db"
            shutil.copy(LIVE / dbname, db)
            c = TestClient(server.create_app(db_path=str(db), mode="demo", password=PW, llm_provider=None,
                                             candidate_path=Path(tmp) / "none.json"))
            c.post("/api/login", json={"password": PW})
            card = c.get(f"/api/runs/{run_id}").json()
            import sqlite3
            req = json.loads(sqlite3.connect(db).execute("SELECT request FROM runs WHERE id=?", (run_id,)).fetchone()[0])
            card = _clean(card)
            card.update({"id": fid, "kind": kind, "origin": "recorded",
                         "origin_note": "Recorded live run (Crustdata) from the live validation; replayed, not run again.",
                         "input": _sentence(req, card), "input_note": "Written from the recorded structured request."})
            out.append(card)
        for fid, kind, text in SYNTHETIC:
            c = TestClient(server.create_app(db_path=str(Path(tmp) / f"{fid}.db"), mode="demo", password=PW, llm_provider=None,
                                             candidate_path=Path(tmp) / "none.json"))
            c.post("/api/login", json={"password": PW})
            card = _clean(c.post("/api/run", json={"text": text, "controls": {}}).json())
            card.update({"id": fid, "kind": kind, "origin": "synthetic",
                         "origin_note": "Synthetic demo case (app/demo.py): no live run produced this verdict.",
                         "input": text.replace("Test Director", "[placeholder name]"),
                         "input_note": "A director name was typed; it is used at run time only and never stored or shown."})
            out.append(card)
    for card in out:
        (OUT / f"{card['id']}.json").write_text(json.dumps(card, indent=1, ensure_ascii=False) + "\n")
    index = [{"id": c["id"], "kind": c["kind"], "vendor": _vendor(c), "overall": c["overall"], "origin": c["origin"]} for c in out]
    (OUT / "index.json").write_text(json.dumps(index, indent=1) + "\n")
    for i in index: print(f"{i['id']:18} {i['origin']:9} {i['overall']:20} {i['vendor']}")

def _vendor(card):
    t = card["input"][len("Check "):]
    return t.split(",")[0].strip()

if __name__ == "__main__":
    os.environ.pop("GEMINI_API_KEY", None)
    build()
