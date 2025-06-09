import json
from pathlib import Path
from config import NERDSCORE_FILE

nerdscore_data = Path(NERDSCORE_FILE)

def load_nerdscore() -> dict:
    if not nerdscore_data.exists():
        nerdscore_data.write_text("{}", encoding="utf-8")
        return {}
    try:
        data = json.loads(nerdscore_data.read_text(encoding='utf-8'))
    except (json.JSONDecodeError, UnicodeDecodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    return data

def save_nerdscore(scores: dict):
    nerdscore_data.write_text(json.dumps(scores, indent=4), encoding='utf-8')

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