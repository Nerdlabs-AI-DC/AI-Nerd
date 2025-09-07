from memory import _write_json_encrypted
from config import FULL_MEMORY_FILE, USER_MEMORIES_FILE, CONTEXT_FILE
import json

files = [FULL_MEMORY_FILE, USER_MEMORIES_FILE, CONTEXT_FILE]

for f in files:
    try:
        with open(f, 'r', encoding='utf-8') as file:
            data = json.load(file)
    except Exception:
        print(f"{f} is already encrypted or couldn't be read, skip...")
        continue

    _write_json_encrypted(f, data)
    print(f"{f} is now encrypted.")
