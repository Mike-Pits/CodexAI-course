"""Local web server for the Lesson 4 Lite assignment."""

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
from app.store import JsonStore


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"


def load_environment() -> None:
    path = ROOT / ".env"
    if not path.exists():
        return
    allowed = {"MODEL_API_KEY", "OPENAI_API_KEY", "API_BASE_URL", "WORKER_MODEL", "PORT", "DATA_PATH", "PRO_PORT", "PRO_DB_PATH"}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and key in allowed:
            os.environ.setdefault(key, value.strip().strip("\"'"))


class Application:
    def __init__(self, data_path: str | Path | None = None):
        self.store = JsonStore(data_path or os.getenv("DATA_PATH", ROOT / "data" / "store.json"))
        self.sessions: dict[str, dict] = {}
        self.lock = RLock()

    def login(self, username: str, password: str) -> tuple[str, dict] | None:
        user = self.store.authenticate(username, password)
        if not user:
            return None
        token = secrets.token_urlsafe(32)
        with self.lock:
            self.sessions[token] = {"user_id": user["id"], "history": []}
        return token, user

    def session(self, token: str | None) -> tuple[dict, dict] | None:
        with self.lock:
            state = self.sessions.get(token or "")
        if not state:
            return None
        user = self.store.get_user(state["user_id"])
        return (state, user) if user else None

    def logout(self, token: str | None) -> None:
        with self.lock:
            self.sessions.pop(token or "", None)

    def list_users(self, actor: dict) -> list[dict]:
        if actor["role"] != "admin":
            raise PermissionError("Требуются права администратора")
        return self.store.list_users()

    def update_profile(self, actor: dict, target_id: str, values: dict[str, str]) -> dict:
        if actor["role"] != "admin" and actor["id"] != target_id:
            raise PermissionError("Нельзя изменять данные другого пользователя")
        return self.store.update_profile(target_id, values)

    def chat(self, state: dict, user: dict, message: str) -> dict:
        if user["role"] != "client":
            raise PermissionError("Чат доступен только клиенту")
        message = " ".join(message.split())
        if not message or len(message) > 2000:
            raise ValueError("Сообщение должно содержать от 1 до 2000 символов")
        facts = extract_facts(message)
        if facts:
            user = self.store.update_profile(user["id"], facts)
        with self.lock:
            history = state["history"]
            history.append({"role": "user", "content": message})
            reply = model_reply(user["profile"], list(history))
            history.append({"role": "assistant", "content": reply})
            if len(history) > 42:
                del history[:-42]
        return {"message": reply, "saved": facts, "profile": user["profile"], "history": list(history)}


load_environment()
APP = Application()


class Handler(BaseHTTPRequestHandler):
    server_version = "PracticeLite/1.0"

    def log_message(self, format: str, *args) -> None:
        print(f"{self.address_string()} - {format % args}")

    def send_json(self, code: int, value: dict | list, headers: dict[str, str] | None = None) -> None:
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

    def send_file(self, path: Path, mime: str) -> None:
        if not path.exists():
            return self.send_json(404, {"error": "Не найдено"})
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def token(self) -> str | None:
        jar = cookies.SimpleCookie(self.headers.get("Cookie", ""))
        return jar["session"].value if "session" in jar else None

    def auth(self) -> tuple[dict, dict] | None:
        return APP.session(self.token())

    def read_json(self) -> dict:
        if self.headers.get("Content-Type", "").split(";", 1)[0] != "application/json":
            raise ValueError("Требуется JSON")
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 < length <= 100_000:
            raise ValueError("Недопустимый размер запроса")
        value = json.loads(self.rfile.read(length))
        if not isinstance(value, dict):
            raise ValueError("Ожидался JSON-объект")
        return value

    def same_origin(self) -> bool:
        origin = self.headers.get("Origin")
        return not origin or origin == "http://" + self.headers.get("Host", "")

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/config":
            return self.send_json(200, {"product": PRODUCT, "model": os.getenv("WORKER_MODEL") or "локальный демо-режим"})
        if path == "/api/me":
            auth = self.auth()
            return self.send_json(200, {"user": auth[1] if auth else None})
        if path == "/api/profile":
            auth = self.auth()
            if not auth:
                return self.send_json(401, {"error": "Сначала войдите"})
            return self.send_json(200, {"user": auth[1]})
        if path == "/api/users":
            auth = self.auth()
            if not auth:
                return self.send_json(401, {"error": "Сначала войдите"})
            try:
                return self.send_json(200, {"users": APP.list_users(auth[1])})
            except PermissionError as exc:
                return self.send_json(403, {"error": str(exc)})
        files = {
            "/": ("index.html", "text/html; charset=utf-8"),
            "/app.js": ("app.js", "text/javascript; charset=utf-8"),
            "/style.css": ("style.css", "text/css; charset=utf-8"),
        }
        if path in files:
            filename, mime = files[path]
            return self.send_file(STATIC / filename, mime)
        self.send_json(404, {"error": "Не найдено"})

    def do_POST(self) -> None:
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
                return self.send_json(200, {"user": user}, {"Set-Cookie": f"session={token}; HttpOnly; SameSite=Strict; Path=/"})
            if path == "/api/logout":
                APP.logout(self.token())
                return self.send_json(200, {"ok": True}, {"Set-Cookie": "session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"})
            auth = self.auth()
            if not auth:
                return self.send_json(401, {"error": "Сначала войдите"})
            state, user = auth
            if path == "/api/chat":
                return self.send_json(200, APP.chat(state, user, data.get("message", "")))
            if path == "/api/new-dialog":
                with APP.lock:
                    state["history"] = []
                return self.send_json(200, {"ok": True})
            return self.send_json(404, {"error": "Не найдено"})
        except PermissionError as exc:
            self.send_json(403, {"error": str(exc)})
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self.send_json(400, {"error": str(exc)})
        except Exception as exc:
            self.send_json(502, {"error": str(exc)})

    def do_PUT(self) -> None:
        if not self.same_origin():
            return self.send_json(403, {"error": "Недопустимый источник запроса"})
        try:
            data = self.read_json()
            auth = self.auth()
            if not auth:
                return self.send_json(401, {"error": "Сначала войдите"})
            _, actor = auth
            path = urlparse(self.path).path
            if path == "/api/profile":
                target = actor["id"]
            elif path.startswith("/api/users/"):
                target = unquote(path.removeprefix("/api/users/"))
            else:
                return self.send_json(404, {"error": "Не найдено"})
            updated = APP.update_profile(actor, target, data.get("profile", {}))
            self.send_json(200, {"user": updated})
        except PermissionError as exc:
            self.send_json(403, {"error": str(exc)})
        except KeyError as exc:
            self.send_json(404, {"error": str(exc)})
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self.send_json(400, {"error": str(exc)})


def main() -> None:
    port = int(os.getenv("PORT", "8765"))
    print(f"Lesson 4 Lite: http://127.0.0.1:{port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
