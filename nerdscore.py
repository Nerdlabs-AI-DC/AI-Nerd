import storage

def load_nerdscore() -> dict:
    data = storage.load_nerdscore() or {}
    if not isinstance(data, dict):
        return {}
    return data


def save_nerdscore(scores: dict):
    storage.save_nerdscore(scores or {})

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