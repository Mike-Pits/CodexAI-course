"""SQLite persistence for users, long-term memory and dialogue history."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.store import PUBLIC_PROFILE_FIELDS, hash_password, verify_password


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self._initialize()

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        schema = """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            role TEXT NOT NULL CHECK (role IN ('client', 'admin')),
            display_name TEXT NOT NULL,
            password_salt TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            key TEXT NOT NULL,
            value TEXT NOT NULL CHECK (length(value) BETWEEN 1 AND 300),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (user_id, key)
        );
        CREATE TABLE IF NOT EXISTS dialogs (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dialog_id TEXT NOT NULL REFERENCES dialogs(id) ON DELETE CASCADE,
            role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
            content TEXT NOT NULL CHECK (length(content) BETWEEN 1 AND 10000),
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_memories_user ON memories(user_id);
        CREATE INDEX IF NOT EXISTS idx_dialogs_user_updated ON dialogs(user_id, updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_messages_dialog_id ON messages(dialog_id, id);
        """
        with self.lock, self.connect() as connection:
            connection.executescript(schema)
            count = connection.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            if count == 0:
                self._seed(connection)

    def _seed(self, connection: sqlite3.Connection) -> None:
        created = now()
        fixtures = [
            ("anna", "client", "Анна", "anna-demo", {
                "goal": "автоматизировать еженедельные отчёты в Excel",
                "budget": "до 12 000 ₽",
                "format": "самостоятельно",
                "pace": "4 часа в неделю",
                "experience": "начинающий",
            }),
            ("boris", "client", "Борис", "boris-demo", {
                "goal": "перейти в Python-разработку",
                "budget": "до 25 000 ₽",
                "format": "с наставником",
                "pace": "6 часов в неделю",
                "experience": "писал небольшие скрипты",
            }),
            ("admin", "admin", "Администратор", "admin-demo", {}),
        ]
        for username, role, name, password, memories in fixtures:
            salt, digest = hash_password(password)
            connection.execute(
                "INSERT INTO users VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (username, username, role, name, salt, digest, created, created),
            )
            for key, value in memories.items():
                connection.execute(
                    "INSERT INTO memories(user_id, key, value, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                    (username, key, value, created, created),
                )

    def _memory(self, connection: sqlite3.Connection, user_id: str) -> dict[str, str]:
        rows = connection.execute(
            "SELECT key, value FROM memories WHERE user_id = ? ORDER BY key", (user_id,)
        ).fetchall()
        return {row["key"]: row["value"] for row in rows}

    def _public_user(self, connection: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "username": row["username"],
            "role": row["role"],
            "profile": {"name": row["display_name"], **self._memory(connection, row["id"])},
            "updated_at": row["updated_at"],
        }

    def authenticate(self, username: str, password: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
            if not row or not verify_password(password, row["password_salt"], row["password_hash"]):
                return None
            return self._public_user(connection, row)

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            return self._public_user(connection, row) if row else None

    def list_users(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM users ORDER BY role DESC, username").fetchall()
            return [self._public_user(connection, row) for row in rows]

    @staticmethod
    def _validate_memory(values: dict[str, str]) -> dict[str, str]:
        if not isinstance(values, dict):
            raise ValueError("Ожидался объект со сведениями")
        clean = {}
        for key, value in values.items():
            if key not in PUBLIC_PROFILE_FIELDS:
                raise ValueError(f"Поле {key!r} нельзя сохранять")
            if not isinstance(value, str):
                raise ValueError("Значения должны быть строками")
            value = " ".join(value.split())
            if len(value) > 300:
                raise ValueError("Значение длиннее 300 символов")
            clean[key] = value
        return clean

    def update_memory(self, user_id: str, values: dict[str, str]) -> dict[str, Any]:
        clean = self._validate_memory(values)
        changed = now()
        with self.lock, self.connect() as connection:
            exists = connection.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone()
            if not exists:
                raise KeyError("Пользователь не найден")
            for key, value in clean.items():
                if key == "name":
                    if not value:
                        raise ValueError("Имя пользователя нельзя удалить")
                    connection.execute(
                        "UPDATE users SET display_name = ?, updated_at = ? WHERE id = ?",
                        (value, changed, user_id),
                    )
                elif value:
                    connection.execute(
                        """INSERT INTO memories(user_id, key, value, created_at, updated_at)
                           VALUES (?, ?, ?, ?, ?)
                           ON CONFLICT(user_id, key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
                        (user_id, key, value, changed, changed),
                    )
                else:
                    connection.execute("DELETE FROM memories WHERE user_id = ? AND key = ?", (user_id, key))
            connection.execute("UPDATE users SET updated_at = ? WHERE id = ?", (changed, user_id))
        return self.get_user(user_id)

    def delete_memory(self, user_id: str, key: str) -> dict[str, Any]:
        if key not in PUBLIC_PROFILE_FIELDS or key == "name":
            raise ValueError("Это поле нельзя удалить")
        with self.lock, self.connect() as connection:
            exists = connection.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone()
            if not exists:
                raise KeyError("Пользователь не найден")
            connection.execute("DELETE FROM memories WHERE user_id = ? AND key = ?", (user_id, key))
            connection.execute("UPDATE users SET updated_at = ? WHERE id = ?", (now(), user_id))
        return self.get_user(user_id)

    def create_dialog(self, user_id: str, title: str = "Новый диалог") -> dict[str, Any]:
        dialog_id = str(uuid.uuid4())
        created = now()
        with self.lock, self.connect() as connection:
            connection.execute(
                "INSERT INTO dialogs(id, user_id, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (dialog_id, user_id, title, created, created),
            )
        return {"id": dialog_id, "title": title, "created_at": created, "updated_at": created}

    def add_message(self, dialog_id: str, user_id: str, role: str, content: str) -> None:
        if role not in ("user", "assistant") or not 1 <= len(content) <= 10_000:
            raise ValueError("Некорректное сообщение")
        changed = now()
        with self.lock, self.connect() as connection:
            dialog = connection.execute(
                "SELECT id FROM dialogs WHERE id = ? AND user_id = ?", (dialog_id, user_id)
            ).fetchone()
            if not dialog:
                raise PermissionError("Диалог не принадлежит пользователю")
            connection.execute(
                "INSERT INTO messages(dialog_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                (dialog_id, role, content, changed),
            )
            if role == "user":
                count = connection.execute(
                    "SELECT COUNT(*) FROM messages WHERE dialog_id = ? AND role = 'user'", (dialog_id,)
                ).fetchone()[0]
                if count == 1:
                    title = content[:70] + ("…" if len(content) > 70 else "")
                    connection.execute("UPDATE dialogs SET title = ? WHERE id = ?", (title, dialog_id))
            connection.execute("UPDATE dialogs SET updated_at = ? WHERE id = ?", (changed, dialog_id))

    def history(self, dialog_id: str, user_id: str, limit: int = 42) -> list[dict[str, str]]:
        with self.connect() as connection:
            owner = connection.execute(
                "SELECT 1 FROM dialogs WHERE id = ? AND user_id = ?", (dialog_id, user_id)
            ).fetchone()
            if not owner:
                raise PermissionError("Диалог не принадлежит пользователю")
            rows = connection.execute(
                """SELECT role, content FROM (
                       SELECT id, role, content FROM messages WHERE dialog_id = ? ORDER BY id DESC LIMIT ?
                   ) ORDER BY id""",
                (dialog_id, limit),
            ).fetchall()
            return [{"role": row["role"], "content": row["content"]} for row in rows]

    def list_dialogs(self, user_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT d.id, d.title, d.created_at, d.updated_at, COUNT(m.id) AS message_count
                   FROM dialogs d LEFT JOIN messages m ON m.dialog_id = d.id
                   WHERE d.user_id = ? GROUP BY d.id ORDER BY d.updated_at DESC""",
                (user_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def delete_dialog(self, dialog_id: str, user_id: str) -> None:
        with self.lock, self.connect() as connection:
            cursor = connection.execute("DELETE FROM dialogs WHERE id = ? AND user_id = ?", (dialog_id, user_id))
            if cursor.rowcount != 1:
                raise PermissionError("Диалог не принадлежит пользователю")

    def counts(self) -> dict[str, int]:
        with self.connect() as connection:
            return {
                table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ("users", "memories", "dialogs", "messages")
            }

