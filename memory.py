import os
import json
import time
import base64
from config import FULL_MEMORY_FILE, USER_MEMORIES_FILE, CONTEXT_FILE, MEMORY_LIMIT
from credentials import MEMORY_KEY_B64

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MEMORIES_FILE = FULL_MEMORY_FILE
_MEMORIES_CACHE = None
_USER_MEMORIES_CACHE = None


def _get_key() -> bytes:
    if not MEMORY_KEY_B64:
        raise RuntimeError("MEMORY_KEY is not set!")
    key = base64.urlsafe_b64decode(MEMORY_KEY_B64)
    if len(key) != 32:
        raise ValueError("MEMORY key must be 32 bytes for AES-256")
    return key


def _encrypt_bytes(plaintext: bytes) -> bytes:
    key = _get_key()
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)
    return base64.urlsafe_b64encode(nonce + ciphertext)


def _decrypt_bytes(data_b64: bytes) -> bytes:
    raw = base64.urlsafe_b64decode(data_b64)
    if len(raw) < 12:
        raise ValueError("Invalid encrypted data")
    nonce = raw[:12]
    ciphertext = raw[12:]
    key = _get_key()
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ciphertext, None)


def _read_json_encrypted(path):
    try:
        with open(path, 'rb') as f:
            b = f.read()
            if not b:
                return None
            try:
                dec = _decrypt_bytes(b)
                return json.loads(dec.decode('utf-8'))
            except Exception:
                try:
                    return json.loads(b.decode('utf-8'))
                except Exception:
                    return None
    except FileNotFoundError:
        return None


