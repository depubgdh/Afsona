"""Majburiy obuna + kanal/guruhlar boshqaruvi + t.me havoladan kino olish."""
import re
import time

import config
import db
import tgapi

_ME = {}
_CACHE = {}                      # uid -> (vaqt, [yetishmayotgan chatlar])
TTL = 20
MEMBER_OK = {"creator", "administrator", "member"}


async def bot_id() -> int:
    if "id" not in _ME:
        d = await tgapi.call("getMe")
        _ME["id"] = d["result"]["id"]
    return _ME["id"]


def link_of(c) -> str:
    if c["username"]:
        return f"https://t.me/{c['username']}"
    return c["invite"] or ""


async def ensure_link(c) -> str:
    """Yopiq kanal/guruh uchun taklif havolasi (bot admin bo'lsa o'zi yaratadi)."""
    if link_of(c):
        return link_of(c)
    try:
        d = await tgapi.call("exportChatInviteLink", chat_id=c["chat_id"])
        if d.get("ok"):
            db._x("UPDATE chats SET invite=? WHERE chat_id=?", (d["result"], c["chat_id"]))
            return d["result"]
    except Exception:
        pass
    return ""


async def is_member(uid: int, chat_id: int) -> bool:
    try:
        d = await tgapi.call("getChatMember", chat_id=chat_id, user_id=uid)
    except Exception:
        return True                                   # tarmoq xatosi — foydalanuvchini to'smaymiz
    if not d.get("ok"):
        return True                                   # bot chiqarib yuborilgan va h.k. — to'smaymiz
    r = d["result"]
    return r["status"] in MEMBER_OK or (r["status"] == "restricted" and r.get("is_member"))


async def missing(uid: int, fresh=False) -> list:
    """Foydalanuvchi obuna bo'lmagan majburiy chatlar ro'yxati (bo'sh = hammasi joyida)."""
    if uid in config.ADMIN_IDS:
        return []
    req = db.required_chats()
    if not req:
        return []
    hit = _CACHE.get(uid)
    if hit and not fresh and time.time() - hit[0] < TTL and not hit[1]:
        return []
    out = []
    for c in req:
        if not await is_member(uid, c["chat_id"]):
            out.append({"chat_id": c["chat_id"], "title": c["title"], "type": c["type"], "url": await ensure_link(c)})
    _CACHE[uid] = (time.time(), out)
    return out


def sub_keyboard(miss: list, check_cb: str) -> dict:
    rows = [[{"text": c["title"][:40] or "Kanal", "url": c["url"]}] for c in miss if c["url"]]
    rows.append([{"text": "Tekshirish", "callback_data": check_cb}])
    return {"inline_keyboard": rows}


SUB_TEXT = "Botdan foydalanish uchun quyidagi kanal va guruhlarga obuna bo‘ling, so‘ng «Tekshirish» tugmasini bosing."


# ---------------- chatlarni aniqlash ----------------
async def refresh_chat(chat_id) -> dict:
    """getChat + botning shu yerdagi huquqini tekshiradi va bazaga yozadi. Xato bo'lsa DbError."""
    d = await tgapi.call("getChat", chat_id=chat_id)
    if not d.get("ok"):
        raise db.DbError("no_chat", "Bunday kanal/guruh topilmadi yoki bot unda yo‘q")
    ch = d["result"]
    if ch.get("type") not in ("channel", "group", "supergroup"):
        raise db.DbError("bad_chat", "Faqat kanal yoki guruh qo‘shish mumkin")
    mm = await tgapi.call("getChatMember", chat_id=ch["id"], user_id=await bot_id())
    adm = bool(mm.get("ok")) and mm["result"]["status"] in ("administrator", "creator")
    db.chat_upsert(ch["id"], ch.get("title") or ch.get("username") or str(ch["id"]), ch["type"], ch.get("username") or "", adm, ch.get("invite_link") or "")
    return dict(db.chat_get(ch["id"]))


async def add_by_ref(ref: str) -> dict:
    ref = (ref or "").strip()
    m = re.search(r"(?:t\.me/|@)([A-Za-z][\w]{3,})", ref)
    if m:
        target = "@" + m.group(1)
    elif re.match(r"^-?\d{5,}$", ref):
        target = int(ref)
    else:
        raise db.DbError("bad_ref", "@username, havola yoki ID yozing")
    return await refresh_chat(target)


async def refresh_all():
    for c in db.chat_list():
        try:
            await refresh_chat(c["chat_id"])
        except db.DbError:
            db.chat_upsert(c["chat_id"], c["title"], c["type"], c["username"], False)
            db._x("UPDATE chats SET required=0 WHERE chat_id=?", (c["chat_id"],))


# ---------------- t.me havoladan kino olish ----------------
TME_RE = re.compile(r"t\.me/(?:c/(\d+)|([A-Za-z]\w{3,}))/(\d+)", re.I)


def parse_tme(url: str):
    m = TME_RE.search(url or "")
    if not m:
        return None
    chat = int("-100" + m.group(1)) if m.group(1) else "@" + m.group(2)
    return chat, int(m.group(3))


async def import_from_link(url: str, admin_id: int) -> dict:
    """Havoladagi postni adminning o'ziga forward qiladi, file_id ni oladi va nusxani o'chiradi.
    Qaytaradi: {file_id, file_unique_id, file_kind, file_size, duration, title}."""
    p = parse_tme(url)
    if not p:
        raise db.DbError("bad_link", "Havola t.me/kanal/123 yoki t.me/c/123456/78 ko‘rinishida bo‘lsin")
    chat, mid = p
    d = await tgapi.call("forwardMessage", chat_id=admin_id, from_chat_id=chat, message_id=mid)
    if not d.get("ok"):
        raise db.DbError("fwd", "Postni olib bo‘lmadi. Bot o‘sha kanal/guruhda a’zo (admin) bo‘lishi va kontent himoyalanmagan bo‘lishi kerak.")
    r = d["result"]
    try:
        await tgapi.call("deleteMessage", chat_id=admin_id, message_id=r["message_id"])
    except Exception:
        pass
    f, kind = (r.get("video"), "video") if r.get("video") else (r.get("document"), "document") if r.get("document") else (r.get("animation"), "document")
    if not f or (kind == "document" and not (f.get("mime_type") or "").startswith("video/")):
        raise db.DbError("no_video", "Bu postda video topilmadi")
    title = (r.get("caption") or "").strip().split("\n")[0][:80] or f.get("file_name", "") or ""
    return {"file_id": f["file_id"], "file_unique_id": f.get("file_unique_id", ""), "file_kind": kind,
            "file_size": f.get("file_size", 0) or 0, "duration": f.get("duration", 0) or 0, "title": title}
