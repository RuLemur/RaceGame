"""HTTP-сервер панели мониторинга (только stdlib).

Раздаёт статику из car_racer/dashboard/web/ и два JSON-эндпоинта:

- GET  /api/stats    -> {"current": {...}, "history": [...]}
- POST /api/command  -> тело {"action": "...", "value": ...}; кладёт команду
                        в очередь (см. car_racer/dashboard/__init__.py).

Сервер привязывается к 127.0.0.1 (не наружу) и живёт в daemon-потоке, поэтому
не мешает тренировке и завершается вместе с процессом.
"""
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, unquote

import car_racer.dashboard as dashboard

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
WEB_DIR_NORM = os.path.normpath(WEB_DIR)

MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}


class DashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # Каждый полл /api/stats пишет в stderr - гасим шум.
        pass

    def _send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/stats":
            self._send_json(dashboard.snapshot())
            return
        self._serve_static(path)

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/command":
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                data = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                data = {}
            if not isinstance(data, dict):
                data = {}
            dashboard.post_command(data)
            self._send_json({"ok": True})
            return
        self._send_json({"error": "not found"}, status=404)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _serve_static(self, path):
        if path in ("/", ""):
            path = "/index.html"
        rel = unquote(path.lstrip("/"))
        full = os.path.normpath(os.path.join(WEB_DIR, rel))
        if not full.startswith(WEB_DIR_NORM + os.sep) or not os.path.isfile(full):
            self._send_json({"error": "not found"}, status=404)
            return
        try:
            with open(full, "rb") as f:
                body = f.read()
        except OSError:
            self._send_json({"error": "not found"}, status=404)
            return
        ext = os.path.splitext(full)[1].lower()
        ctype = MIME.get(ext, "application/octet-stream")
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def start(port=8080):
    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", port), DashboardHandler)
    except OSError as e:
        print(f"[dashboard] не удалось запустить сервер на порту {port}: {e}")
        return
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    print(f"[dashboard] панель: http://127.0.0.1:{port}/")
