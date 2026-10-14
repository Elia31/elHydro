# src/core/log_store.py
# Log-Verwaltung: speichert und liest System-Logeinträge als JSON-Dateien.
import json
import os
import time
import threading


class LogStore:
    # Nach so vielen neuen Einträgen wird die Datei auf max_lines gekürzt
    ROTATE_EVERY = 500

    def __init__(self, log_file: str, max_lines: int = 5000):
        self.log_file = log_file
        self.max_lines = max_lines
        self._lock = threading.Lock()
        self._appends_since_rotate = 0
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        self.rotate()

    def append(self, message: str, level: str = "INFO", mac: str = None):
        entry = {
            "ts": int(time.time()),
            "level": level,
            "mac": mac,
            "msg": message,
        }
        with self._lock:
            try:
                with open(self.log_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            except Exception:
                pass
            self._appends_since_rotate += 1
            needs_rotate = self._appends_since_rotate >= self.ROTATE_EVERY

        if needs_rotate:
            self.rotate()

    def get_logs(self, limit: int = 200, mac: str = None, level: str = None) -> list:
        if not os.path.exists(self.log_file):
            return []

        try:
            with open(self.log_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except Exception:
            return []

        result = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if mac and entry.get("mac") != mac:
                continue
            if level and entry.get("level") != level:
                continue
            result.append(entry)

        return result[-limit:]

    def rotate(self):
        if not os.path.exists(self.log_file):
            return
        with self._lock:
            self._appends_since_rotate = 0
            try:
                with open(self.log_file, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                if len(lines) > self.max_lines:
                    with open(self.log_file, "w", encoding="utf-8") as f:
                        f.writelines(lines[-self.max_lines:])
            except Exception:
                pass
