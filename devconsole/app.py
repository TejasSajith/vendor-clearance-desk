"""Local dev console for the clearance engine. Localhost only. NOT the product UI and not for the demo.
Lets you try signals and parameters against the real policy/decision code, run the evaluation, and walk a run through
approval and a simulated crash. Data in a run is SIMULATED (taken from the signals you give), never live.
    python devconsole/app.py      then open http://127.0.0.1:8765
"""
import json, sqlite3, sys, time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "evaluation"))
import core, decision, policy, run_eval

DB_PATH = str(HERE / "console.db")
_db = None

class SimulatedCrash(BaseException): pass

def db():
    global _db
    if _db is None:
        _db = core.connect(DB_PATH)
        _db.execute("CREATE TABLE IF NOT EXISTS effects(key TEXT PRIMARY KEY, kind TEXT, ts REAL)")
    return _db

def reset():
    global _db
    if _db is not None: _db.close(); _db = None
    Path(DB_PATH).unlink(missing_ok=True)

def cases():
    out = []
    for f in ("cases_synthetic.json", "cases_real.json"):
        p = ROOT / "evaluation" / f
        if p.exists(): out += json.loads(p.read_text())
    return out

def merged_params(over):
    p = policy.load_params()
    for k, v in (over or {}).items():
        if k in p and v is not None and v != "":
            t = type(policy.PROPOSED_PARAMS[k])
            p[k] = (str(v).lower() == "true") if t is bool else t(v)
    return p

def api_evaluate(b):
    checks = policy.evaluate(b["signals"], merged_params(b.get("params")), b.get("risk_tier", "low"))
    d = decision.decide(checks)
    return {"checks": checks, "verdict": d.verdict, "reasons": d.reasons, "missing": d.missing}

def api_eval(b):
    cs = [c for c in cases() if c.get("expected")]
    cand = run_eval.run(cs, merged_params(b.get("params")))
    base = run_eval.run(cs, policy.load_params())
    changed = [{"id": x["id"], "default": y["got"], "now": x["got"], "expected": x["expected"]}
               for x, y in zip(cand["results"], base["results"]) if x["got"] != y["got"]]
    return {"metrics": {k: v for k, v in cand.items() if k != "results"}, "results": cand["results"], "changed_vs_default": changed}

SIM_CALLS = [("identify", "/company/identify", 0.2), ("profile", "/company/enrich", 2.0), ("director", "/person/enrich", 1.0), ("adverse", "/web/search/live", 1.0)]

def api_run_start(b):
    d = db()
    sig = b["signals"]; tier = b.get("risk_tier", "low")
    rid = core.start_run(d, "console: " + str(b.get("label", "custom")))
    def gather():
        for section, endpoint, credits in SIM_CALLS:
            if section in sig:
                core.tracked_call(d, rid, endpoint, {"simulated": True}, lambda: {"ok": True}, credits=credits)
                core.add_fact(d, rid, "vendor", section, sig[section], f"simulated://{section}", json.dumps(sig[section])[:300],
                              "SIMULATED", time.strftime("%Y-%m-%d"))
        return sig
    core.run_step(d, rid, "gather", gather)
    def decide():
        r = api_evaluate({"signals": sig, "risk_tier": tier, "params": b.get("params")})
        return {"verdict": r["verdict"], "missing": r["missing"], "reasons": r["reasons"]}
    res = core.run_step(d, rid, "decide", decide)
    dec = decision.Decision(res["verdict"], res["reasons"], res["missing"])
    core.finalize(d, rid, dec)
    return api_run_get(rid)

def api_run_get(rid):
    d = db()
    q = lambda sql, a=(): [list(r) for r in d.execute(sql, a)]
    return {"run": rid, "steps": q("SELECT name,result FROM steps WHERE run_id=?", (rid,)),
            "facts": core.facts(d, rid), "calls": q("SELECT endpoint,status,credits,ms FROM calls WHERE run_id=?", (rid,)),
            "credits": core.run_cost(d, rid), "actions": q("SELECT key,kind,status FROM actions WHERE run_id=?", (rid,)),
            "effects": q("SELECT key,kind FROM effects")}

def _effect(kind, payload, key):
    db().execute("INSERT OR IGNORE INTO effects VALUES(?,?,?)", (key, kind, time.time()))   # idempotent per key

def api_action(b):
    d, key, op = db(), b["key"], b["op"]
    if op == "approve": core.set_approval(d, key, True)
    elif op == "reject": core.set_approval(d, key, False)
    elif op == "execute": core.execute_action(d, key, _effect)
    elif op == "crash":
        def dying(kind, payload, k): raise SimulatedCrash()
        try: core.execute_action(d, key, dying)
        except SimulatedCrash: pass
    elif op == "recover": core.recover_actions(d, _effect)
    else: raise ValueError("unknown op")
    run = d.execute("SELECT run_id FROM actions WHERE key=?", (key,)).fetchone()[0]
    return api_run_get(run)

ROUTES_POST = {"/api/evaluate": api_evaluate, "/api/eval": api_eval, "/api/run/start": api_run_start, "/api/action": api_action,
               "/api/reset": lambda b: (reset(), {"ok": True})[1]}

class H(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/": return self._send(200, (HERE / "index.html").read_bytes(), "text/html; charset=utf-8")
        if u.path == "/api/cases": return self._send(200, cases())
        if u.path == "/api/params": return self._send(200, policy.PROPOSED_PARAMS)
        if u.path == "/api/run": return self._send(200, api_run_get(parse_qs(u.query)["id"][0]))
        self._send(404, {"error": "not found"})
    def do_POST(self):
        fn = ROUTES_POST.get(urlparse(self.path).path)
        if not fn: return self._send(404, {"error": "not found"})
        try: self._send(200, fn(json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")))
        except Exception as e: self._send(400, {"error": f"{type(e).__name__}: {e}"})
    def log_message(self, *a): pass

if __name__ == "__main__":
    print("Dev console on http://127.0.0.1:8765 (localhost only; data in runs is SIMULATED). Ctrl+C to stop.")
    HTTPServer(("127.0.0.1", 8765), H).serve_forever()
