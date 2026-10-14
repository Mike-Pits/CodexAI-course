"""Pro web server using SQLite for memory, users and dialogue history."""

from __future__ import annotations

import json
import os
import secrets
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import RLock
from urllib.parse import unquote, urlparse

from app.agent import PRODUCT, extract_facts, model_reply
from app.server import load_environment
from pro.db import Database


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"


class ProApplication:
    def __init__(self, db_path: str | Path | None = None):
        self.db = Database(db_path or os.getenv("PRO_DB_PATH", ROOT / "data" / "pro.sqlite3"))
        self.sessions: dict[str, dict] = {}
        self.lock = RLock()

    def login(self, username: str, password: str):
        user = self.db.authenticate(username, password)
        if not user:
            return None
        token = secrets.token_urlsafe(32)
        with self.lock:
            self.sessions[token] = {"user_id": user["id"], "dialog_id": None}
        return token, user

    def session(self, token: str | None):
        with self.lock:
            state = self.sessions.get(token or "")
        if not state:
            return None
        user = self.db.get_user(state["user_id"])
        return (state, user) if user else None

    def logout(self, token: str | None):
        with self.lock:
            self.sessions.pop(token or "", None)

    @staticmethod
    def require_admin(actor: dict) -> None:
        if actor["role"] != "admin":
            raise PermissionError("Требуются права администратора")

    @staticmethod
    def require_owner_or_admin(actor: dict, target_id: str) -> None:
        if actor["role"] != "admin" and actor["id"] != target_id:
            raise PermissionError("Нет доступа к данным другого пользователя")

    def list_users(self, actor: dict):
        self.require_admin(actor)
        return self.db.list_users()

    def update_memory(self, actor: dict, target_id: str, values: dict):
        self.require_owner_or_admin(actor, target_id)
        return self.db.update_memory(target_id, values)

    def delete_memory(self, actor: dict, target_id: str, key: str):
        self.require_owner_or_admin(actor, target_id)
        return self.db.delete_memory(target_id, key)

    def new_dialog(self, state: dict, actor: dict):
        if actor["role"] != "client":
            raise PermissionError("Диалоги доступны только клиенту")
        dialog = self.db.create_dialog(actor["id"])
        state["dialog_id"] = dialog["id"]
        return dialog

    def select_dialog(self, state: dict, actor: dict, dialog_id: str):
        history = self.db.history(dialog_id, actor["id"])
        state["dialog_id"] = dialog_id
        return history

    def chat(self, state: dict, actor: dict, message: str):
        if actor["role"] != "client":
            raise PermissionError("Чат доступен только клиенту")
        message = " ".join(str(message).split())
        if not 1 <= len(message) <= 2000:
            raise ValueError("Сообщение должно содержать от 1 до 2000 символов")
        if not state.get("dialog_id"):
            self.new_dialog(state, actor)
        dialog_id = state["dialog_id"]
        self.db.add_message(dialog_id, actor["id"], "user", message)
        facts = extract_facts(message)
        if facts:
            actor = self.db.update_memory(actor["id"], facts)
        history = self.db.history(dialog_id, actor["id"])
        reply = model_reply(actor["profile"], history)
        self.db.add_message(dialog_id, actor["id"], "assistant", reply)
        return {
            "dialog_id": dialog_id,
            "message": reply,
            "saved": facts,
            "profile": actor["profile"],
            "history": self.db.history(dialog_id, actor["id"]),
        }


load_environment()
APP = ProApplication()


