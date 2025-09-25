import json
import threading
from pathlib import Path
import os
import time
import config

METRICS_FILE = config.DATA_DIR / "metrics.json"
_LOCK = threading.Lock()

def update_metrics(user_id: int) -> None:
    key = str(user_id)
    try:
        with open(config.METRICS_FILE, 'r', encoding='utf-8') as f:
            metrics = json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        metrics = {}

    if not isinstance(metrics, dict):
        metrics = {}

    current = metrics.get(key)
    if isinstance(current, dict):
        current['messages'] = int(current.get('messages') or 0) + 1
        metrics[key] = current
    elif isinstance(current, int):
        metrics[key] = current + 1
    else:
        metrics[key] = 1

    try:
        with open(config.METRICS_FILE, 'w', encoding='utf-8') as f:
            json.dump(metrics, f, indent=2, ensure_ascii=False)
    except Exception:
        return

def _ensure_file():
	os.makedirs(os.path.dirname(str(METRICS_FILE)), exist_ok=True)
	if not METRICS_FILE.exists():
		METRICS_FILE.write_text(json.dumps({
			"messages_sent": 0,
			"updated_at": time.time()
		}, indent=2), encoding='utf-8')


def _load():
	_ensure_file()
	try:
		return json.loads(METRICS_FILE.read_text(encoding='utf-8'))
	except Exception:
		return {"messages_sent": 0, "updated_at": time.time()}


def _save(data: dict):
	data["updated_at"] = time.time()
	METRICS_FILE.write_text(json.dumps(data, indent=2), encoding='utf-8')


class _ValueHolder:
	def __init__(self, getter):
		self._getter = getter

	def get(self):
		try:
			return int(self._getter())
		except Exception:
			return 0


class Counter:
	def __init__(self, key: str):
		self.key = key
		self._value = _ValueHolder(lambda: _load().get(self.key, 0))

	def inc(self, amount: int = 1):
		with _LOCK:
			data = _load()
			data[self.key] = int(data.get(self.key, 0)) + int(amount)
			_save(data)


messages_sent = Counter('messages_sent')