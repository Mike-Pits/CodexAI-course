"""Run from repository root: python3 -m lite.server."""
import json
import os
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
from lite.core import ROOT, ModelClient, read_json, recruit, sell

client = ModelClient()
class Handler(BaseHTTPRequestHandler):
    def send(self, code, payload, content_type="application/json; charset=utf-8"):
        body = json.dumps(payload, ensure_ascii=False).encode() if isinstance(payload, (dict, list)) else payload
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/config":
            return self.send(200, {"ready": bool(client.key and os.getenv("WORKER_MODEL")),
                "model": os.getenv("WORKER_MODEL", "не задана"),
                "vacancy": (ROOT / "data/vacancy.txt").read_text(),
                "examples": read_json(ROOT / "data/lite_cases.json"), "product": read_json(ROOT / "data/product.json")})
        files = {"/": ("index.html", "text/html; charset=utf-8"), "/app.js": ("app.js", "text/javascript; charset=utf-8"), "/style.css": ("style.css", "text/css; charset=utf-8")}
        if path not in files:
            return self.send(404, {"error": "Не найдено"})
        file, mime = files[path]
        self.send(200, (ROOT / "static" / file).read_bytes(), mime)

    def do_POST(self):
        try:
            origin = self.headers.get("Origin")
            if origin and origin != "http://" + self.headers.get("Host", ""):
                return self.send(403, {"error": "Недопустимый источник запроса"})
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                return self.send(415, {"error": "Требуется JSON"})
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 100000:
                return self.send(413, {"error": "Допустимо до 100 КБ"})
            data = json.loads(self.rfile.read(length))
            if self.path == "/api/recruit":
                for field in ("vacancy", "resume"):
                    if not isinstance(data.get(field), str) or not data[field].strip():
                        raise ValueError("Заполните вакансию и резюме")
                result = recruit(client, os.getenv("WORKER_MODEL"), data["vacancy"], data["resume"])
            elif self.path == "/api/sales":
                history = data.get("history")
                if not isinstance(history, list) or not 1 <= len(history) <= 41:
                    raise ValueError("Диалог должен содержать от 1 до 41 реплики")
                for i, entry in enumerate(history):
                    if not isinstance(entry, dict) or entry.get("role") != ("user" if i % 2 == 0 else "assistant") or not isinstance(entry.get("content"), str) or not entry["content"].strip():
                        raise ValueError("Некорректная история диалога")
                if history[-1]["role"] != "user":
                    raise ValueError("Последняя реплика должна принадлежать клиенту")
                result = sell(client, os.getenv("WORKER_MODEL"), history)
            else:
                return self.send(404, {"error": "Не найдено"})
            self.send(200, result)
        except (ValueError, TypeError, KeyError) as exc:
            self.send(400, {"error": str(exc)})
        except Exception as exc:
            self.send(502, {"error": str(exc)})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8765"))
    print(f"Lite: http://127.0.0.1:{port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
