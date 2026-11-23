"""aiohttp veb-server: Mini App (index.html), /api, /media, /stream (kinoni Mini App ichida ko'rsatish)."""
import os
import pathlib
import re

from aiohttp import ClientSession, ClientTimeout, web

import api
import config
import db
import tgapi

ROOT = pathlib.Path(__file__).parent
NO_STORE = {"Cache-Control": "no-store"}
MEDIA_RE = re.compile(r"^(poster_\d+|ad_main|ad_forced|ad_m\d+)$")
_FP = {}            # kino id -> (Telegram file_path, muddat)


async def index(request):
    return web.Response(text=(ROOT / "index.html").read_text(encoding="utf-8"), content_type="text/html", headers=NO_STORE)


async def media(request):
    """Poster va reklama fayllari. ?v=<versiya> bilan keshlanadi. Video uchun Range (iOS talab qiladi)."""
    key = request.match_info["key"]
    row = db.media_get(key) if MEDIA_RE.match(key) else None
    if not row:
        return web.Response(status=404)
    data = bytes(row["data"])
    hdr = {"Cache-Control": "public, max-age=31536000, immutable", "Accept-Ranges": "bytes"}
    m = re.match(r"bytes=(\d*)-(\d*)$", request.headers.get("Range", "").strip())
    if m and (m.group(1) or m.group(2)):
        n = len(data)
        lo, hi = (int(m.group(1)), int(m.group(2)) if m.group(2) else n - 1) if m.group(1) else (max(0, n - int(m.group(2))), n - 1)
        hi = min(hi, n - 1)
        if lo > hi or lo >= n:
            return web.Response(status=416, headers={"Content-Range": f"bytes */{n}"})
        hdr["Content-Range"] = f"bytes {lo}-{hi}/{n}"
        return web.Response(status=206, body=data[lo:hi + 1], content_type=row["mime"], headers=hdr)
    return web.Response(body=data, content_type=row["mime"], headers=hdr)


async def _file_path(m):
    import time
    c = _FP.get(m["id"])
    if c and c[1] > time.time():
        return c[0]
    d = await tgapi.call("getFile", file_id=m["file_id"])
    if not d.get("ok"):
        return None                                  # masalan, "file is too big" (20 MB dan katta, o'z Bot API serveri yo'q)
    _FP[m["id"]] = (d["result"]["file_path"], time.time() + 1800)
    return d["result"]["file_path"]


async def stream(request):
    """Kinoni Mini App pleyeriga uzatadi (Range qo'llanadi). Imzolangan havola: kim ko'rayotgani va muddati tekshiriladi."""
    q = request.query
    try:
        mid, uid, exp = int(request.match_info["id"]), int(q.get("u", 0)), int(q.get("e", 0))
    except ValueError:
        return web.Response(status=400)
    if not api.stream_ok(uid, mid, exp, q.get("s", "")):
        return web.Response(status=403)
    m = db.movie_get(mid)
    if not m or not m["active"]:
        return web.Response(status=404)
    if m["stream_url"]:
        raise web.HTTPFound(m["stream_url"])
    path = await _file_path(m)
    if not path:
        return web.Response(status=404)
    if path.startswith("/") and os.path.exists(path):          # o'z Bot API serveri: fayl diskda, FileResponse Range'ni o'zi biladi
        return web.FileResponse(path, headers={"Content-Type": "video/mp4"})
    base = (config.BOT_API_URL or "https://api.telegram.org") + f"/file/bot{config.BOT_TOKEN}/{path}"
    h = {"Range": request.headers["Range"]} if "Range" in request.headers else {}
    async with ClientSession(timeout=ClientTimeout(total=None, sock_read=60)) as s:
        async with s.get(base, headers=h) as r:
            resp = web.StreamResponse(status=r.status, headers={"Content-Type": "video/mp4", "Accept-Ranges": "bytes", "Cache-Control": "private, max-age=3600"})
            for k in ("Content-Length", "Content-Range"):
                if k in r.headers:
                    resp.headers[k] = r.headers[k]
            await resp.prepare(request)
            async for chunk in r.content.iter_chunked(65536):
                await resp.write(chunk)
            return resp


async def handle_api(request):
    path = request.match_info["path"]
    try:
        body = await request.json()
        if not isinstance(body, dict):
            body = {}
    except Exception:
        body = {}
    try:
        return web.json_response(await api.dispatch(path, body), headers=NO_STORE)
    except api.ApiError as e:
        return web.json_response({"error": e.code, "message": e.msg}, status=e.status, headers=NO_STORE)
    except Exception:
        import logging
        logging.exception("api xatosi: %s", path)
        return web.json_response({"error": "server", "message": "Server xatosi"}, status=500, headers=NO_STORE)


def make_app():
    app = web.Application(client_max_size=1024 * 1024 * 12)
    app.router.add_get("/", index)
    app.router.add_get("/health", lambda r: web.Response(text="ok"))
    app.router.add_get("/media/{key}", media)
    app.router.add_get("/stream/{id}", stream)
    app.router.add_post("/api/{path:.*}", handle_api)
    return app
