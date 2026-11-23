"""Telegram bot (aiogram 3): kino kodi yoki nomi bo'yicha kinoni yuboradi, ruxsat berilganlar video qabul qiladi, admin so'rovlarni tasdiqlaydi."""
import html
import re

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo

import api
import config
import db
import deliver

router = Router()
CODE_RE = re.compile(r"^[\s\[\(\{<#/]*(?:kod|code|kino|film|№|no)?[\s:=.\-#№]*?(\d{1,7})[\s\]\)\}>]*$", re.I)


def parse_code(text: str):
    """'1', '[1]', '[ 1 ]', 'kod1', '[kod1]', '[kod : 1 ]', '[ kod:1]', '[/1]', '/1', '#1' ... -> 1; boshqa matn -> None."""
    m = CODE_RE.match((text or "").strip())
    return int(m.group(1)) if m else None


def app_kb(text="🎬 Kinolarni ochish", path="") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=text, web_app=WebAppInfo(url=config.WEBAPP_URL + path))]])


async def send_by_id(m: Message, mid: int):
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
                        getattr(f, "file_name", "") or (m.caption or ""))
    mb = (f.file_size or 0) / 1048576
    await m.answer(f"✅ Video qabul qilindi{f' ({mb:.0f} MB)' if mb else ''}.\nEndi ma’lumotlarini to‘ldiring: nomi, rasmi, hashtag, emotsiya, yosh chegarasi.",
                   reply_markup=app_kb("📝 Ma’lumotlarni to‘ldirish", "?tab=post"))


@router.message(F.chat.type == "private", F.text)
async def text_msg(m: Message):
    u = m.from_user
    db.ensure_user(u.id, u.username or "", u.first_name or "", "")
    text = (m.text or "").strip()
    code = parse_code(text)
    if code is not None:
        mv = db.movie_by_code(code)
        if mv:
            return await send_by_id(m, mv["id"])
        return await m.answer(f"😕 {code}-kodli kino topilmadi.")
    rows = db.search(text, 8)
    if rows and rows[0]["title"].strip().lower() == text.lower() and len(rows) == 1 or (rows and rows[0]["aliases"] and text.lower() in rows[0]["aliases"].split(",")):
        return await send_by_id(m, rows[0]["id"])
    if not rows:
        return await m.answer("😕 Hech narsa topilmadi. Kino kodini yozing yoki nomini tekshiring.", reply_markup=app_kb("🔍 Mini App’da qidirish"))
    kb = [[InlineKeyboardButton(text=f"🎬 {r['title'][:40]}" + (f" ({r['year']})" if r["year"] else "") + f" · {r['code']}", callback_data=f"mv:{r['id']}")] for r in rows]
    await m.answer("Topilgan kinolar:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


@router.callback_query(F.data.startswith("mv:"))
async def cb_movie(cb: CallbackQuery):
    await cb.answer()
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
