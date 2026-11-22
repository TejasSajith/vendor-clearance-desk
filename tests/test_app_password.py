"""The access-password gate: only on when APP_PASSWORD is set and non-blank; never a default password."""
import importlib, sys
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
# devconsole/app.py shares the name `app`: load the app/ package explicitly, then give sys.modules["app"] back (as test_server does)
_prev = sys.modules.pop("app", None) if not hasattr(sys.modules.get("app"), "__path__") else None
server = importlib.import_module("app.server")
app_main = importlib.import_module("app.__main__")
if _prev is not None: sys.modules["app"] = _prev
else: sys.modules.pop("app", None)

def make(tmp_path, monkeypatch, env_pw=None, require_password=False):
    monkeypatch.setattr(server.llm, "load_dotenv", lambda *a, **k: None)   # keep the developer's .env out of the test
    if env_pw is None: monkeypatch.delenv("APP_PASSWORD", raising=False)
    else: monkeypatch.setenv("APP_PASSWORD", env_pw)
    return TestClient(server.create_app(data_dir=tmp_path, llm_provider=None, allow_live=False, require_password=require_password))

@pytest.mark.parametrize("env_pw", [None, "", "   "])
def test_unset_or_blank_password_means_no_gate_locally(tmp_path, monkeypatch, env_pw):
    c = make(tmp_path, monkeypatch, env_pw)
    assert c.get("/api/health").json()["login_required"] is False
    r = c.get("/api/status")
    assert r.status_code == 200 and r.json()["login_required"] is False

def test_unset_password_still_refused_when_not_local(tmp_path, monkeypatch):
    with pytest.raises(RuntimeError): make(tmp_path, monkeypatch, None, require_password=True)

def test_set_password_gates_and_correct_one_signs_in(tmp_path, monkeypatch):
    c = make(tmp_path, monkeypatch, "s3cret-for-test")
    assert c.get("/api/health").json()["login_required"] is True
    r = c.get("/api/status")
    assert r.status_code == 401 and r.json() == {"error": "Please sign in"}
    assert c.post("/api/login", json={"password": "s3cret-for-test"}).status_code == 200
    assert c.get("/api/status").status_code == 200

def test_wrong_password_is_a_clear_401(tmp_path, monkeypatch):
    c = make(tmp_path, monkeypatch, "s3cret-for-test")
    for wrong in ("nope", "", "s3cret-for-tes"):
        r = c.post("/api/login", json={"password": wrong})
        assert r.status_code == 401 and r.json() == {"error": "Wrong password"}
    assert c.get("/api/status").status_code == 401

def test_login_page_says_who_sets_the_password():
    html = (ROOT / "app" / "static" / "index.html").read_text(encoding="utf-8")
    assert "Enter the access password" in html and "set by the person who runs the server" in html
    js = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")
    assert "e.status === 401" in js   # wrong password gets its own message, not a generic error

def test_startup_note_names_the_source_and_never_the_value(monkeypatch):
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    assert app_main.password_note(False).startswith("none")
    monkeypatch.setenv("APP_PASSWORD", "s3cret-for-test")
    assert ".env" in app_main.password_note(False) and "shell" in app_main.password_note(True)
    assert "s3cret" not in app_main.password_note(False) + app_main.password_note(True)