def _write_json_encrypted(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    plain = json.dumps(obj, indent=2, ensure_ascii=False).encode('utf-8')
    enc = _encrypt_bytes(plain)
    with open(path, 'wb') as f:
        f.write(enc)


def init_memory_files():
    if _read_json_encrypted(MEMORIES_FILE) is None:
        _write_json_encrypted(MEMORIES_FILE, {"summaries": [], "memories": []})
    if _read_json_encrypted(USER_MEMORIES_FILE) is None:
        _write_json_encrypted(USER_MEMORIES_FILE, {})


def load_memory_cache():
    global _MEMORIES_CACHE, _USER_MEMORIES_CACHE
    data = _read_json_encrypted(MEMORIES_FILE) or {"summaries": [], "memories": []}
    _MEMORIES_CACHE = {"summaries": list(data.get("summaries", [])), "memories": list(data.get("memories", []))}
    udata = _read_json_encrypted(USER_MEMORIES_FILE) or {}
    # deep copy
    _USER_MEMORIES_CACHE = {k: {"summaries": list(v.get("summaries", [])), "memories": list(v.get("memories", []))} for k, v in udata.items()}


def add_memory_to_cache(summary: str, full_memory: str) -> int:
    global _MEMORIES_CACHE
    if _MEMORIES_CACHE is None:
        load_memory_cache()
    if _MEMORIES_CACHE is None:
        _MEMORIES_CACHE = {"summaries": [], "memories": []}
    if len(_MEMORIES_CACHE.get("summaries", [])) >= MEMORY_LIMIT:
        _MEMORIES_CACHE["summaries"].pop(0)
        _MEMORIES_CACHE["memories"].pop(0)
    _MEMORIES_CACHE.setdefault("summaries", []).append(summary)
    _MEMORIES_CACHE.setdefault("memories", []).append(full_memory)
    return len(_MEMORIES_CACHE.get("summaries", []))


def add_user_memory_to_cache(user_id: str, summary: str, full_memory: str) -> int:
    global _USER_MEMORIES_CACHE
    user_key = str(user_id)
    if _USER_MEMORIES_CACHE is None:
        load_memory_cache()
    if _USER_MEMORIES_CACHE is None:
        _USER_MEMORIES_CACHE = {}
    if user_key not in _USER_MEMORIES_CACHE:
        _USER_MEMORIES_CACHE[user_key] = {"summaries": [], "memories": []}
    if len(_USER_MEMORIES_CACHE[user_key].get("summaries", [])) >= MEMORY_LIMIT:
        _USER_MEMORIES_CACHE[user_key]["summaries"].pop(0)
        _USER_MEMORIES_CACHE[user_key]["memories"].pop(0)
    _USER_MEMORIES_CACHE[user_key].setdefault("summaries", []).append(summary)
    _USER_MEMORIES_CACHE[user_key].setdefault("memories", []).append(full_memory)
    return len(_USER_MEMORIES_CACHE[user_key].get("summaries", []))


def flush_memory_cache():
    global _MEMORIES_CACHE, _USER_MEMORIES_CACHE
    if _MEMORIES_CACHE is not None:
        try:
            _write_json_encrypted(MEMORIES_FILE, {"summaries": _MEMORIES_CACHE.get("summaries", []), "memories": _MEMORIES_CACHE.get("memories", [])})
        except Exception:
            raise
    if _USER_MEMORIES_CACHE is not None:
        try:
            _write_json_encrypted(USER_MEMORIES_FILE, _USER_MEMORIES_CACHE)
        except Exception:
            raise


def save_memory(summary: str, full_memory: str) -> int:
    global _MEMORIES_CACHE
    data = _read_json_encrypted(MEMORIES_FILE)
    if data is None:
        data = {"summaries": [], "memories": []}
    if len(data.get("summaries", [])) >= MEMORY_LIMIT:
        data["summaries"].pop(0)
        data["memories"].pop(0)
    data.setdefault("summaries", []).append(summary)
    data.setdefault("memories", []).append(full_memory)
    _write_json_encrypted(MEMORIES_FILE, data)
    if _MEMORIES_CACHE is not None:
        _MEMORIES_CACHE.setdefault("summaries", []).append(summary)
        _MEMORIES_CACHE.setdefault("memories", []).append(full_memory)
        if len(_MEMORIES_CACHE.get("summaries", [])) > MEMORY_LIMIT:
            _MEMORIES_CACHE["summaries"].pop(0)
            _MEMORIES_CACHE["memories"].pop(0)
    return len(data["summaries"])


def get_memory_detail(index: int) -> str:
    global _MEMORIES_CACHE
    if _MEMORIES_CACHE is not None:
        memories = _MEMORIES_CACHE.get("memories", [])
    else:
        data = _read_json_encrypted(MEMORIES_FILE) or {"memories": []}
        memories = data.get("memories", [])
    if 1 <= index <= len(memories):
        return memories[index - 1]
    return ""


def get_all_summaries() -> list:
    global _MEMORIES_CACHE
    if _MEMORIES_CACHE is not None:
        return list(_MEMORIES_CACHE.get("summaries", []))
    data = _read_json_encrypted(MEMORIES_FILE) or {"summaries": []}
    return data.get("summaries", [])


def save_user_memory(user_id: str, summary: str, full_memory: str) -> int:
    global _USER_MEMORIES_CACHE
    user_key = str(user_id)
    data = _read_json_encrypted(USER_MEMORIES_FILE) or {}
    if user_key not in data:
        data[user_key] = {"summaries": [], "memories": []}
    if len(data[user_key].get("summaries", [])) >= MEMORY_LIMIT:
        data[user_key]["summaries"].pop(0)
        data[user_key]["memories"].pop(0)
    data[user_key].setdefault("summaries", []).append(summary)
    data[user_key].setdefault("memories", []).append(full_memory)
    _write_json_encrypted(USER_MEMORIES_FILE, data)
    if _USER_MEMORIES_CACHE is not None:
        if user_key not in _USER_MEMORIES_CACHE:
            _USER_MEMORIES_CACHE[user_key] = {"summaries": [], "memories": []}
        _USER_MEMORIES_CACHE[user_key].setdefault("summaries", []).append(summary)
        _USER_MEMORIES_CACHE[user_key].setdefault("memories", []).append(full_memory)
        if len(_USER_MEMORIES_CACHE[user_key].get("summaries", [])) > MEMORY_LIMIT:
            _USER_MEMORIES_CACHE[user_key]["summaries"].pop(0)
            _USER_MEMORIES_CACHE[user_key]["memories"].pop(0)
    return len(data[user_key]["summaries"])


def get_user_memory_detail(user_id: str, index: int) -> str:
    user_key = str(user_id)
    global _USER_MEMORIES_CACHE
    if _USER_MEMORIES_CACHE is not None and user_key in _USER_MEMORIES_CACHE:
        memories = _USER_MEMORIES_CACHE[user_key].get("memories", [])
        if 1 <= index <= len(memories):
            return memories[index - 1]
    data = _read_json_encrypted(USER_MEMORIES_FILE) or {}
    if user_key in data:
        memories = data[user_key].get("memories", [])
        if 1 <= index <= len(memories):
            return memories[index - 1]
    return ""


def get_user_summaries(user_id: str) -> list:
    user_key = str(user_id)
    global _USER_MEMORIES_CACHE
    if _USER_MEMORIES_CACHE is not None and user_key in _USER_MEMORIES_CACHE:
        return list(_USER_MEMORIES_CACHE[user_key].get("summaries", []))
    data = _read_json_encrypted(USER_MEMORIES_FILE) or {}
    if user_key in data:
        return data[user_key].get("summaries", [])
    return []


def save_context(user_id: str, channel_id: str) -> None:
    current_time = time.time()
    try:
        with open(CONTEXT_FILE, 'r', encoding='utf-8') as f:
            try:
                context = json.load(f) or {}
            except Exception:
                context = {}
    except FileNotFoundError:
        context = {}
    os.makedirs(os.path.dirname(CONTEXT_FILE), exist_ok=True)
    context[str(user_id)] = {"channel_id": channel_id, "timestamp": current_time}
    with open(CONTEXT_FILE, 'w', encoding='utf-8') as f:
        json.dump(context, f, indent=2, ensure_ascii=False)


def get_channel_by_user(user_id: str):
    try:
        with open(CONTEXT_FILE, 'r', encoding='utf-8') as f:
            try:
                context = json.load(f) or {}
            except Exception:
                context = {}
    except FileNotFoundError:
        context = {}
    data = context.get(str(user_id), {})
    if isinstance(data, dict):
        return data.get("channel_id", ""), data.get("timestamp", 0)
    return "", 0


def delete_user_memories(user_id: str) -> bool:
    key = str(user_id)
    data = _read_json_encrypted(USER_MEMORIES_FILE) or {}
    if key in data:
        try:
            del data[key]
            _write_json_encrypted(USER_MEMORIES_FILE, data)
            return True
        except Exception:
            raise
    return False