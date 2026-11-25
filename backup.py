"""Baza zaxirasi: Render bepul tarifida fayl tizimi har deployda tozalanadi.
Bot bazani vaqti-vaqti bilan admin chatiga yuboradi va PIN qiladi; yangi ishga tushganda baza bo'sh bo'lsa, o'sha yerdan o'zi tiklaydi."""
import asyncio
import logging
import os
import sqlite3
import tempfile
import time

import config
import tgapi

NAME = "kinobot-backup.sqlite3"
LIMIT = 49 * 1024 * 1024
_state = {"sig": None, "t": 0.0, "warned": False}
log = logging.getLogger("backup")


def _sig():
    s = []
    for suf in ("", "-wal"):
        try:
            st = os.stat(config.DB_PATH + suf)
            s.append((st.st_mtime_ns, st.st_size))
        except OSError:
            s.append(None)
    return tuple(s)


def movie_count(path: str) -> int:
    try:
        con = sqlite3.connect(path)
        try:
            return con.execute("SELECT COUNT(*) FROM movies").fetchone()[0]
        finally:
            con.close()
    except Exception:
        return 0


def _snapshot() -> bytes:
    tmp = tempfile.mktemp(suffix=".sqlite3")
    src = sqlite3.connect(config.DB_PATH)
    dst = sqlite3.connect(tmp)
    try:
        src.backup(dst)
    finally:
        dst.close(); src.close()
    try:
        return open(tmp, "rb").read()
    finally:
        os.remove(tmp)


def install(data: bytes) -> bool:
    """Zaxira faylini bazaning o'rniga qo'yadi (avval tekshiradi)."""
    tmp = config.DB_PATH + ".restore"
    d = os.path.dirname(config.DB_PATH)
    if d:
        os.makedirs(d, exist_ok=True)
    open(tmp, "wb").write(data)
    try:
        con = sqlite3.connect(tmp)
        ok = con.execute("PRAGMA quick_check").fetchone()[0] == "ok" and con.execute("SELECT COUNT(*) FROM movies").fetchone() is not None
        con.close()
    except Exception:
        ok = False
    if not ok:
        os.remove(tmp)
        return False
    for suf in ("-wal", "-shm"):
        try:
            os.remove(config.DB_PATH + suf)
        except OSError:
            pass
    os.replace(tmp, config.DB_PATH)
    return True


async def restore_if_empty() -> bool:
    """Baza bo'sh bo'lsa — adminning pin qilingan zaxirasidan tiklaydi."""
    if movie_count(config.DB_PATH) > 0:
        return False
    for admin in config.ADMIN_IDS:
        try:
            d = await tgapi.call("getChat", chat_id=admin)
            doc = ((d.get("result") or {}).get("pinned_message") or {}).get("document") or {}
            if not (doc.get("file_name") or "").startswith("kinobot-backup"):
                continue
            data, _ = await tgapi.download_file(doc["file_id"], raw=True)
            if data and install(data):
                log.warning("Baza zaxiradan tiklandi (%s)", admin)
                return True
        except Exception as e:
            log.warning("tiklash xatosi: %s", e)
    return False


async def run_once(force=False) -> str:
    """Zaxira yuboradi. Qaytaradi: 'ok' | 'skip' | 'big' | 'fail'."""
    sig = _sig()
    if not force and sig == _state["sig"]:
        return "skip"
    if not config.ADMIN_IDS or movie_count(config.DB_PATH) == 0 and not force:
        return "skip"
    admin = sorted(config.ADMIN_IDS)[0]
    data = await asyncio.to_thread(_snapshot)
    if len(data) > LIMIT:
        if not _state["warned"]:
            _state["warned"] = True
            await tgapi.send_message(admin, "Baza 49 MB dan oshdi, zaxira yuborilmaydi. Render Disk ulang.")
        return "big"
    old = None
    try:
        d = await tgapi.call("getChat", chat_id=admin)
        old = ((d.get("result") or {}).get("pinned_message") or {}).get("message_id")
    except Exception:
        pass
    r = await tgapi.upload("sendDocument", "document", NAME, data, "application/octet-stream", chat_id=str(admin), disable_notification="true",
                           caption="Zaxira nusxa (o‘chirmang). Bot qayta ishga tushganda baza shu yerdan tiklanadi.")
    if not r.get("ok"):
        return "fail"
    mid = r["result"]["message_id"]
    try:
        await tgapi.call("pinChatMessage", chat_id=admin, message_id=mid, disable_notification=True)
        if old:
            await tgapi.call("deleteMessage", chat_id=admin, message_id=old)
    except Exception:
        pass
    _state["sig"], _state["t"] = sig, time.time()
    return "ok"


async def loop():
    await asyncio.sleep(45)
    while True:
        try:
            if time.time() - _state["t"] > 120:
                await run_once()
        except Exception as e:
            log.warning("zaxira xatosi: %s", e)
        await asyncio.sleep(60)
