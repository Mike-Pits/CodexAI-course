"""SQLite transactions and schema migration. Files belong to their meeting UUID."""

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from .config import DATA

TURSO_DATABASE_URL = os.environ.get("TURSO_DATABASE_URL")
TURSO_AUTH_TOKEN = os.environ.get("TURSO_AUTH_TOKEN")


class _RemoteCursor:
    def __init__(self, cursor):
        self.cursor = cursor
        self.columns = [column[0] for column in (cursor.description or [])]

    def fetchone(self):
        row = self.cursor.fetchone()
        return _RemoteRow(zip(self.columns, row)) if row is not None else None

    def fetchall(self):
        return [_RemoteRow(zip(self.columns, row)) for row in self.cursor.fetchall()]

    def __iter__(self):
        return iter(self.fetchall())


class _RemoteRow(dict):
    def __getitem__(self, key):
        if isinstance(key, int):
            return tuple(self.values())[key]
        return super().__getitem__(key)


class _RemoteConnection:
    """DB-API adapter backed by an embedded Turso replica in Vercel's /tmp."""

    def __init__(self):
        import libsql

        DATA.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.remote = not (TURSO_DATABASE_URL or "").startswith("file:")
        if self.remote:
            self.database = libsql.connect(
                str(DATA / "turso-replica.sqlite3"),
                sync_url=TURSO_DATABASE_URL,
                auth_token=TURSO_AUTH_TOKEN or "",
            )
            self.database.sync()
        else:
            self.database = libsql.connect((TURSO_DATABASE_URL or "").removeprefix("file://"))

    def execute(self, statement, parameters=()):
        if statement.strip().upper().startswith("BEGIN"):
            return _RemoteCursor(self.database.execute("SELECT 1 WHERE 0"))
        return _RemoteCursor(self.database.execute(statement, tuple(parameters)))

    def executescript(self, script):
        self.database.executescript(script)

    def commit(self):
        self.database.commit()
        if self.remote:
            self.database.sync()

    def rollback(self):
        self.database.rollback()

    def close(self):
        self.database.close()


def now():
    return datetime.now(timezone.utc).isoformat()


def uid():
    return uuid.uuid4().hex


@contextmanager
def connect():
    if TURSO_DATABASE_URL:
        database = _RemoteConnection()
        try:
            yield database
            database.commit()
        except BaseException:
            database.rollback()
            raise
        finally:
            database.close()
        return
    db = sqlite3.connect(DATA / "meetings.sqlite3", timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    try:
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def initialize():
    DATA.mkdir(parents=True, exist_ok=True, mode=0o700)
    (DATA / "files").mkdir(exist_ok=True, mode=0o700)
    with connect() as db:
        if not TURSO_DATABASE_URL:
            db.execute("PRAGMA journal_mode=WAL")
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version == 0:
            db.executescript("""
            CREATE TABLE meetings (
                id TEXT PRIMARY KEY, title TEXT NOT NULL, meeting_date TEXT NOT NULL,
                text TEXT NOT NULL DEFAULT '', version INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                deleted INTEGER NOT NULL DEFAULT 0,
                source TEXT NOT NULL DEFAULT 'manual', source_url TEXT,
                source_key TEXT);
            CREATE TABLE files (
                id TEXT PRIMARY KEY, meeting_id TEXT NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
                name TEXT NOT NULL, path TEXT NOT NULL, kind TEXT NOT NULL,
                duration REAL, created_at TEXT NOT NULL, checksum TEXT);
            CREATE TABLE jobs (
                id TEXT PRIMARY KEY, meeting_id TEXT NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
                kind TEXT NOT NULL, state TEXT NOT NULL, stage TEXT NOT NULL,
                source_text TEXT NOT NULL, source_date TEXT NOT NULL, source_version INTEGER NOT NULL,
                file_id TEXT REFERENCES files(id) ON DELETE CASCADE,
                error TEXT, created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT);
            CREATE TABLE results (
                id TEXT PRIMARY KEY, meeting_id TEXT NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
                kind TEXT NOT NULL, payload TEXT NOT NULL,
                source_text TEXT NOT NULL, source_date TEXT NOT NULL,
                model TEXT NOT NULL, created_at TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 0, manual INTEGER NOT NULL DEFAULT 0,
                UNIQUE(meeting_id, kind));
            CREATE INDEX jobs_queue ON jobs(state, created_at);
            CREATE UNIQUE INDEX meetings_source_key ON meetings(source_key) WHERE source_key IS NOT NULL;
            PRAGMA user_version=2;
            """)
        elif version == 1:
            db.executescript("""
            ALTER TABLE meetings ADD COLUMN source TEXT NOT NULL DEFAULT 'manual';
            ALTER TABLE meetings ADD COLUMN source_url TEXT;
            ALTER TABLE meetings ADD COLUMN source_key TEXT;
            ALTER TABLE files ADD COLUMN checksum TEXT;
            CREATE UNIQUE INDEX meetings_source_key ON meetings(source_key) WHERE source_key IS NOT NULL;
            PRAGMA user_version=2;
            """)


def meeting(db, ident):
    row = db.execute(
        "SELECT * FROM meetings WHERE id=? AND deleted=0", (ident,)
    ).fetchone()
    if not row:
        raise LookupError("Встреча не найдена")
    return dict(row)


def details(ident):
    with connect() as db:
        item = meeting(db, ident)
        item["files"] = [
            dict(r)
            for r in db.execute(
                "SELECT id,name,kind,duration,checksum FROM files WHERE meeting_id=? ORDER BY created_at",
                (ident,),
            )
        ]
        item["jobs"] = [
            dict(r)
            for r in db.execute(
                "SELECT id,kind,state,stage,error,created_at,started_at,finished_at FROM jobs WHERE meeting_id=? ORDER BY created_at DESC",
                (ident,),
            )
        ]
        item["results"] = {}
        for row in db.execute("SELECT * FROM results WHERE meeting_id=?", (ident,)):
            result = dict(row)
            result["payload"] = json.loads(result["payload"])
            result["stale"] = (
                result["source_text"] != item["text"]
                or result["source_date"] != item["meeting_date"]
            )
            item["results"][row["kind"]] = result
        return item
