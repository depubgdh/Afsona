"""Kinoni Telegram chatiga yuborish (bot ham, Mini App ham shu yerdan foydalanadi)."""
import html

import config
import db
import tgapi

MIME_EXT = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif", "video/mp4": "mp4"}


def caption(m) -> str:
    tags = " ".join("#" + t for t in db.unpack(m["tags"]))
    emos = " · ".join(f"{db.EMOTIONS.get(t, '🏷')} {t.capitalize()}" for t in db.unpack(m["emotions"]))
    meta = " · ".join(x for x in (f"📺 {m['quality']}" if m["quality"] else "", f"🗣 {html.escape(m['lang'])}" if m["lang"] else "",
                                  f"🔞 {m['age']}+" if m["age"] else "") if x)
    head = f"🎬 <b>{html.escape(m['title'])}</b>" + (f" ({m['year']})" if m["year"] else "")
    parts = [head, f"🆔 Kod: <code>{m['code']}</code>", tags, emos, meta]
    text = "\n".join(p for p in parts if p)
    if m["descr"]:
        room = 1000 - len(text) - 20
        if room > 60:
            d = m["descr"].strip()
            text += "\n\n" + html.escape(d[:room] + ("…" if len(d) > room else ""))
    return text[:1024]


def keyboard(m) -> dict:
    rows = []
    if config.WEBAPP_URL:                                # 1-qator: Mini App'da ko'rish
        rows.append([{"text": "🎬 Mini App’da ko‘rish", "web_app": {"url": f"{config.WEBAPP_URL}?movie={m['id']}"}}])
    rows.append([{"text": "❤️ Yoqdi", "callback_data": f"lk:{m['id']}"}, {"text": "🔖 Saqlash", "callback_data": f"sv:{m['id']}"}])
    url = m["ad_url"] or db.get_text("ad_main_url", "")
    if url and (m["ad_ver"] or db.media_get("ad_main")):
        rows.append([{"text": db.get_text("ad_main_text", "") or "📢 Reklama", "url": url}])
    return {"inline_keyboard": rows}


async def send_ad(chat_id: int, key: str = "ad_forced") -> bool:
    """Majburiy reklama: rasm / GIF / video + tagida havola tugmasi."""
    med = db.media_get(key)
    if not med:
        return False
    url, text = db.get_text(key + "_url", ""), db.get_text(key + "_text", "") or "🔗 Batafsil"
    kb = {"inline_keyboard": [[{"text": text, "url": url}]]} if url else None
    mime = med["mime"]
    method, field = (("sendAnimation", "animation") if mime == "image/gif" else ("sendVideo", "video") if mime == "video/mp4" else ("sendPhoto", "photo"))
    extra = {"reply_markup": kb} if kb else {}
    cached = db.get_text(f"fid_{key}", "")
    try:
        if cached.startswith(f"{med['ver']}:"):
            d = await tgapi.call(method, chat_id=chat_id, **{field: cached.split(":", 1)[1]}, caption="📢 Reklama", **extra)
            if d.get("ok"):
                return True
        d = await tgapi.upload(method, field, f"ad.{MIME_EXT.get(mime, 'bin')}", bytes(med["data"]), mime, chat_id=str(chat_id), caption="📢 Reklama", **extra)
        if d.get("ok"):
            r = d["result"]
            fid = (r.get("animation") or r.get("video") or {}).get("file_id") or (r["photo"][-1]["file_id"] if r.get("photo") else "")
            if fid:
                db.set_text(f"fid_{key}", f"{med['ver']}:{fid}")
            return True
    except Exception:
        pass
    return False


async def send_movie(chat_id: int, uid: int, mid: int):
    """Natija: 'ok' | 'none' | 'confirm' (18+ tasdiq kerak) | 'fail'."""
    m = db.movie_get(mid)
    if not m or not m["active"]:
        return "none"
    u = db.get_user(uid)
    if m["age"] >= 18 and not (u and u["adult_ok"]):
        await tgapi.send_message(chat_id, "🔞 Bu kino 18 yoshdan oshganlar uchun. Yoshingiz 18 dan oshganmi?",
                                 reply_markup={"inline_keyboard": [[{"text": "✅ Ha, 18 dan oshganman", "callback_data": f"ad:{mid}"}]]})
        return "confirm"
    st = db.get_settings()
    if db.forced_due(uid, st["forced_every_min"]):
        await send_ad(chat_id, "ad_forced")
    if (m["src"] or "tg") != "tg":                       # YouTube / sayt: Mini App ichida ko'rsatiladi
        kb = keyboard(m)
        try:
            if m["poster_url"] or m["poster_ver"]:
                poster = m["poster_url"] or f"{config.WEBAPP_URL}/media/poster_{m['id']}?v={m['poster_ver']}"
                d = await tgapi.call("sendPhoto", chat_id=chat_id, photo=poster, caption=caption(m), parse_mode="HTML", reply_markup=kb)
            else:
                d = await tgapi.call("sendMessage", chat_id=chat_id, text=caption(m), parse_mode="HTML", reply_markup=kb)
        except Exception:
            return "fail"
        if not d.get("ok"):
            return "fail"
        db.record_view(uid, mid)
        return "ok"
    method, field = ("sendVideo", "video") if m["file_kind"] == "video" else ("sendDocument", "document")
    extra = {"supports_streaming": True} if method == "sendVideo" else {}
    args = dict(chat_id=chat_id, caption=caption(m), parse_mode="HTML", reply_markup=keyboard(m), **extra)
    d = {"ok": False}
    try:
        if method == "sendVideo" and m["poster_ver"] and config.WEBAPP_URL:
            # Admin tanlagan poster kinoning muqovasi bo'ladi (cover). Poster yo'q bo'lsa — videoning o'z rasmi.
            d = await tgapi.call(method, **args, **{field: m["file_id"]}, cover=f"{config.WEBAPP_URL}/media/poster_{m['id']}?v={m['poster_ver']}")
        if not d.get("ok"):
            d = await tgapi.call(method, **args, **{field: m["file_id"]})
    except Exception:
        return "fail"
    if not d.get("ok"):
        return "fail"
    db.record_view(uid, mid)
    return "ok"
