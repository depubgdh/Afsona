"""Telegram bot (aiogram 3): kino kodi yoki nomi bo'yicha kinoni yuboradi, ruxsat berilganlar video qabul qiladi, admin so'rovlarni tasdiqlaydi."""
import html
import re

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, ChatMemberUpdated, InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo

import api
import config
import db
import backup
import deliver
import subs
import tgapi

router = Router()
CODE_RE = re.compile(r"^[\s\[\(\{<#/]*(?:kod|code|kino|film|№|no)?[\s:=.\-#№]*?(\d{1,7})[\s\]\)\}>]*$", re.I)


def parse_code(text: str):
    """'1', '[1]', '[ 1 ]', 'kod1', '[kod1]', '[kod : 1 ]', '[ kod:1]', '[/1]', '/1', '#1' ... -> 1; boshqa matn -> None."""
    m = CODE_RE.match((text or "").strip())
    return int(m.group(1)) if m else None


def app_kb(text="🎬 Kinolarni ochish", path="") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=text, web_app=WebAppInfo(url=config.WEBAPP_URL + path))]])


async def need_sub(chat_id: int, uid: int, cb_data: str) -> bool:
    """True bo'lsa — foydalanuvchi obuna emas, xabar yuborildi."""
    miss = await subs.missing(uid, fresh=True)
    if not miss:
        return False
    await tgapi.send_message(chat_id, subs.SUB_TEXT, reply_markup=subs.sub_keyboard(miss, cb_data))
    return True


async def send_by_id(m: Message, mid: int):
    if await need_sub(m.chat.id, m.from_user.id, f"sub:{mid}"):
        return
    res = await deliver.send_movie(m.chat.id, m.from_user.id, mid)
    if res == "none":
        await m.answer("😕 Kino topilmadi.")
    elif res == "fail":
        await m.answer("⚠️ Kinoni yuborib bo‘lmadi. Birozdan so‘ng urinib ko‘ring.")


@router.message(CommandStart())
async def start(m: Message, command: CommandObject):
    u = m.from_user
    db.ensure_user(u.id, u.username or "", u.first_name or "", "")
    arg = (command.args or "").strip()
    if not arg and await need_sub(m.chat.id, u.id, "sub:0"):
        return
    if arg.startswith("m_") and arg[2:].isdigit():                 # t.me/bot?start=m_12  — kino havolasi
        return await send_by_id(m, int(arg[2:]))
    if arg.isdigit():
        mv = db.movie_by_code(int(arg))
        if mv:
            return await send_by_id(m, mv["id"])
    text = db.get_settings()["welcome"].replace("{name}", u.first_name or u.username or "do‘st")
    await m.answer(text, reply_markup=app_kb())


@router.message(Command("admin"))
async def admin(m: Message):
    if m.from_user.id in config.ADMIN_IDS:
        await m.answer("🛠 Admin panel Mini App ichida: ochib, yuqoridagi ⚙ tugmasini bosing.", reply_markup=app_kb("🛠 Admin panelni ochish"))


@router.message(F.chat.type == "private", F.document, F.document.file_name.startswith("kinobot-backup"))
async def restore_backup(m: Message):
    """Admin zaxira faylini botga yuborsa — baza shu fayldan tiklanadi."""
    if m.from_user.id not in config.ADMIN_IDS:
        return
    data, _ = await tgapi.download_file(m.document.file_id, raw=True)
    if data and backup.install(data):
        db.init_db()
        await m.answer("Baza zaxiradan tiklandi.")
    else:
        await m.answer("Zaxira faylini o‘qib bo‘lmadi.")


@router.message(F.chat.type == "private", F.video | F.document)
async def got_file(m: Message):
    """Video qabul qilish: faqat admin va ruxsat berilganlar."""
    u = m.from_user
    db.ensure_user(u.id, u.username or "", u.first_name or "", "")
    f = m.video or m.document
    if m.document and not (m.document.mime_type or "").startswith("video/"):
        return await m.answer("Faqat video fayl yuboring.")
    if not db.can_post(u.id):
        return await m.answer("🔒 Kino joylash uchun admin ruxsati kerak. Mini App → «Kino joylash» bo‘limida so‘rov yuboring.", reply_markup=app_kb("📝 So‘rov yuborish", "?tab=post"))
    uid = db.upload_add(u.id, "video" if m.video else "document", f.file_id, f.file_unique_id, f.file_size or 0, getattr(f, "duration", 0) or 0,
                        getattr(f, "file_name", "") or (m.caption or ""), (f.thumbnail.file_id if getattr(f, "thumbnail", None) else ""))
    mb = (f.file_size or 0) / 1048576
    await m.answer(f"✅ Video qabul qilindi{f' ({mb:.0f} MB)' if mb else ''}.\nEndi ma’lumotlarini to‘ldiring: nomi, rasmi, hashtag, emotsiya, yosh chegarasi.",
                   reply_markup=app_kb("📝 Ma’lumotlarni to‘ldirish", "?tab=post"))