class Handler(BaseHTTPRequestHandler):
    server_version = "PracticePro/1.0"

    def log_message(self, format: str, *args) -> None:
        print(f"{self.address_string()} - {format % args}")

    def send_json(self, code, value, headers=None):
        body = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; object-src 'none'; base-uri 'none'")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path, mime):
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def token(self):
        jar = cookies.SimpleCookie(self.headers.get("Cookie", ""))
        return jar["pro_session"].value if "pro_session" in jar else None

    def auth(self):
        return APP.session(self.token())

    def read_json(self):
        if self.headers.get("Content-Type", "").split(";", 1)[0] != "application/json":
            raise ValueError("Требуется JSON")
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 < length <= 100_000:
            raise ValueError("Недопустимый размер запроса")
        value = json.loads(self.rfile.read(length))
        if not isinstance(value, dict):
            raise ValueError("Ожидался JSON-объект")
        return value

    def same_origin(self):
        origin = self.headers.get("Origin")
        return not origin or origin == "http://" + self.headers.get("Host", "")

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/config":
            return self.send_json(200, {"product": PRODUCT, "model": os.getenv("WORKER_MODEL") or "локальный демо-режим", "storage": "SQLite"})
        if path == "/api/me":
            auth = self.auth()
            return self.send_json(200, {"user": auth[1] if auth else None})
        auth = self.auth()
        if path.startswith("/api/") and not auth:
            return self.send_json(401, {"error": "Сначала войдите"})
        if path == "/api/memory":
            return self.send_json(200, {"user": auth[1]})
        if path == "/api/dialogs":
            if auth[1]["role"] != "client":
                return self.send_json(403, {"error": "Диалоги доступны только клиенту"})
            return self.send_json(200, {"dialogs": APP.db.list_dialogs(auth[1]["id"])})
        if path.startswith("/api/dialogs/"):
            try:
                dialog_id = unquote(path.removeprefix("/api/dialogs/"))
                history = APP.select_dialog(auth[0], auth[1], dialog_id)
                return self.send_json(200, {"dialog_id": dialog_id, "history": history})
            except PermissionError as exc:
                return self.send_json(403, {"error": str(exc)})
        if path == "/api/users":
            try:
                return self.send_json(200, {"users": APP.list_users(auth[1])})
            except PermissionError as exc:
                return self.send_json(403, {"error": str(exc)})
        files = {
            "/": (STATIC / "pro-index.html", "text/html; charset=utf-8"),
            "/pro-app.js": (STATIC / "pro-app.js", "text/javascript; charset=utf-8"),
            "/style.css": (STATIC / "style.css", "text/css; charset=utf-8"),
            "/pro-style.css": (STATIC / "pro-style.css", "text/css; charset=utf-8"),
        }
        if path in files:
            return self.send_file(*files[path])
        return self.send_json(404, {"error": "Не найдено"})

    def do_POST(self):
        if not self.same_origin():
            return self.send_json(403, {"error": "Недопустимый источник запроса"})
        try:
            data = self.read_json()
            path = urlparse(self.path).path
            if path == "/api/login":
                result = APP.login(str(data.get("username", "")), str(data.get("password", "")))
                if not result:
                    return self.send_json(401, {"error": "Неверный логин или пароль"})
                token, user = result
                return self.send_json(200, {"user": user}, {"Set-Cookie": f"pro_session={token}; HttpOnly; SameSite=Strict; Path=/"})
            if path == "/api/logout":
                APP.logout(self.token())
                return self.send_json(200, {"ok": True}, {"Set-Cookie": "pro_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"})
            auth = self.auth()
            if not auth:
                return self.send_json(401, {"error": "Сначала войдите"})
            state, actor = auth
            if path == "/api/chat":
                return self.send_json(200, APP.chat(state, actor, data.get("message", "")))
            if path == "/api/dialogs":
                return self.send_json(201, {"dialog": APP.new_dialog(state, actor)})
            return self.send_json(404, {"error": "Не найдено"})
        except PermissionError as exc:
            self.send_json(403, {"error": str(exc)})
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self.send_json(400, {"error": str(exc)})
        except Exception as exc:
            self.send_json(502, {"error": str(exc)})

    def do_PUT(self):
        if not self.same_origin():
            return self.send_json(403, {"error": "Недопустимый источник запроса"})
        try:
            data = self.read_json()
            auth = self.auth()
            if not auth:
                return self.send_json(401, {"error": "Сначала войдите"})
            _, actor = auth
            path = urlparse(self.path).path
            if path == "/api/memory":
                target = actor["id"]
            elif path.startswith("/api/users/") and path.endswith("/memory"):
                target = unquote(path[len("/api/users/"):-len("/memory")].strip("/"))
            else:
                return self.send_json(404, {"error": "Не найдено"})
            user = APP.update_memory(actor, target, data.get("profile", {}))
            self.send_json(200, {"user": user})
        except PermissionError as exc:
            self.send_json(403, {"error": str(exc)})
        except KeyError as exc:
            self.send_json(404, {"error": str(exc)})
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self.send_json(400, {"error": str(exc)})

    def do_DELETE(self):
        if not self.same_origin():
            return self.send_json(403, {"error": "Недопустимый источник запроса"})
        try:
            auth = self.auth()
            if not auth:
                return self.send_json(401, {"error": "Сначала войдите"})
            state, actor = auth
            path = urlparse(self.path).path
            if path.startswith("/api/memory/"):
                target, key = actor["id"], unquote(path.removeprefix("/api/memory/"))
                user = APP.delete_memory(actor, target, key)
                return self.send_json(200, {"user": user})
            if path.startswith("/api/users/") and "/memory/" in path:
                rest = path.removeprefix("/api/users/")
                target, key = map(unquote, rest.split("/memory/", 1))
                user = APP.delete_memory(actor, target, key)
                return self.send_json(200, {"user": user})
            if path.startswith("/api/dialogs/"):
                dialog_id = unquote(path.removeprefix("/api/dialogs/"))
                APP.db.delete_dialog(dialog_id, actor["id"])
                if state.get("dialog_id") == dialog_id:
                    state["dialog_id"] = None
                return self.send_json(200, {"ok": True})
            return self.send_json(404, {"error": "Не найдено"})
        except PermissionError as exc:
            self.send_json(403, {"error": str(exc)})
        except KeyError as exc:
            self.send_json(404, {"error": str(exc)})
        except ValueError as exc:
            self.send_json(400, {"error": str(exc)})


def main():
    port = int(os.getenv("PRO_PORT", "8766"))
    print(f"Lesson 4 Pro: http://127.0.0.1:{port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()

