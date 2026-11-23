"""Mahalliy sinov serveri (Telegramsiz): python dev_server.py  →  http://localhost:8771/?dev=1
Foydalanuvchi: sarlavha X-Dev-User (standart 7 — admin). /dev/upload — «botga video yuborildi» ni taqlid qiladi."""
import asyncio
import json
import os
import pathlib
import sys
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

os.environ.setdefault("DB_PATH", tempfile.mkdtemp() + "/dev.sqlite3")
os.environ.setdefault("ADMIN_IDS", "7")
os.environ.setdefault("BOT_USERNAME", "kino_demo_bot")
import api, config, db, tgapi  # noqa: E402

SENT = []


async def fake_call(method, **kw):
    SENT.append((method, kw.get("chat_id"), (kw.get("caption") or kw.get("text") or "")[:80]))
    return {"ok": True, "result": {}}


async def fake_upload(method, field, filename, data, mime, **kw):
    SENT.append((method, kw.get("chat_id"), "upload " + filename))
    return {"ok": True, "result": {}}

tgapi.call, tgapi.upload = fake_call, fake_upload
db.init_db()
ROOT = pathlib.Path(__file__).parent


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _send(self, code, body, ctype="application/json"):
        b = body if isinstance(body, bytes) else body.encode()
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        if self.path.startswith("/sent"):
            return self._send(200, json.dumps(SENT))
        if (self.path.startswith("/vid") or self.path.startswith("/stream/")) and os.environ.get("DEV_VIDEO"):
            return self._send(200, pathlib.Path(os.environ["DEV_VIDEO"]).read_bytes(), "video/webm")
        if self.path.startswith("/media/"):
            row = db.media_get(self.path[7:].split("?")[0])
            return self._send(200, bytes(row["data"]), row["mime"]) if row else self._send(404, b"")
        self._send(200, (ROOT / "index.html").read_text(encoding="utf-8"), "text/html; charset=utf-8")

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0)); body = json.loads(self.rfile.read(n) or b"{}")
        uid = int(self.headers.get("X-Dev-User", os.environ.get("DEV_UID", "7")))
        user = {"id": uid, "first_name": "Test" if uid == 7 else f"User{uid}", "username": "testuser" if uid == 7 else f"user{uid}"}
        if self.path == "/dev/upload":
            db.ensure_user(uid, user["username"], user["first_name"], "")
            i = db.upload_add(uid, "video", "FILEID" + str(os.urandom(3).hex()), os.urandom(4).hex(), body.get("size", 900_000_000), 5400, body.get("name", "film.mp4"))
            return self._send(200, json.dumps({"id": i}))
        try:
            self._send(200, json.dumps(asyncio.run(api.dispatch(self.path[5:], body, dev_user=user))))
        except api.ApiError as e:
            self._send(e.status, json.dumps({"error": e.code, "message": e.msg}))


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8771
    print("dev server", port, "DB", config.DB_PATH)
    ThreadingHTTPServer(("0.0.0.0", port), H).serve_forever()