@router.message(F.chat.type == "private", F.text)
async def text_msg(m: Message):
    u = m.from_user
    db.ensure_user(u.id, u.username or "", u.first_name or "", "")
    text = (m.text or "").strip()
    if u.id in config.ADMIN_IDS and subs.parse_tme(text) and not parse_code(text):
        return await admin_link(m, text)
    code = parse_code(text)
    if code is not None:
        mv = db.movie_by_code(code)
        if mv:
            return await send_by_id(m, mv["id"])
        return await m.answer(f"😕 {code}-kodli kino topilmadi.")
    if await need_sub(m.chat.id, u.id, "sub:0"):
        return
    rows = db.search(text, 8)
    if rows and rows[0]["title"].strip().lower() == text.lower() and len(rows) == 1 or (rows and rows[0]["aliases"] and text.lower() in rows[0]["aliases"].split(",")):
        return await send_by_id(m, rows[0]["id"])
    if not rows:
        return await m.answer("😕 Hech narsa topilmadi. Kino kodini yozing yoki nomini tekshiring.", reply_markup=app_kb("🔍 Mini App’da qidirish"))
    kb = [[InlineKeyboardButton(text=f"🎬 {r['title'][:40]}" + (f" ({r['year']})" if r["year"] else "") + f" · {r['code']}", callback_data=f"mv:{r['id']}")] for r in rows]
    await m.answer("Topilgan kinolar:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


async def admin_link(m: Message, url: str):
    """Admin guruh/kanal posti havolasini tashladi: videoni olib, ro'yxatga qo'shamiz."""
    try:
        r = await subs.import_from_link(url, m.from_user.id)
    except db.DbError as e:
        return await m.answer("⚠️ " + e.msg)
    db.upload_add(m.from_user.id, r["file_kind"], r["file_id"], r["file_unique_id"], r["file_size"], r["duration"], r["title"], r.get("thumb", ""))
    mb = r["file_size"] / 1048576
    await m.answer(f"✅ Video olindi{f' ({mb:.0f} MB)' if mb else ''}. Endi Mini App → Kino joylash bo‘limida ma’lumotlarini to‘ldiring.",
                   reply_markup=app_kb("Ma’lumotlarni to‘ldirish", "?tab=post"))


@router.callback_query(F.data.startswith("sub:"))
async def cb_sub(cb: CallbackQuery):
    miss = await subs.missing(cb.from_user.id, fresh=True)
    if miss:
        return await cb.answer("Hali hamma kanalga obuna bo‘lmadingiz", show_alert=True)
    await cb.answer("Rahmat!")
    mid = int(cb.data[4:] or 0)
    if mid:
        res = await deliver.send_movie(cb.message.chat.id, cb.from_user.id, mid)
        if res == "none":
            await cb.message.answer("Kino topilmadi.")
    else:
        u = cb.from_user
        await cb.message.answer(db.get_settings()["welcome"].replace("{name}", u.first_name or "do‘st"), reply_markup=app_kb())


@router.my_chat_member()
async def on_my_chat(ev: ChatMemberUpdated):
    """Bot kanal/guruhga qo'shilsa yoki admin qilinsa — ro'yxatga yozib boramiz."""
    ch = ev.chat
    if ch.type not in ("channel", "group", "supergroup"):
        return
    st = ev.new_chat_member.status
    if st in ("left", "kicked"):
        return db.chat_remove(ch.id)
    db.chat_upsert(ch.id, ch.title or ch.username or str(ch.id), ch.type, ch.username or "", st == "administrator")
    if st != "administrator":
        db._x("UPDATE chats SET required=0 WHERE chat_id=?", (ch.id,))


@router.callback_query(F.data.startswith("mv:"))
async def cb_movie(cb: CallbackQuery):
    await cb.answer()
    if await need_sub(cb.message.chat.id, cb.from_user.id, f"sub:{cb.data[3:]}"):
        return
    res = await deliver.send_movie(cb.message.chat.id, cb.from_user.id, int(cb.data[3:]))
    if res == "none":
        await cb.message.answer("😕 Kino topilmadi.")


@router.callback_query(F.data.startswith("ad:"))
async def cb_adult(cb: CallbackQuery):
    db.set_adult(cb.from_user.id)
    await cb.answer("Tasdiqlandi")
    await deliver.send_movie(cb.message.chat.id, cb.from_user.id, int(cb.data[3:]))


@router.callback_query(F.data.startswith(("lk:", "sv:")))
async def cb_like(cb: CallbackQuery):
    kind = "likes" if cb.data.startswith("lk:") else "saves"
    try:
        on = db.toggle(kind, cb.from_user.id, int(cb.data[3:]))
    except db.DbError as e:
        return await cb.answer(e.msg, show_alert=True)
    await cb.answer(("❤️ Yoqtirganlarga qo‘shildi" if on else "Yoqtirishdan olindi") if kind == "likes" else ("🔖 Saqlandi" if on else "Saqlanganlardan olindi"))


@router.callback_query(F.data.startswith("pm:"))
async def cb_perm(cb: CallbackQuery):
    if cb.from_user.id not in config.ADMIN_IDS:
        return await cb.answer("Ruxsat yo‘q", show_alert=True)
    _, act, uid = cb.data.split(":")
    try:
        await api.resolve_perm(int(uid), act == "ok")
    except db.DbError as e:
        return await cb.answer(e.msg, show_alert=True)
    await cb.message.edit_text((cb.message.html_text or "") + ("\n\n✅ Ruxsat berildi" if act == "ok" else "\n\n❌ Rad etildi"), parse_mode="HTML")
    await cb.answer("Bajarildi")
