import json
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_json(provider: str, filename: str) -> dict | list:
    path = FIXTURES_DIR / provider / filename
    return json.loads(path.read_text(encoding="utf-8"))
