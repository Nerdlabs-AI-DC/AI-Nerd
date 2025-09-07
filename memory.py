import os
import json
import time
import base64
from config import FULL_MEMORY_FILE, USER_MEMORIES_FILE, CONTEXT_FILE, MEMORY_LIMIT
from credentials import MEMORY_KEY_B64

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MEMORIES_FILE = FULL_MEMORY_FILE


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
    nonce = os.urandom(12)  # 96-bit nonce recommended for GCM
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


def save_memory(summary: str, full_memory: str) -> int:
    data = _read_json_encrypted(MEMORIES_FILE)
    if data is None:
        data = {"summaries": [], "memories": []}
    # Enforce limit
    if len(data.get("summaries", [])) >= MEMORY_LIMIT:
        data["summaries"].pop(0)
        data["memories"].pop(0)
    data.setdefault("summaries", []).append(summary)
    data.setdefault("memories", []).append(full_memory)
    _write_json_encrypted(MEMORIES_FILE, data)
    return len(data["summaries"])


def get_memory_detail(index: int) -> str:
    data = _read_json_encrypted(MEMORIES_FILE) or {"memories": []}
    memories = data.get("memories", [])
    if 1 <= index <= len(memories):
        return memories[index - 1]
    return ""


def get_all_summaries() -> list:
    data = _read_json_encrypted(MEMORIES_FILE) or {"summaries": []}
    return data.get("summaries", [])


def save_user_memory(user_id: str, summary: str, full_memory: str) -> int:
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
    return len(data[user_key]["summaries"])


def get_user_memory_detail(user_id: str, index: int) -> str:
    user_key = str(user_id)
    data = _read_json_encrypted(USER_MEMORIES_FILE) or {}
    if user_key in data:
        memories = data[user_key].get("memories", [])
        if 1 <= index <= len(memories):
            return memories[index - 1]
    return ""


def get_user_summaries(user_id: str) -> list:
    user_key = str(user_id)
    data = _read_json_encrypted(USER_MEMORIES_FILE) or {}
    if user_key in data:
        return data[user_key].get("summaries", [])
    return []


def save_context(user_id: str, channel_id: str) -> None:
    current_time = time.time()
    context = _read_json_encrypted(CONTEXT_FILE) or {}
    context[str(user_id)] = {"channel_id": channel_id, "timestamp": current_time}
    _write_json_encrypted(CONTEXT_FILE, context)


def get_channel_by_user(user_id: str):
    context = _read_json_encrypted(CONTEXT_FILE) or {}
    data = context.get(str(user_id), {})
    if isinstance(data, dict):
        return data.get("channel_id", ""), data.get("timestamp", 0)
    return "", 0