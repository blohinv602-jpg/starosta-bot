import json
import logging
import mimetypes
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import api
import auth
import config

log = logging.getLogger("http")

MAX_BODY = 25 * 1024 * 1024


class Handler(BaseHTTPRequestHandler):
    server_version = "StarostaBot/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        log.info("%s - %s", self.address_string(), fmt % args)

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_PATCH(self):
        self._handle("PATCH")

    def do_DELETE(self):
        self._handle("DELETE")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Init-Data")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")

    def _json(self, status: int, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _bytes(self, status: int, body: bytes, content_type: str, filename: str | None = None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if filename:
            quoted = urllib.parse.quote(filename)
            self.send_header(
                "Content-Disposition", f"attachment; filename*=UTF-8''{quoted}"
            )
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> bytes:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length > MAX_BODY:
            raise api.ApiError("Слишком большой запрос", 413)
        return self.rfile.read(length) if length else b""

    def _handle(self, method: str):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = {k: v[-1] for k, v in urllib.parse.parse_qs(parsed.query).items()}

        if path in ("/health", "/api/health"):
            return self._json(200, {"ok": True, "demo": config.DEV_MODE})

        if path.startswith("/api/"):
            return self._handle_api(method, path, query)

        return self._handle_static(path)

    def _handle_api(self, method: str, path: str, query: dict):
        try:
            init_data = self.headers.get("X-Init-Data") or ""
            tg_user = auth.parse(init_data)
            raw = self._read_body() if method in ("POST", "PATCH", "DELETE") else b""
            body = api.parse_body(raw)

            if path == "/api/report.xlsx" and method == "GET":
                ctx = api.Ctx(tg_user)
                group = ctx.require_group()
                content, filename = api.build_report(group, query.get("period") or "month")
                return self._bytes(
                    200,
                    content,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    filename,
                )

            if path == "/api/materials/file" and method == "GET":
                ctx = api.Ctx(tg_user)
                group = ctx.require_group()
                item_id = int(query.get("id") or 0)
                row = api.db.q1(
                    "SELECT * FROM materials WHERE id = ? AND group_id = ?",
                    (item_id, group["id"]),
                )
                if not row:
                    raise api.ApiError("Материал не найден", 404)
                data = api.pathlib.Path(row["file_path"]).read_bytes()
                return self._bytes(
                    200, data, "application/octet-stream", f"{row['title']}"
                )

            ctx = api.Ctx(tg_user)
            result = api.route(ctx, method, path, query, body, raw)
            return self._json(200, {"ok": True, "data": result})
        except api.ApiError as exc:
            return self._json(exc.status, {"ok": False, "error": exc.message})
        except auth.AuthError as exc:
            return self._json(401, {"ok": False, "error": f"auth: {exc}"})
        except Exception as exc:
            log.exception("api failure %s %s", method, path)
            return self._json(500, {"ok": False, "error": f"Внутренняя ошибка: {exc}"})

    def _handle_static(self, path: str):
        if path == "/":
            file_path = config.WEB_DIR / "index.html"
        else:
            relative = path.lstrip("/")
            file_path = (config.WEB_DIR / relative).resolve()
            if not str(file_path).startswith(str(config.WEB_DIR.resolve())):
                return self._json(403, {"ok": False, "error": "forbidden"})
        if not file_path.is_file():
            return self._json(404, {"ok": False, "error": "not found"})
        guessed = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
        if guessed.startswith("text/") or guessed in (
            "application/javascript",
            "application/json",
        ):
            guessed = f"{guessed}; charset=utf-8"
        body = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", guessed)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)


def serve():
    server = ThreadingHTTPServer((config.HOST, config.PORT), Handler)
    server.daemon_threads = True
    log.info("listening on http://%s:%s", config.HOST, config.PORT)
    return server
