"""API yo'llari. Hammasi POST /api/<yo'l>, tanasida {init_data, ...}. Admin yo'llari faqat ADMIN_IDS uchun."""
import asyncio
import base64
import hashlib
import hmac
import re
import time

import auth
import config
import db
import deliver
import backup
import subs
import tgapi

ROUTES = {}
ADMIN_ROUTES = set()
SUB_FREE = {"me", "sub/status", "sub/check"}          # obunasiz ham ishlaydigan yo'llar
TG_FILE_LIMIT = 20 * 1024 * 1024          # oddiy Bot API faqat shu hajmgacha fayl berib turadi


class ApiError(Exception):
    def __init__(self, status: int, code: str, msg: str = "", extra: dict = None):
        super().__init__(code)
        self.status, self.code, self.msg, self.extra = status, code, msg or code, extra or {}


def route(path, admin=False):
    def deco(fn):
        ROUTES[path] = fn
        if admin:
            ADMIN_ROUTES.add(path)
        return fn
    return deco


def _i(v, d=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return d


async def dispatch(path: str, body: dict, dev_user: dict = None):
    fn = ROUTES.get(path)
    if not fn:
        raise ApiError(404, "not_found", "Yo‘l topilmadi")
    if dev_user:
        tg_user = dev_user
    else:
        a = auth.verify(body.get("init_data", ""))
        if not a:
            raise ApiError(401, "auth", "Telegram orqali oching")
        tg_user = a["user"]
    uid = int(tg_user["id"])
    user = db.ensure_user(uid, tg_user.get("username") or "", tg_user.get("first_name") or "", tg_user.get("photo_url") or "")
    if user["banned"]:
        raise ApiError(403, "banned", "Hisobingiz bloklangan")
    is_admin = uid in config.ADMIN_IDS
    if path in ADMIN_ROUTES and not is_admin:
        raise ApiError(403, "forbidden", "Faqat admin uchun")
    ctx = {"uid": uid, "user": user, "is_admin": is_admin}
    if path not in SUB_FREE and not is_admin:
        miss = await subs.missing(uid)
        if miss:
            raise ApiError(403, "subscribe", "Avval kanallarga obuna bo‘ling", {"missing": miss})
    try:
        return await fn(ctx, body)
    except db.DbError as e:
        raise ApiError(400, e.code, e.msg)


# ---------------- yordamchilar ----------------
def _sniff(b: bytes, allow_video=False):
    if b[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if b[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if b[:4] == b"GIF8":
        return "image/gif"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return "image/webp"
    if allow_video and b[4:8] == b"ftyp":
        return "video/mp4"
    return None


def _decode(d: dict, key="data", allow_video=False):
    raw = d.get(key)
    if not raw:
        return None, None
    try:
        b = base64.b64decode(str(raw), validate=False)
    except Exception:
        raise ApiError(400, "bad_file", "Fayl o‘qilmadi")
    mime = _sniff(b, allow_video)
    if not mime:
        raise ApiError(400, "bad_type", "Faqat JPG, PNG, WEBP, GIF" + (" yoki MP4" if allow_video else "") + " yuklang")
    return b, mime


def _url(u: str, allow_tg=True) -> str:
    u = (u or "").strip()[:500]
    if u and not re.match(r"^(https?://" + ("|tg://" if allow_tg else "") + ")", u, re.I):
        raise ApiError(400, "bad_url", "Havola https:// bilan boshlansin")
    return u


def has_stream(m) -> bool:
    if (m["src"] or "tg") != "tg":
        return True
    return bool(m["stream_url"]) or bool(config.BOT_API_URL) or (0 < (m["file_size"] or 0) <= TG_FILE_LIMIT)


def _sig(uid: int, mid: int, exp: int) -> str:
    return hmac.new(config.BOT_TOKEN.encode() or b"dev", f"{uid}:{mid}:{exp}".encode(), hashlib.sha256).hexdigest()[:32]


def stream_ok(uid: int, mid: int, exp: int, sig: str) -> bool:
    return exp > time.time() and hmac.compare_digest(_sig(uid, mid, exp), sig or "")


def stream_link(uid: int, mid: int) -> str:
    exp = int(time.time()) + 8 * 3600
    return f"/stream/{mid}?u={uid}&e={exp}&s={_sig(uid, mid, exp)}"


def card(m) -> dict:
    return db.movie_public(m)


def _ad(key: str) -> dict:
    meta = db.media_meta(key)
    return {"ver": meta["ver"], "mime": meta["mime"], "url": db.get_text(key + "_url", ""), "text": db.get_text(key + "_text", "")}


def public_ads() -> dict:
    return {"main": _ad("ad_main"), "forced": _ad("ad_forced")}


async def notify_admins(text: str, kb=None):
    for a in config.ADMIN_IDS:
        await tgapi.send_message(a, text, parse_mode="HTML", **({"reply_markup": kb} if kb else {}))


def perm_text(p: dict) -> str:
    import html
    e = html.escape
    return (f"📝 <b>Kino joylashga ruxsat so‘rovi</b>\n👤 {e(p['first_name'])} {e(p['last_name'])}\n📅 Tug‘ilgan yili: {p['year']}\n"
            f"📞 {e(p['phone'])}\n✉️ {e(p['email'])}\n🆔 <code>{p['user_id']}</code>" + (f" · @{e(p['username'])}" if p.get("username") else ""))


# ---------------- foydalanuvchi ----------------
@route("me")
async def api_me(c, d):
    uid, u = c["uid"], c["user"]
    st = db.get_settings()
    perm = db.perm_get(uid)
    miss = await subs.missing(uid)
    return {
        "sub": {"required": bool(miss), "missing": miss},
        "user": {"id": uid, "name": u["first_name"], "username": u["username"], "photo": u["photo"], "hist_on": bool(u["hist_on"]), "adult_ok": bool(u["adult_ok"])},
        "is_admin": c["is_admin"], "can_post": db.can_post(uid), "perm": perm["status"] if perm else "",
        "settings": {"forced_every_min": st["forced_every_min"], "forced_skip_sec": st["forced_skip_sec"]},
        "ads": public_ads(), "bot": config.BOT_USERNAME, "qualities": list(db.QUALITIES), "ages": list(db.AGES),
        "emotions": [{"k": k, "e": e} for k, e in db.EMOTIONS.items()], "counts": db.counts(uid),
    }


@route("admin/backup", admin=True)
async def api_a_backup(c, d):
    r = await backup.run_once(force=True)
    if r != "ok":
        raise ApiError(500, "backup", "Zaxira yuborilmadi (" + r + ")")
    return {"ok": True}


@route("sub/status")
async def api_sub_status(c, d):
    miss = await subs.missing(c["uid"])
    return {"required": bool(miss), "missing": miss}


@route("sub/check")
async def api_sub_check(c, d):
    miss = await subs.missing(c["uid"], fresh=True)
    return {"required": bool(miss), "missing": miss}


@route("home")
async def api_home(c, d):
    uid = c["uid"]
    items, total = db.list_movies(0, 20)
    return {"top": [card(m) for m in db.top_movies()], "foryou": [card(m) for m in db.recommend(uid, 10)], "tags": db.popular_tags(),
            "items": [card(m) for m in items], "total": total}


@route("movies")
async def api_movies(c, d):
    items, total = db.list_movies(max(0, _i(d.get("offset"))), 20, str(d.get("tag", "")), "views" if d.get("sort") == "views" else "new")
    return {"items": [card(m) for m in items], "total": total}


@route("search")
async def api_search(c, d):
    return {"items": [card(m) for m in db.search(str(d.get("q", "")), 40)]}


@route("movie")
async def api_movie(c, d):
    m = db.movie_get(_i(d.get("id")) or (db.movie_by_code(_i(d.get("code")))["id"] if db.movie_by_code(_i(d.get("code"))) else 0))
    if not m or (not m["active"] and not c["is_admin"]):
        raise ApiError(404, "none", "Kino topilmadi")
    out = card(m)
    out.update(db.flags(c["uid"], m["id"]))
    out["has_stream"] = has_stream(m)
    out["src"] = m["src"] or "tg"
    ad_media = db.media_get(f"ad_m{m['id']}") if m["ad_ver"] else None
    out["ad"] = {"ver": m["ad_ver"], "url": m["ad_url"], "mime": ad_media["mime"]} if ad_media else None
    out["can_edit"] = c["is_admin"] or m["owner"] == c["uid"]
    return out


@route("movie/like")
async def api_like(c, d):
    mid = _i(d.get("id"))
    on = db.toggle("likes", c["uid"], mid)
    return {"on": on, "likes": db.movie_get(mid)["likes"]}


@route("movie/save")
async def api_save(c, d):
    return {"on": db.toggle("saves", c["uid"], _i(d.get("id")))}


@route("movie/watch")
async def api_watch(c, d):
    """mode='bot' — kinoni botdagi chatga yuboradi; mode='app' — Mini App pleyeri uchun havola beradi."""
    uid, mid = c["uid"], _i(d.get("id"))
    m = db.movie_get(mid)
    if not m or not m["active"]:
        raise ApiError(404, "none", "Kino topilmadi")
    if m["age"] >= 18 and not c["user"]["adult_ok"]:
        raise ApiError(403, "adult", "18 yoshdan oshganingizni tasdiqlang")
    if d.get("mode") == "bot":
        res = await deliver.send_movie(uid, uid, mid)
        if res == "fail":
            raise ApiError(502, "send_fail", "Kinoni yuborib bo‘lmadi. Avval botga /start yozing.")
        return {"sent": True}
    if (m["src"] or "tg") != "tg":                       # YouTube / boshqa sayt
        db.record_view(uid, mid)
        return {"kind": m["src"], "src": m["src_url"], "title": m["title"]}
    if not has_stream(m):
        raise ApiError(409, "no_stream", "Bu kino katta, uni botga yuborib ko‘ring")
    db.record_view(uid, mid)
    return {"kind": "file", "src": stream_link(uid, mid), "title": m["title"]}


@route("user/adult")
async def api_adult(c, d):
    db.set_adult(c["uid"])
    return {"ok": True}


@route("me/history")
async def api_hist(c, d):
    db.set_hist(c["uid"], bool(d.get("on")))
    return {"on": bool(d.get("on"))}


@route("me/history/clear")
async def api_hist_clear(c, d):
    db.clear_history(c["uid"])
    return {"counts": db.counts(c["uid"])}


@route("me/list")
async def api_list(c, d):
    kind = d.get("kind") if d.get("kind") in ("like", "save", "history") else "like"
    return {"items": [card(m) for m in db.my_list(kind, c["uid"])], "counts": db.counts(c["uid"])}


# ---------------- ruxsat va joylash ----------------
@route("perm/request")
async def api_perm_request(c, d):
    p = db.perm_request(c["uid"], d)
    p["username"] = c["user"]["username"]
    kb = {"inline_keyboard": [[{"text": "✅ Ruxsat berish", "callback_data": f"pm:ok:{c['uid']}"}, {"text": "❌ Rad etish", "callback_data": f"pm:no:{c['uid']}"}]]}
    asyncio.ensure_future(notify_admins(perm_text(p), kb))
    return {"perm": "pending"}


@route("upload/list")
async def api_upload_list(c, d):
    if not db.can_post(c["uid"]):
        raise ApiError(403, "forbidden", "Kino joylashga ruxsat yo‘q")
    return {"items": db.uploads_pending(c["uid"]), "next_code": db.next_code()}


def _save_poster(mid: int, d: dict):
    b, mime = _decode(d, "poster")
    if b:
        db.movie_set_media(mid, "poster", db.media_save(f"poster_{mid}", mime, b))


@route("movie/create")
async def api_movie_create(c, d):
    if not db.can_post(c["uid"]):
        raise ApiError(403, "forbidden", "Kino joylashga ruxsat yo‘q")
    thumb = db.upload_thumb(c["uid"], d.get("upload_id")) if d.get("upload_id") else ""
    mid = db.movie_create(c["uid"], d, c["is_admin"])
    _save_poster(mid, d)
    if thumb and not db.movie_get(mid)["poster_ver"]:            # poster berilmagan: videoning o'z rasmini qo'yamiz
        try:
            data, mime = await tgapi.download_file(thumb)
            if data:
                db.movie_set_media(mid, "poster", db.media_save(f"poster_{mid}", mime, data))
        except Exception:
            pass
    m = db.movie_get(mid)
    return {"id": mid, "code": m["code"]}


@route("movie/update")
async def api_movie_update(c, d):
    mid = _i(d.get("id"))
    db.movie_update(mid, c["uid"], d, c["is_admin"])
    _save_poster(mid, d)
    return {"ok": True}


@route("movie/delete")
async def api_movie_delete(c, d):
    db.movie_delete(_i(d.get("id")), c["uid"], c["is_admin"])
    return {"ok": True}


@route("movie/mine")
async def api_movie_mine(c, d):
    rows = db._q("SELECT * FROM movies WHERE owner=? ORDER BY id DESC LIMIT 100", (c["uid"],))
    return {"items": [card(m) for m in rows]}


@route("movie/edit")
async def api_movie_edit(c, d):
    """Tahrirlash formasi uchun to'liq ma'lumot (egasi yoki admin)."""
    m = db.movie_get(_i(d.get("id")))
    if not m or (m["owner"] != c["uid"] and not c["is_admin"]):
        raise ApiError(403, "forbidden", "Ruxsat yo‘q")
    out = card(m)
    out.update({"aliases": m["aliases"].replace(",", ", "), "stream_url": m["stream_url"], "src_url": ("" if (m["src"] or "tg") == "tg" else (f"https://youtu.be/{m['src_url']}" if m["src"] == "yt" else m["src_url"])), "ad_url": m["ad_url"], "ad_ver": m["ad_ver"], "top_pos": m["top_pos"]})
    return out


# ---------------- admin ----------------
@route("admin/stats", admin=True)
async def api_a_stats(c, d):
    return db.stats()


@route("admin/movies", admin=True)
async def api_a_movies(c, d):
    q = str(d.get("q", "")).strip()
    if q:
        rows = db.search(q, 60, include_inactive=True)
    else:
        rows = db._q("SELECT * FROM movies ORDER BY id DESC LIMIT 60")
    top = db._q("SELECT * FROM movies WHERE top_pos>0 ORDER BY top_pos ASC")
    return {"items": [dict(card(m), top_pos=m["top_pos"]) for m in rows], "top": [card(m) for m in top],
            "total": db._q("SELECT COUNT(*) c FROM movies", one=True)["c"], "top_mode": db.get_settings()["top_mode"]}


@route("admin/movie/ad", admin=True)
async def api_a_movie_ad(c, d):
    mid = _i(d.get("id"))
    m = db.movie_get(mid)
    if not m:
        raise ApiError(404, "none", "Kino topilmadi")
    b, mime = _decode(d, "data", allow_video=True)
    if b:
        db.movie_set_media(mid, "ad", db.media_save(f"ad_m{mid}", mime, b))
    elif d.get("remove"):
        db.media_delete(f"ad_m{mid}")
        db.movie_set_media(mid, "ad", 0)
    db._x("UPDATE movies SET ad_url=? WHERE id=?", (_url(d.get("url", "")), mid))
    return {"ok": True}


@route("admin/top", admin=True)
async def api_a_top(c, d):
    """Top ro'yxatni qo'lda belgilash: {ids: [kino id lari tartib bilan]}."""
    ids = [_i(x) for x in (d.get("ids") or []) if _i(x)]
    db._x("UPDATE movies SET top_pos=0")
    for pos, mid in enumerate(ids[:50], 1):
        db._x("UPDATE movies SET top_pos=? WHERE id=?", (pos, mid))
    return {"ok": True}


@route("admin/perms", admin=True)
async def api_a_perms(c, d):
    return {"pending": db.perm_list("pending"), "approved": db.perm_list("approved"), "rejected": db.perm_list("rejected")}


async def resolve_perm(uid: int, ok: bool):
    db.perm_decide(uid, ok)
    await tgapi.send_message(uid, "✅ Kino joylashga ruxsat berildi! Mini App → «Kino joylash» bo‘limiga o‘ting." if ok else "❌ Afsus, kino joylashga ruxsat berilmadi.")


@route("admin/perm/decide", admin=True)
async def api_a_perm_decide(c, d):
    await resolve_perm(_i(d.get("user_id")), bool(d.get("ok")))
    return await api_a_perms(c, d)


@route("admin/perm/revoke", admin=True)
async def api_a_perm_revoke(c, d):
    db._x("UPDATE perms SET status='rejected', decided=? WHERE user_id=?", (db.now(), _i(d.get("user_id"))))
    return await api_a_perms(c, d)


@route("admin/ads", admin=True)
async def api_a_ads(c, d):
    return public_ads()


@route("admin/ad/save", admin=True)
async def api_a_ad_save(c, d):
    key = d.get("key")
    if key not in db.AD_KEYS:
        raise ApiError(400, "bad_key", "Noto‘g‘ri reklama")
    b, mime = _decode(d, "data", allow_video=True)
    if b:
        db.media_save(key, mime, b)
    elif not db.media_get(key):
        raise ApiError(400, "no_file", "Avval rasm, GIF yoki video tanlang")
    db.set_text(key + "_url", _url(d.get("url", "")))
    db.set_text(key + "_text", str(d.get("text", "")).strip()[:40])
    db.set_text(f"fid_{key}", "")
    return public_ads()


@route("admin/ad/delete", admin=True)
async def api_a_ad_del(c, d):
    key = d.get("key")
    if key not in db.AD_KEYS:
        raise ApiError(400, "bad_key", "Noto‘g‘ri reklama")
    db.media_delete(key)
    db.set_text(key + "_url", "")
    return public_ads()


@route("admin/settings", admin=True)
async def api_a_settings(c, d):
    return {"settings": db.get_settings()}


@route("admin/settings/save", admin=True)
async def api_a_settings_save(c, d):
    return {"settings": db.set_settings(d.get("values") or {})}


@route("admin/broadcast", admin=True)
async def api_a_broadcast(c, d):
    text = str(d.get("text", "")).strip()[:3500]
    if not text:
        raise ApiError(400, "empty", "Matn yozing")
    ids = db.all_user_ids()
    asyncio.ensure_future(tgapi.broadcast(ids, text))
    return {"queued": len(ids)}


# ---------------- admin: majburiy obuna kanallari ----------------
def _chats():
    return {"items": db.chat_list(), "max": db.MAX_REQUIRED, "required": len(db.required_chats()), "bot": config.BOT_USERNAME}


@route("admin/chats", admin=True)
async def api_a_chats(c, d):
    return _chats()


@route("admin/chat/refresh", admin=True)
async def api_a_chat_refresh(c, d):
    await subs.refresh_all()
    return _chats()


@route("admin/chat/add", admin=True)
async def api_a_chat_add(c, d):
    await subs.add_by_ref(str(d.get("ref", "")))
    return _chats()


@route("admin/chat/required", admin=True)
async def api_a_chat_required(c, d):
    db.chat_set_required(_i(d.get("chat_id")), bool(d.get("on")))
    subs._CACHE.clear()
    return _chats()


@route("admin/chat/remove", admin=True)
async def api_a_chat_remove(c, d):
    db.chat_remove(_i(d.get("chat_id")))
    subs._CACHE.clear()
    return _chats()


@route("upload/link", admin=True)
async def api_upload_link(c, d):
    """Admin guruh/kanaldagi post havolasini tashlaydi — bot videoni olib, ro'yxatga qo'shadi."""
    r = await subs.import_from_link(str(d.get("url", "")), c["uid"])
    uid = db.upload_add(c["uid"], r["file_kind"], r["file_id"], r["file_unique_id"], r["file_size"], r["duration"], r["title"], r.get("thumb", ""))
    return {"upload_id": uid, "title": r["title"], "size": r["file_size"]}
