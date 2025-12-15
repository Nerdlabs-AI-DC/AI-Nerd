import sqlite3
import json
import threading
from pathlib import Path

_DB_PATH = Path("data") / "storage.db"
_LOCK = threading.Lock()
_CONN = None


def _get_conn():
    global _CONN
    if _CONN is None:
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CONN = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
        _CONN.execute("PRAGMA journal_mode=WAL;")
        _init_db(_CONN)
    return _CONN


def _init_db(conn: sqlite3.Connection):
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS kv (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS blobs (
        key TEXT PRIMARY KEY,
        value BLOB
    )
    """)
    conn.commit()


def get_json(key: str, default=None):
    try:
        with _LOCK:
            cur = _get_conn().cursor()
            cur.execute("SELECT value FROM kv WHERE key = ?", (key,))
            row = cur.fetchone()
            if not row:
                return default
            return json.loads(row[0])
    except Exception:
        return default


def set_json(key: str, obj) -> None:
    try:
        val = json.dumps(obj, ensure_ascii=False)
        with _LOCK:
            conn = _get_conn()
            conn.execute("REPLACE INTO kv (key, value) VALUES (?, ?)", (key, val))
            conn.commit()
    except Exception:
        raise


def get_blob(key: str):
    try:
        with _LOCK:
            cur = _get_conn().cursor()
            cur.execute("SELECT value FROM blobs WHERE key = ?", (key,))
            row = cur.fetchone()
            if not row:
                return None
            return row[0]
    except Exception:
        return None


def set_blob(key: str, data: bytes) -> None:
    try:
        with _LOCK:
            conn = _get_conn()
            conn.execute("REPLACE INTO blobs (key, value) VALUES (?, ?)", (key, data))
            conn.commit()
    except Exception:
        raise


def load_settings():
    return get_json('serversettings', {}) or {}


def save_settings(settings: dict):
    set_json('serversettings', settings or {})


def load_daily_counts():
    return get_json('daily_message_counts', {}) or {}


def save_daily_counts(data: dict):
    set_json('daily_message_counts', data or {})


def load_recent_questions():
    return get_json('recent_questions', {}) or {}


def save_recent_questions(data: dict):
    set_json('recent_questions', data or {})


def load_daily_quiz_records():
    return get_json('daily_quiz_records', {}) or {}


def save_daily_quiz_records(data: dict):
    set_json('daily_quiz_records', data or {})


def load_nerdscore():
    return get_json('nerdscore', {}) or {}


def save_nerdscore(data: dict):
    set_json('nerdscore', data or {})


def load_metrics():
    return get_json('metrics', {}) or {}


def save_metrics(data: dict):
    set_json('metrics', data or {})


def load_user_metrics():
    return get_json('user_metrics', {}) or {}


def save_user_metrics(data: dict):
    set_json('user_metrics', data or {})


def get_freewill_attempts():
    return get_json('recent_freewill', {}) or {}


def save_freewill_attempts(data: dict):
    set_json('recent_freewill', data or {})


def get_context():
    return get_json('context_memory', {}) or {}


def save_context(data: dict):
    set_json('context_memory', data or {})


def get_blob_key_for_path(path_name: str) -> str:
    # map legacy filenames to blob keys
    if 'memories' in path_name:
        return 'memories_enc'
    if 'user_memories' in path_name:
        return 'user_memories_enc'
    return path_name


def get_encrypted_blob_for_path(path_name: str):
    return get_blob(get_blob_key_for_path(path_name))


def set_encrypted_blob_for_path(path_name: str, data: bytes):
    return set_blob(get_blob_key_for_path(path_name), data)


def load_knowledge():
    return get_json('knowledge_data', {}) or {}

def save_knowledge(data: dict):
    set_json('knowledge_data', data or {})


def load_banned_users():
    data = get_json('banned_users', []) or []
    try:
        if isinstance(data, dict):
            return [int(k) for k in data.keys()]
        return [int(x) for x in data]
    except Exception:
        return []


def save_banned_users(user_list):
    try:
        data = [int(x) for x in (user_list or [])]
    except Exception:
        data = []
    set_json('banned_users', data)


def load_banned_map():
    raw = get_json('banned_users', {}) or {}
    try:
        if isinstance(raw, dict):
            out = {}
            for k, v in raw.items():
                try:
                    out[int(k)] = v or {}
                except Exception:
                    continue
            return out
        if isinstance(raw, list):
            return {int(x): {'notified': False} for x in raw}
    except Exception:
        pass
    return {}


def save_banned_map(banned_map: dict):
    try:
        serial = {str(int(k)): (v or {}) for k, v in (banned_map or {}).items()}
        set_json('banned_users', serial)
    except Exception:
        raise


def mark_banned_user_notified(user_id: int):
    try:
        bm = load_banned_map()
        if int(user_id) in bm:
            bm[int(user_id)]['notified'] = True
            save_banned_map(bm)
    except Exception:
        pass


def is_banned_user_notified(user_id: int) -> bool:
    try:
        bm = load_banned_map()
        meta = bm.get(int(user_id))
        if not meta:
            return False
        return bool(meta.get('notified'))
    except Exception:
        return False
