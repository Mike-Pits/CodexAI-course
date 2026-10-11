"""Persistent aggregate quotas; never stores messages or raw IP addresses."""
import hashlib
import hmac
import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class Quotas:
    def __init__(self, path: str, secret: str, per_minute: int, per_day: int):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path, self.secret = path, secret
        self.per_minute, self.per_day = per_minute, per_day
        with sqlite3.connect(path) as db:
            db.execute('CREATE TABLE IF NOT EXISTS daily (day TEXT PRIMARY KEY, count INTEGER NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS hits (ip TEXT NOT NULL, ts REAL NOT NULL)')
            db.execute('CREATE INDEX IF NOT EXISTS hits_ip_ts ON hits(ip, ts)')

    def reserve(self, ip: str, now: float) -> tuple[str, int] | None:
        day = datetime.fromtimestamp(now, timezone.utc).date().isoformat()
        hashed = hmac.new(self.secret.encode(), ip.encode(), hashlib.sha256).hexdigest()
        with sqlite3.connect(self.path, timeout=5) as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM hits WHERE ts <= ?', (now - 60,))
            db.execute('DELETE FROM daily WHERE day != ?', (day,))
            count, oldest = db.execute('SELECT COUNT(*), MIN(ts) FROM hits WHERE ip = ?', (hashed,)).fetchone()
            if count >= self.per_minute:
                return ('Слишком много сообщений. Подождите минуту.', max(1, math.ceil(oldest + 60 - now)))
            daily = db.execute('SELECT count FROM daily WHERE day = ?', (day,)).fetchone()
            if daily and daily[0] >= self.per_day:
                return ('Лимит учебного чата на сегодня исчерпан. Попробуйте завтра.', math.ceil(86400 - now % 86400))
            db.execute('INSERT INTO hits VALUES (?, ?)', (hashed, now))
            db.execute('INSERT INTO daily VALUES (?, 1) ON CONFLICT(day) DO UPDATE SET count = count + 1', (day,))
        return None
