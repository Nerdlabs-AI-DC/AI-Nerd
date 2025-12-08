import threading
import time
import shutil
import sqlite3
from pathlib import Path
from datetime import datetime, timezone, timedelta


class BackupManager:
    def __init__(self, db_path: Path, backups_dir: Path = None, interval_hours: float = 12.0, retain_days: int = 7, max_backups: int = 14):
        self.db_path = Path(db_path)
        self.backups_dir = Path(backups_dir) if backups_dir is not None else (self.db_path.parent / "backups")
        self.interval = int(interval_hours * 3600)
        self.retain_days = retain_days
        self.max_backups = max_backups
        self._thread = None
        self._stop_event = threading.Event()

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="BackupManager")
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=1)

    def _run_loop(self):
        while not self._stop_event.is_set():
            try:
                delay = self._seconds_until_next_backup()
                start = time.time()
                while not self._stop_event.is_set() and time.time() - start < delay:
                    time.sleep(1)

                if self._stop_event.is_set():
                    break

                self._make_backup()
            except Exception:
                pass

    def _make_backup(self):
        if not self.db_path.exists():
            return
        self.backups_dir.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc)
        ts = now.strftime("%Y%m%d%H%M%S")
        dest_name = f"{self.db_path.stem}-{ts}{self.db_path.suffix}"
        dest_path = self.backups_dir / dest_name

        try:
            with sqlite3.connect(str(self.db_path)) as src_conn:
                with sqlite3.connect(str(dest_path)) as dst_conn:
                    src_conn.backup(dst_conn)
        except Exception:
            try:
                shutil.copy2(str(self.db_path), str(dest_path))
            except Exception:
                return

        try:
            self._prune_backups()
        except Exception:
            pass

    def _get_latest_backup_mtime(self):
        if not self.backups_dir.exists():
            return None
        files = [p for p in self.backups_dir.iterdir() if p.is_file()]
        if not files:
            return None
        latest = max(files, key=lambda p: p.stat().st_mtime)
        try:
            return datetime.fromtimestamp(latest.stat().st_mtime, timezone.utc)
        except Exception:
            return None

    def _seconds_until_next_backup(self):
        latest = self._get_latest_backup_mtime()
        now = datetime.now(timezone.utc)
        if latest is None:
            return 0
        next_time = latest + timedelta(seconds=self.interval)
        delta = (next_time - now).total_seconds()
        return max(0, int(delta))

    def _prune_backups(self):
        files = [p for p in self.backups_dir.iterdir() if p.is_file()]
        if not files:
            return
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.retain_days)
        for p in files:
            try:
                mtime = datetime.fromtimestamp(p.stat().st_mtime, timezone.utc)
                if mtime < cutoff:
                    p.unlink()
            except Exception:
                continue

        files = sorted([p for p in self.backups_dir.iterdir() if p.is_file()], key=lambda x: x.stat().st_mtime)
        while len(files) > self.max_backups:
            try:
                files[0].unlink()
            except Exception:
                pass
            files = sorted([p for p in self.backups_dir.iterdir() if p.is_file()], key=lambda x: x.stat().st_mtime)


__all__ = ["BackupManager"]
