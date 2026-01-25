import sqlite3
import json
import threading
from pathlib import Path
from datetime import datetime, timezone, timedelta

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
    cur.execute("""
    CREATE TABLE IF NOT EXISTS abuse_tracking (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        content_hash TEXT NOT NULL,
        content_len INTEGER NOT NULL,
        timestamp REAL NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)
    cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_abuse_user_id ON abuse_tracking(user_id)
    """)
    cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_abuse_timestamp ON abuse_tracking(timestamp)
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


def load_image_descriptions() -> dict:
    return get_json('image_descriptions', {}) or {}


def get_image_description(attach_id) -> str | None:
    try:
        imgs = load_image_descriptions()
        ent = imgs.get(str(attach_id))
        if not ent:
            return None
        try:
            ent['last_used'] = datetime.now(timezone.utc).isoformat()
            imgs[str(attach_id)] = ent
            set_json('image_descriptions', imgs)
        except Exception:
            pass
        return ent.get('description')
    except Exception:
        return None


def save_image_description(attach_id, description: str) -> None:
    try:
        imgs = load_image_descriptions()
        imgs[str(attach_id)] = {
            'description': description,
            'last_used': datetime.now(timezone.utc).isoformat()
        }
        set_json('image_descriptions', imgs)
    except Exception:
        raise


def prune_image_descriptions(age_hours: int = 24) -> list:
    try:
        imgs = load_image_descriptions()
        now = datetime.now(timezone.utc)
        removed = []
        for k, v in list(imgs.items()):
            lu = v.get('last_used') if isinstance(v, dict) else None
            if not lu:
                removed.append(k)
                del imgs[k]
                continue
            try:
                last_used = datetime.fromisoformat(lu)
                if last_used.tzinfo is None:
                    last_used = last_used.replace(tzinfo=timezone.utc)
            except Exception:
                removed.append(k)
                del imgs[k]
                continue
            if (now - last_used) > timedelta(hours=age_hours):
                removed.append(k)
                del imgs[k]
        if removed:
            set_json('image_descriptions', imgs)
        return removed
    except Exception:
        return []


def add_abuse_tracking_record(user_id: int, content_hash: str, content_len: int, timestamp: float) -> None:
    try:
        with _LOCK:
            conn = _get_conn()
            conn.execute(
                "INSERT INTO abuse_tracking (user_id, content_hash, content_len, timestamp) VALUES (?, ?, ?, ?)",
                (user_id, content_hash, content_len, timestamp)
            )
            conn.commit()
    except Exception:
        raise


def get_abuse_tracking_records(user_id: int, limit: int = 200) -> list:
    try:
        with _LOCK:
            cur = _get_conn().cursor()
            cur.execute(
                "SELECT user_id, content_hash, content_len, timestamp FROM abuse_tracking WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?",
                (user_id, limit)
            )
            rows = cur.fetchall()
            return [
                {
                    'user_id': row[0],
                    'content_hash': row[1],
                    'content_len': row[2],
                    'timestamp': row[3]
                }
                for row in rows
            ]
    except Exception:
        return []


def get_all_tracked_users() -> list:
    try:
        with _LOCK:
            cur = _get_conn().cursor()
            cur.execute("SELECT DISTINCT user_id FROM abuse_tracking")
            rows = cur.fetchall()
            return [row[0] for row in rows]
    except Exception:
        return []


def get_tracked_users_count() -> int:
    try:
        with _LOCK:
            cur = _get_conn().cursor()
            cur.execute("SELECT COUNT(DISTINCT user_id) FROM abuse_tracking")
            row = cur.fetchone()
            return row[0] if row else 0
    except Exception:
        return 0


def clear_abuse_tracking_records(user_id: int) -> None:
    try:
        with _LOCK:
            conn = _get_conn()
            conn.execute("DELETE FROM abuse_tracking WHERE user_id = ?", (user_id,))
            conn.commit()
    except Exception:
        raise
