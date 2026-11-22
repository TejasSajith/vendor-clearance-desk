"""Thin Crustdata probe client: throttles per endpoint, retries 429, logs every call
to probe/calls.jsonl, saves raw bodies to probe/raw/. Key is read from CRUSTDATA_API_KEY only."""
import json, os, re, time, pathlib, requests

BASE = "https://api.crustdata.com"
HERE = pathlib.Path(__file__).parent
RAW = HERE / "raw"; RAW.mkdir(exist_ok=True)
LOG = HERE / "calls.jsonl"
BUDGET = 150.0
# Effective per-minute limits on this account (GET /account/endpoints). Stricter than the
# 30/15/10 in the brief, so we follow the account's numbers.
RPM = {"/company/search": 5, "/company/identify": 5, "/company/enrich": 5, "/job/search": 5,
       "/person/search": 5, "/person/enrich": 5, "/web/search/live": 10, "/web/enrich/live": 10}
_last = {}

def spent():
    if not LOG.exists(): return 0.0
    return sum((json.loads(l).get("credits") or 0) for l in LOG.read_text().splitlines() if l.strip())

def call(path, body, tag, timeout=90):
    key = os.environ["CRUSTDATA_API_KEY"]
    if spent() >= BUDGET:
        raise SystemExit(f"budget {BUDGET} reached")
    gap = 60.0 / RPM.get(path, 300) + 0.7
    wait = _last.get(path, 0) + gap - time.time()
    if wait > 0: time.sleep(wait)
    hdr = {"authorization": f"Bearer {key}", "x-api-version": "2025-11-01", "content-type": "application/json"}
    for attempt in range(4):
        t0 = time.time(); _last[path] = t0
        try:
            r = requests.post(BASE + path, headers=hdr, json=body, timeout=timeout)
            status, text, h = r.status_code, r.text, r.headers
        except requests.exceptions.RequestException as e:
            status, text, h = "timeout/err", repr(e), {}
        ms = int((time.time() - t0) * 1000)
        cr = h.get("x-credits-used") if h else None
        rec = {"ts": time.strftime("%H:%M:%S"), "tag": tag, "endpoint": path, "params": body,
               "status": status, "credits": float(cr) if cr not in (None, "") else 0.0,
               "credits_header": cr, "ms": ms, "attempt": attempt, "request_id": h.get("x-request-id") if h else None}
        with LOG.open("a") as f: f.write(json.dumps(rec) + "\n")
        if status == 429:
            time.sleep(float(h.get("retry-after", 15)) + 1); continue
        break
    (RAW / (re.sub(r"[^A-Za-z0-9_.-]", "_", tag)[:90] + ".json")).write_text(text)
    try: data = json.loads(text)
    except Exception: data = None
    return status, data, rec
