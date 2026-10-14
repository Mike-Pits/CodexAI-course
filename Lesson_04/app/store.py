"""Thread-safe JSON persistence and role-aware user operations."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any


PUBLIC_PROFILE_FIELDS = ("name", "goal", "budget", "format", "pace", "experience")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 200_000)
    return salt, digest.hex()


def verify_password(password: str, salt: str, expected: str) -> bool:
    _, actual = hash_password(password, salt)
    return hmac.compare_digest(actual, expected)


def demo_data() -> dict[str, Any]:
    users = []
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
    for username, role, name, password, memory in fixtures:
        salt, digest = hash_password(password)
        users.append({
            "id": username,
            "username": username,
            "role": role,
            "password_salt": salt,
            "password_hash": digest,
            "profile": {"name": name, **memory},
            "updated_at": _now(),
        })
    return {"schema_version": 1, "users": users}


class JsonStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.lock = RLock()
        if not self.path.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._write(demo_data())
        self._read()

    def _read(self) -> dict[str, Any]:
        with self.lock:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        if data.get("schema_version") != 1 or not isinstance(data.get("users"), list):
            raise ValueError("Неподдерживаемая структура JSON-хранилища")
        return data

    def _write(self, data: dict[str, Any]) -> None:
        with self.lock:
            temp = self.path.with_suffix(self.path.suffix + ".tmp")
            temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            temp.replace(self.path)

    @staticmethod
    def public_user(user: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": user["id"],
            "username": user["username"],
            "role": user["role"],
            "profile": deepcopy(user.get("profile", {})),
            "updated_at": user.get("updated_at"),
        }

    def authenticate(self, username: str, password: str) -> dict[str, Any] | None:
        data = self._read()
        for user in data["users"]:
            if user["username"] == username and verify_password(
                password, user["password_salt"], user["password_hash"]
            ):
                return self.public_user(user)
        return None

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        for user in self._read()["users"]:
            if user["id"] == user_id:
                return self.public_user(user)
        return None

    def list_users(self) -> list[dict[str, Any]]:
        return [self.public_user(user) for user in self._read()["users"]]

    def update_profile(self, user_id: str, values: dict[str, str]) -> dict[str, Any]:
        clean: dict[str, str] = {}
        for key, value in values.items():
            if key not in PUBLIC_PROFILE_FIELDS:
                raise ValueError(f"Поле {key!r} нельзя сохранять")
            if not isinstance(value, str):
                raise ValueError("Значения профиля должны быть строками")
            value = value.strip()
            if len(value) > 300:
                raise ValueError("Значение профиля длиннее 300 символов")
            clean[key] = value
        with self.lock:
            data = self._read()
            for user in data["users"]:
                if user["id"] == user_id:
                    profile = user.setdefault("profile", {})
                    for key, value in clean.items():
                        if value:
                            profile[key] = value
                        else:
                            profile.pop(key, None)
                    user["updated_at"] = _now()
                    self._write(data)
                    return self.public_user(user)
        raise KeyError("Пользователь не найден")

