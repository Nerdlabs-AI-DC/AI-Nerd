#!/usr/bin/env python3
"""
migrate_to_sqlite.py

Script to migrate legacy JSON files into the new SQLite-backed storage.

Usage:
  python migrate_to_sqlite.py [--data-dir DATA_DIR] [--dry-run] [--overwrite]

This will look for common legacy files (in DATA_DIR and project root) and
copy their contents into the SQLite DB used by the project. For "memories"
files the script will use the project's memory encryption helper so contents
are encrypted the same way the bot expects.
"""
import argparse
import json
from pathlib import Path
import sys

# local imports (project modules)
import storage
import memory


FILE_MAPPINGS = {
    # plaintext JSON -> storage kv key
    "daily_message_counts.json": ("kv", "daily_message_counts"),
    "recent_questions.json": ("kv", "recent_questions"),
    "daily_quiz_records.json": ("kv", "daily_quiz_records"),
    "metrics.json": ("kv", "metrics"),
    "nerdscoredata.json": ("kv", "nerdscore"),
    "recent_freewill.json": ("kv", "recent_freewill"),
    "serversettings.json": ("kv", "serversettings"),
    "user_metrics.json": ("kv", "user_metrics"),
    "context_memory.json": ("kv", "context_memory"),

    # memories are stored as encrypted blobs
    "memories.json": ("blob", "memories_enc"),
    "user_memories.json": ("blob", "user_memories_enc"),
}


def load_json_file(path: Path):
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def load_bytes_file(path: Path):
    try:
        return path.read_bytes()
    except Exception:
        return None


def migrate_file(src: Path, kind: str, target_key: str, overwrite: bool, dry_run: bool):
    print(f"Processing {src} -> {kind}:{target_key}")

    if kind == "kv":
        data = load_json_file(src)
        if data is None:
            # try as bytes then decode
            b = load_bytes_file(src)
            if b is None:
                print(f"  could not read {src}")
                return False
            try:
                data = json.loads(b.decode("utf-8"))
            except Exception:
                print(f"  file not valid JSON, skipping {src}")
                return False

        existing = storage.get_json(target_key, None)
        if existing is not None and not overwrite:
            print(f"  target key '{target_key}' already exists in DB (use --overwrite to replace). Skipping")
            return False

        if dry_run:
            print(f"  dry-run: would set key '{target_key}' with JSON value (type={type(data).__name__})")
            return True

        storage.set_json(target_key, data)
        print(f"  migrated JSON -> {target_key}")
        return True

    if kind == "blob":
        # For memories we prefer to load JSON (if plaintext) and have memory._write_json_encrypted
        # encrypt and store it. If it's already binary/encoded, store raw bytes.
        data_json = load_json_file(src)
        if data_json is not None:
            if dry_run:
                print(f"  dry-run: would encrypt+store JSON -> blob '{target_key}' (via memory._write_json_encrypted)")
                return True
            # use the project's helper to write encrypted blob
            try:
                # memory._write_json_encrypted accepts a path_or_key and an object
                memory._write_json_encrypted(src.name, data_json)
                print(f"  migrated JSON -> encrypted blob {target_key}")
                return True
            except Exception as e:
                print(f"  failed to write encrypted blob for {src}: {e}")
                return False

        # not JSON - treat as binary (maybe already encrypted)
        b = load_bytes_file(src)
        if b is None:
            print(f"  could not read {src} as bytes, skipping")
            return False

        existing = storage.get_blob(target_key)
        if existing is not None and not overwrite:
            print(f"  target blob '{target_key}' already exists in DB (use --overwrite to replace). Skipping")
            return False

        if dry_run:
            print(f"  dry-run: would write {len(b)} bytes into blob '{target_key}'")
            return True

        storage.set_blob(target_key, b)
        print(f"  migrated bytes -> blob {target_key} (size={len(b)} bytes)")
        return True

    print(f"Unknown kind {kind}")
    return False


def find_candidates(data_dir: Path):
    found = []
    # look in provided data_dir and project root
    locations = [data_dir, Path(".")]
    seen = set()
    for loc in locations:
        if not loc.exists():
            continue
        for name, (kind, key) in FILE_MAPPINGS.items():
            p = loc / name
            if p.exists() and p not in seen:
                found.append((p, kind, key))
                seen.add(p)
    return found


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--data-dir", default="data", help="Directory containing legacy JSON files (default: data)")
    p.add_argument("--dry-run", action="store_true", help="Show what would be migrated without writing to DB")
    p.add_argument("--overwrite", action="store_true", help="Overwrite existing keys/blobs in DB")
    args = p.parse_args()

    data_dir = Path(args.data_dir)
    candidates = find_candidates(data_dir)
    if not candidates:
        print("No legacy files found to migrate. Looked in:", data_dir, Path('.'))
        return 0

    print(f"Found {len(candidates)} files to consider for migration:")
    for pth, kind, key in candidates:
        print(f" - {pth} -> {kind}:{key}")

    migrated = 0
    for pth, kind, key in candidates:
        ok = migrate_file(pth, kind, key, overwrite=args.overwrite, dry_run=args.dry_run)
        if ok:
            migrated += 1

    print(f"Migration complete: {migrated}/{len(candidates)} processed (dry-run={args.dry_run})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
