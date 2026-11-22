"""Operations parameters from ops_config.json. All values are PROPOSED (see DECISIONS.md D50 to D55)."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATH = ROOT / "ops_config.json"

def load(path=None):
    raw = json.loads(Path(path or PATH).read_text())
    return {k: v for k, v in raw.items() if not k.startswith("_")}

OPS = load()
