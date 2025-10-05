import threading
import time
import storage

_LOCK = threading.Lock()


def update_metrics(user_id: int) -> None:
	key = str(user_id)
	metrics = storage.load_metrics() or {}
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
		storage.save_metrics(metrics)
	except Exception:
		return


def _load():
	try:
		return storage.load_metrics() or {"messages_sent": 0, "updated_at": time.time()}
	except Exception:
		return {"messages_sent": 0, "updated_at": time.time()}


def _save(data: dict):
	data["updated_at"] = time.time()
	storage.save_metrics(data)


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