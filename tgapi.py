"""Telegram Bot API (faqat kerakli qismi). Hamma yuborish shu yerdan o'tadi — bot ham, Mini App ham bir xil ishlaydi."""
import asyncio
import json

import config


def _base() -> str:
    return (config.BOT_API_URL or "https://api.telegram.org") + "/bot{}/{}"


async def call(method: str, **params):
    import aiohttp
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as s:
        async with s.post(_base().format(config.BOT_TOKEN, method), json=params) as r:
            return await r.json()


async def upload(method: str, field: str, filename: str, data: bytes, mime: str, **params):
    """Fayl yuklab yuborish (reklama rasmi/GIF/videosi bazadan keladi)."""
    import aiohttp
    form = aiohttp.FormData()
    for k, v in params.items():
        form.add_field(k, v if isinstance(v, str) else json.dumps(v, ensure_ascii=False))
    form.add_field(field, data, filename=filename, content_type=mime)
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120)) as s:
        async with s.post(_base().format(config.BOT_TOKEN, method), data=form) as r:
            return await r.json()


async def download_file(file_id: str, raw: bool = False):
    """Telegram serveridagi faylni yuklab oladi -> (bytes, mime). Xato bo'lsa (b'', '')."""
    import os
    import aiohttp
    d = await call("getFile", file_id=file_id)
    if not d.get("ok"):
        return b"", ""
    path = d["result"].get("file_path", "")
    if path.startswith("/") and os.path.exists(path):            # o'z Bot API serveri: fayl diskda
        return open(path, "rb").read(), "application/octet-stream" if raw else "image/jpeg"
    url = f"{config.BOT_API_URL or 'https://api.telegram.org'}/file/bot{config.BOT_TOKEN}/{path}"
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as s:
        async with s.get(url) as r:
            if r.status != 200:
                return b"", ""
            mime = "image/png" if path.lower().endswith(".png") else "image/webp" if path.lower().endswith(".webp") else "image/jpeg"
            return await r.read(), mime


async def send_message(chat_id: int, text: str, **kw) -> bool:
    try:
        d = await call("sendMessage", chat_id=chat_id, text=text, **kw)
        return bool(d.get("ok"))
    except Exception:
        return False


async def broadcast(user_ids, text: str, delay: float = 0.05) -> int:
    ok = 0
    for uid in user_ids:
        if await send_message(uid, text):
            ok += 1
        await asyncio.sleep(delay)
    return ok
