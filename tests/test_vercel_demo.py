"""Vercel demo function: replays fixtures only (no keys, no database, no network, no writes); the allowlist keeps data off Vercel;
the backend accepts a bearer token and allows cross-site calls only from the configured origin."""
import importlib, json, os, sys
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
demo = importlib.import_module("vercel_demo.main")
from tests.test_server import make, PW, ACME, server   # noqa: E402

def test_config_without_backend_is_demo_only(monkeypatch):
    monkeypatch.delenv("BACKEND_URL", raising=False)
    c = TestClient(demo.app).get("/api/config").json()
    assert c["platform"] == "vercel" and c["backend_url"] is None and c["demo_label"].startswith("Demo mode: recorded results")

@pytest.mark.parametrize("raw,want", [("https://desk.example.com/", "https://desk.example.com"), ("https://desk.example.com/x", "https://desk.example.com"),
                                      ("http://localhost:8000", "http://localhost:8000"), ("http://desk.example.com", None),
                                      ("javascript:alert(1)", None), ("desk.example.com", None), ("", None)])
def test_backend_url_must_be_https(raw, want): assert demo.backend_url(raw) == want

def test_six_cases_cover_the_required_outcomes():
    c = TestClient(demo.app)
    cases = c.get("/api/demo/cases").json()["cases"]
    assert len(cases) == 6
    cards = {x["id"]: c.get(f"/api/demo/cases/{x['id']}").json() for x in cases}
    assert all(r["demo"] and r["demo_label"] for r in cards.values())
    assert cards["cleared"]["verdict"] == "CLEARED" and cards["cleared"]["action"]["status"] == "pending"
    assert cards["held"]["verdict"] == "HOLD_FOR_APPROVAL"
    assert "No record found" in cards["no-record"]["checks"][0]["reason"]
    assert any(k["reason"] == "no claimed director in the request" for k in cards["director-missing"]["checks"])
    assert any(k["label"] == "Suspicious" for k in cards["suspicious"]["checks"])
    assert cards["cap-stopped"]["status"] == "stopped_at_cap"
    # synthetic cases are labelled; the rest are recorded live runs
    assert {i for i, r in cards.items() if r["origin"] == "synthetic"} == {"cleared", "held"}
    assert c.get("/api/demo/cases/../../.env").status_code == 404 and c.get("/api/demo/cases/nope").status_code == 404

def test_fixtures_hold_no_placeholder_names_or_secrets():
    blob = "".join(p.read_text(encoding="utf-8") for p in (ROOT / "vercel_demo" / "fixtures").glob("*.json"))
    for bad in ("Test Director", "SECRET", "api_key", "CRUSTDATA_API_KEY", "GEMINI"): assert bad not in blob

def test_demo_function_has_no_storage_or_network_code(tmp_path, monkeypatch):
    src = (ROOT / "vercel_demo" / "main.py").read_text(encoding="utf-8")
    for bad in ("sqlite3", "import requests", "httpx", "import core", "write_text", "open("): assert bad not in src
    monkeypatch.chdir(tmp_path)
    c = TestClient(demo.app)
    for p in ("/api/config", "/api/demo/cases", "/api/demo/cases/cleared"): assert c.get(p).status_code == 200
    assert list(tmp_path.iterdir()) == []

def test_vercelignore_is_an_allowlist():
    lines = [l.strip() for l in (ROOT / ".vercelignore").read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]
    assert lines[0] == "/*"
    assert {l for l in lines if l.startswith("!")} == {"!public", "!vercel_demo", "!vercel.json", "!pyproject.toml"}
    for must in (".env", "*.db", "**/raw/"): assert must in lines
    for p in ("public/index.html", "public/app.js", "vercel_demo/main.py", "vercel_demo/fixtures/index.json"): assert (ROOT / p).exists()

def test_backend_bearer_token_and_config(tmp_path):
    c = make(tmp_path)
    assert c.get("/api/config").json() == {"platform": "server"}
    tok = c.post("/api/login", json={"password": PW}).json()["token"]
    fresh = TestClient(c.app)            # no cookie: the token alone signs in
    assert fresh.get("/api/status").status_code == 401
    assert fresh.get("/api/status", headers={"authorization": f"Bearer {tok}"}).status_code == 200
    assert fresh.get("/api/status", headers={"authorization": "Bearer wrong"}).status_code == 401

def test_cors_only_for_the_configured_origin(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_CORS_ORIGIN", "https://desk.vercel.app")
    c = make(tmp_path)
    pre = lambda o: c.options("/api/login", headers={"origin": o, "access-control-request-method": "POST",
                                                    "access-control-request-headers": "content-type"})
    assert pre("https://desk.vercel.app").headers.get("access-control-allow-origin") == "https://desk.vercel.app"
    assert "access-control-allow-origin" not in pre("https://evil.example").headers
    monkeypatch.setenv("APP_CORS_ORIGIN", "*")
    with pytest.raises(RuntimeError): make(tmp_path / "x")

def test_no_cors_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("APP_CORS_ORIGIN", raising=False)
    r = make(tmp_path).get("/api/config", headers={"origin": "https://desk.vercel.app"})
    assert "access-control-allow-origin" not in r.headers
