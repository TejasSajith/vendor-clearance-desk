"""LLM adapter. The model only TRANSLATES (English in, fields out; decision in, English out). It never decides a verdict.

extract(text, schema, ...) -> dict, or raises LLMUnavailable. Callers must always have a code fallback (nl.py does).
Providers (config.json "llm.provider"): "gemini" | "none". "gemini" without GEMINI_API_KEY behaves as "none".
Every model call goes through core.cached_call: throttle, cache, ledger (model, tokens; credits 0, since it is not Crustdata).
The key is read from the environment (or a gitignored .env file). It is never logged, stored or returned.

    python llm.py models     # list the models this key can use (to check config.json "llm.model")
"""
import hashlib, json, os, sys, uuid
from pathlib import Path
import requests
import core

ROOT = Path(__file__).resolve().parent
API = "https://generativelanguage.googleapis.com/v1beta"
ENDPOINT = "/llm/generate"      # one ledger endpoint for every model call; the model name is in the logged params

class LLMUnavailable(Exception):
    """No provider, no key, timeout after the retry, or a bad response. The caller falls back to code."""

def load_dotenv(path=ROOT / ".env"):
    """Minimal .env reader (KEY=VALUE lines). Never overrides a variable already set. .env is gitignored."""
    try: lines = Path(path).read_text().splitlines()
    except OSError: return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line: continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

def settings():
    s = {"provider": "none", "model": None, "timeout_seconds": 20, "attempts": 2, "cooldown_seconds": 0, "thinking_level": None}
    s.update({k: v for k, v in (core.CONFIG.get("llm") or {}).items() if not k.startswith("_")})
    return s

class GeminiProvider:
    name = "gemini"
    def __init__(self, model, key, timeout, thinking_level=None):
        self.model, self._key, self.timeout, self.thinking_level = model, key, timeout, thinking_level
    def __repr__(self): return f"GeminiProvider(model={self.model!r})"      # never shows the key
    def generate(self, system, text, schema):
        body = {"systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": text}]}],
                "generationConfig": {"responseMimeType": "application/json", "responseSchema": schema, "temperature": 0}}
        if self.thinking_level: body["generationConfig"]["thinkingConfig"] = {"thinkingLevel": self.thinking_level}
        try:
            r = requests.post(f"{API}/models/{self.model}:generateContent", json=body, timeout=self.timeout,
                              headers={"x-goog-api-key": self._key, "content-type": "application/json"})
        except requests.exceptions.RequestException as e:
            raise core.TransientError(type(e).__name__)        # the exception text could echo request details; keep only the type
        if r.status_code == 429: raise core.RateLimited(None)
        if r.status_code >= 500: raise core.TransientError(f"HTTP {r.status_code}")
        if r.status_code >= 400: raise LLMUnavailable(f"model API refused the request: HTTP {r.status_code}")
        j = r.json()
        try: out = j["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError): raise LLMUnavailable("model returned no text")
        u = j.get("usageMetadata") or {}
        return {"text": out, "tokens_in": u.get("promptTokenCount"), "tokens_out": u.get("candidatesTokenCount"),
                "model": j.get("modelVersion") or self.model}

def get_provider():
    """The configured provider, or None (template fallback)."""
    s = settings()
    if s["provider"] != "gemini": return None
    load_dotenv()
    key = os.environ.get("GEMINI_API_KEY")
    if not key or not s.get("model"): return None
    return GeminiProvider(s["model"], key, s["timeout_seconds"], s.get("thinking_level"))

def ledger_run(db, label="llm"):
    """A fresh ledger run for model calls made outside a vendor run (parsing a sentence, writing a memo)."""
    return core.start_run(db, json.dumps({"kind": label}), run_id=f"{label}_{uuid.uuid4().hex[:10]}")

_down_until = {}     # model -> clock time: after a timeout or 5xx, skip the model for cooldown_seconds (templates answer at once)

def available(provider):
    return provider is not None and core._clock["now"]() >= _down_until.get(getattr(provider, "model", provider.name), 0)

def extract(text, schema, system, db, run_id, provider="config", task="extract"):
    """Ask the model for JSON matching `schema`. Returns the parsed dict or raises LLMUnavailable.
    The ledger logs model, task, a hash of the input (not the input) and the token counts."""
    if provider == "config": provider = get_provider()
    if provider is None: raise LLMUnavailable("no model provider configured")
    s = settings()
    model = getattr(provider, "model", provider.name)
    if not available(provider): raise LLMUnavailable("model API cooling down after a failure; using templates")
    params = {"model": model, "task": task, "input_sha": hashlib.sha256((system + "\n" + text).encode()).hexdigest()[:16]}
    try:
        out = core.cached_call(db, run_id, ENDPOINT, params, lambda: provider.generate(system, text, schema),
                               credits_from=lambda o: 0.0, attempts=s["attempts"],
                               log_from=lambda o: {"tokens_in": o.get("tokens_in"), "tokens_out": o.get("tokens_out")})
    except core.SourceUnreachable as e:          # timeouts or 5xx after the retry: cool down so the next call does not wait again
        _down_until[model] = core._clock["now"]() + (s.get("cooldown_seconds") or 0)
        raise LLMUnavailable(str(e))
    except (core.LimitExceeded, LLMUnavailable) as e:
        raise LLMUnavailable(str(e))
    except Exception as e:                       # anything unexpected from the provider: fall back, never crash the run
        raise LLMUnavailable(type(e).__name__)
    try:
        val = json.loads(out["text"])
    except (TypeError, ValueError): raise LLMUnavailable("model output is not JSON")
    if not isinstance(val, dict): raise LLMUnavailable("model output is not an object")
    return val

def list_models():
    load_dotenv()
    key = os.environ.get("GEMINI_API_KEY")
    if not key: raise SystemExit("GEMINI_API_KEY is not set (environment or .env)")
    r = requests.get(f"{API}/models", headers={"x-goog-api-key": key}, timeout=20, params={"pageSize": 200})
    r.raise_for_status()
    return [m["name"].removeprefix("models/") for m in r.json().get("models", [])
            if "generateContent" in (m.get("supportedGenerationMethods") or [])]

if __name__ == "__main__":
    if sys.argv[1:] == ["models"]:
        names = list_models(); cfg = settings().get("model")
        print("\n".join(names)); print(f"\nconfig.json llm.model = {cfg!r}: {'available' if cfg in names else 'NOT in this list'}")
    else: print(__doc__)
