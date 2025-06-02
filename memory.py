import os
import json
from config import SUMMARIES_FILE, FULL_MEMORY_FILE, USER_MEMORIES_FILE


def init_memory_files():
    for path in (SUMMARIES_FILE, FULL_MEMORY_FILE):
        if not os.path.isfile(path):
            with open(path, 'w', encoding='utf-8') as f:
                json.dump([], f)
    if not os.path.isfile(USER_MEMORIES_FILE):
        with open(USER_MEMORIES_FILE, 'w', encoding='utf-8') as f:
            json.dump({}, f)


def save_memory(summary: str, full_memory: str) -> int:
    with open(SUMMARIES_FILE, 'r+', encoding='utf-8') as sf, \
         open(FULL_MEMORY_FILE, 'r+', encoding='utf-8') as mf:
        summaries = json.load(sf)
        memories = json.load(mf)
        summaries.append(summary)
        memories.append(full_memory)
        sf.seek(0)
        json.dump(summaries, sf, indent=2, ensure_ascii=False)
        sf.truncate()
        mf.seek(0)
        json.dump(memories, mf, indent=2, ensure_ascii=False)
        mf.truncate()
    return len(summaries)


def get_memory_detail(index: int) -> str:
    with open(FULL_MEMORY_FILE, 'r', encoding='utf-8') as f:
        memories = json.load(f)
    if 1 <= index <= len(memories):
        return memories[index - 1]
    return ""


def save_user_memory(user_id: str, summary: str, full_memory: str) -> int:
    with open(USER_MEMORIES_FILE, 'r+', encoding='utf-8') as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            data = {}
        if user_id not in data:
            data[user_id] = {"summaries": [], "memories": []}
        data[user_id]["summaries"].append(summary)
        data[user_id]["memories"].append(full_memory)
        f.seek(0)
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.truncate()
    return len(data[user_id]["summaries"])


def get_user_memory_detail(user_id: str, index: int) -> str:
    user_key = str(user_id)
    with open(USER_MEMORIES_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if user_key in data:
        memories = data[user_key]["memories"]
        if 1 <= index <= len(memories):
            return memories[index - 1]
    return ""