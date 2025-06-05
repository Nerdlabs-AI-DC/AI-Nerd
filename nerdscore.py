import json
from pathlib import Path

NERDSCORE_PATH = Path('nerdscoredata.json')

def load_nerdscore() -> dict:
    if not NERDSCORE_PATH.exists():
        NERDSCORE_PATH.write_text("{}", encoding="utf-8")
        return {}
    try:
        data = json.loads(NERDSCORE_PATH.read_text(encoding='utf-8'))
    except (json.JSONDecodeError, UnicodeDecodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    return data

def save_nerdscore(scores: dict):
    NERDSCORE_PATH.write_text(json.dumps(scores, indent=4), encoding='utf-8')

def increase_nerdscore(user_id: int, amount: int = 1) -> int:
    scores = load_nerdscore()
    user_key = str(user_id)
    current = scores.get(user_key, 0)
    current += amount
    if current < 0:
        current = 0
    scores[user_key] = current
    save_nerdscore(scores)
    return current

def get_nerdscore(user_id: int) -> int:
    scores = load_nerdscore()
    return scores.get(str(user_id), 0)