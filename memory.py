import os
import json
import time
from config import FULL_MEMORY_FILE, USER_MEMORIES_FILE, CONTEXT_FILE, MEMORY_LIMIT

MEMORIES_FILE = FULL_MEMORY_FILE

def init_memory_files():
    if not os.path.isfile(MEMORIES_FILE):
        with open(MEMORIES_FILE, 'w', encoding='utf-8') as f:
            json.dump({"summaries": [], "memories": []}, f)
    if not os.path.isfile(USER_MEMORIES_FILE):
        with open(USER_MEMORIES_FILE, 'w', encoding='utf-8') as f:
            json.dump({}, f)


def save_memory(summary: str, full_memory: str) -> int:
    with open(MEMORIES_FILE, 'r+', encoding='utf-8') as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            data = {"summaries": [], "memories": []}
        # Enforce limit of 50
        if len(data["summaries"]) >= MEMORY_LIMIT:
            data["summaries"].pop(0)
            data["memories"].pop(0)
        data["summaries"].append(summary)
        data["memories"].append(full_memory)
        f.seek(0)
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.truncate()
    return len(data["summaries"])


def get_memory_detail(index: int) -> str:
    with open(MEMORIES_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
    memories = data.get("memories", [])
    if 1 <= index <= len(memories):
        return memories[index - 1]
    return ""


def save_user_memory(user_id: str, summary: str, full_memory: str) -> int:
    user_key = str(user_id)
    with open(USER_MEMORIES_FILE, 'r+', encoding='utf-8') as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            data = {}
        if user_key not in data:
            data[user_key] = {"summaries": [], "memories": []}
        # Enforce limit of 50 per user
        if len(data[user_key]["summaries"]) >= MEMORY_LIMIT:
            data[user_key]["summaries"].pop(0)
            data[user_key]["memories"].pop(0)
        data[user_key]["summaries"].append(summary)
        data[user_key]["memories"].append(full_memory)
        f.seek(0)
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.truncate()
    return len(data[user_key]["summaries"])


def get_user_memory_detail(user_id: str, index: int) -> str:
    user_key = str(user_id)
    with open(USER_MEMORIES_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if user_key in data:
        memories = data[user_key]["memories"]
        if 1 <= index <= len(memories):
            return memories[index - 1]
    return ""


def save_context(user_id: str, channel_id: str) -> None:
    current_time = time.time()
    try:
        with open(CONTEXT_FILE, 'r+', encoding='utf-8') as f:
            try:
                context = json.load(f)
                if not isinstance(context, dict):
                    context = {}
            except json.JSONDecodeError:
                context = {}
            context[str(user_id)] = {"channel_id": channel_id, "timestamp": current_time}
            f.seek(0)
            json.dump(context, f, indent=2, ensure_ascii=False)
            f.truncate()
    except FileNotFoundError:
        with open(CONTEXT_FILE, 'w', encoding='utf-8') as f:
            context = {str(user_id): {"channel_id": channel_id, "timestamp": current_time}}
            json.dump(context, f, indent=2, ensure_ascii=False)


def get_channel_by_user(user_id: str):
    try:
        with open(CONTEXT_FILE, 'r', encoding='utf-8') as f:
            context = json.load(f)
            data = context.get(str(user_id), {})
            if isinstance(data, dict):
                return data.get("channel_id", ""), data.get("timestamp", 0)
            return "", 0
    except (FileNotFoundError, json.JSONDecodeError):
        return "", 0