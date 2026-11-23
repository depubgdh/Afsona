"""Kino bot: ma'lumotlar bazasi va qoidalar (SQLite).

Asosiy tushunchalar:
- movies: kino (kod = raqam, nom, hashtag, emotsiya, yosh chegarasi, sifat, til, Telegram file_id).
- uploads: botga yuborilgan, hali kino bo'lib joylanmagan videolar.
- perms: kino joylashga ruxsat so'rovlari (ism, familya, yil, telefon, e-mail).
- likes / saves / history / affinity: profil va tavsiyalar (affinity — hashtag/emotsiya bo'yicha qiziqish balli).
- media: poster va reklama fayllari. settings: admin sozlamalari.
"""
import re
import sqlite3
import time
from datetime import datetime

import config

DEFAULTS = {
    "forced_every_min": 30,      # shuncha daqiqa ko'rilsa majburiy reklama chiqadi
    "forced_skip_sec": 5,        # majburiy reklamani shuncha soniyadan keyin o'tkazish mumkin
    "top_mode": "auto",          # auto = eng ko'p ko'rilganlar, manual = admin tanlagan tartib
    "top_count": 8,
    "welcome": "Salom, {name}! 🎬 Kino kodini yozing — bot kinoni yuboradi. Yoki kinolarni Mini App ichida qidiring.",
}
QUALITIES = ("480p", "720p", "1080p", "2K", "4K")
AGES = (0, 6, 12, 16, 18)
# tayyor emotsiyalar (admin/joylovchi o'zi ham yangisini yoza oladi)
EMOTIONS = {"horror": "😱", "romantika": "❤️", "komediya": "😂", "drama": "😢", "jangari": "🔥", "fantastika": "🚀",
            "sarguzasht": "🧭", "detektiv": "🕵️", "multfilm": "🧸", "tarixiy": "🏛", "triller": "😰", "oilaviy": "👨‍👩‍👧"}
AD_KEYS = ("ad_main", "ad_forced")           # umumiy reklama (kino ustida) va majburiy reklama
MEDIA_MAX = 3_000_000
AD_MAX = 6_000_000
POSTER_MAX = 1_500_000

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(user_id INTEGER PRIMARY KEY, username TEXT DEFAULT '', first_name TEXT DEFAULT '', photo TEXT DEFAULT '',
  joined REAL, banned INTEGER DEFAULT 0, hist_on INTEGER DEFAULT 1, adult_ok INTEGER DEFAULT 0, last_forced REAL DEFAULT 0, last_seen REAL DEFAULT 0);
CREATE TABLE IF NOT EXISTS movies(id INTEGER PRIMARY KEY AUTOINCREMENT, code INTEGER UNIQUE NOT NULL, title TEXT NOT NULL, year INTEGER DEFAULT 0,
  descr TEXT DEFAULT '', tags TEXT DEFAULT ',', emotions TEXT DEFAULT ',', age INTEGER DEFAULT 0, quality TEXT DEFAULT '', lang TEXT DEFAULT '',
  aliases TEXT DEFAULT '', file_id TEXT DEFAULT '', file_kind TEXT DEFAULT 'video', file_size INTEGER DEFAULT 0, duration INTEGER DEFAULT 0,
  stream_url TEXT DEFAULT '', poster_ver INTEGER DEFAULT 0, ad_url TEXT DEFAULT '', ad_ver INTEGER DEFAULT 0, owner INTEGER DEFAULT 0,
  views INTEGER DEFAULT 0, likes INTEGER DEFAULT 0, top_pos INTEGER DEFAULT 0, active INTEGER DEFAULT 1, created REAL);
CREATE TABLE IF NOT EXISTS likes(user_id INTEGER, movie_id INTEGER, ts REAL, PRIMARY KEY(user_id, movie_id));
CREATE TABLE IF NOT EXISTS saves(user_id INTEGER, movie_id INTEGER, ts REAL, PRIMARY KEY(user_id, movie_id));
CREATE TABLE IF NOT EXISTS history(user_id INTEGER, movie_id INTEGER, ts REAL, PRIMARY KEY(user_id, movie_id));
CREATE TABLE IF NOT EXISTS affinity(user_id INTEGER, tag TEXT, score REAL, PRIMARY KEY(user_id, tag));
CREATE TABLE IF NOT EXISTS perms(user_id INTEGER PRIMARY KEY, status TEXT, first_name TEXT, last_name TEXT, year INTEGER, phone TEXT, email TEXT,
  created REAL, decided REAL DEFAULT 0);
CREATE TABLE IF NOT EXISTS uploads(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, file_id TEXT, uniq TEXT, kind TEXT, size INTEGER,
  duration INTEGER, name TEXT, created REAL, used INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS media(key TEXT PRIMARY KEY, mime TEXT, data BLOB, ver INTEGER);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
CREATE INDEX IF NOT EXISTS i_movies_views ON movies(views DESC);
CREATE INDEX IF NOT EXISTS i_hist ON history(user_id, ts DESC);
"""

_VIEW_SEEN = {}          # (uid, movie_id) -> vaqt: bir kishining bir kinoni qayta-qayta ochishi ko'rishlar sonini oshirmasin


class DbError(Exception):
    def __init__(self, code: str, msg: str = ""):
        super().__init__(code)
        self.code, self.msg = code, msg or code


def connect():
    con = sqlite3.connect(config.DB_PATH, timeout=15, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    return con


def init_db():
    con = connect()
    try:
        con.executescript(SCHEMA)
    finally:
        con.close()


def now() -> float:
    return time.time()


def _q(sql, args=(), one=False):
    con = connect()
    try:
        cur = con.execute(sql, args)
        return (cur.fetchone() if one else cur.fetchall())
    finally:
        con.close()


def _x(sql, args=()):
    con = connect()
    try:
        cur = con.execute(sql, args)
        return cur.lastrowid
    finally:
        con.close()


# ---------------- sozlamalar ----------------
def get_settings() -> dict:
    st = dict(DEFAULTS)
    for r in _q("SELECT key,value FROM settings"):
        if r["key"] in DEFAULTS:
            d = DEFAULTS[r["key"]]
            try:
                st[r["key"]] = int(r["value"]) if isinstance(d, int) else r["value"]
            except ValueError:
                pass
    return st


def set_settings(vals: dict) -> dict:
    for k, v in vals.items():
        if k not in DEFAULTS:
            continue
        if isinstance(DEFAULTS[k], int):
            try:
                v = max(0, min(100000, int(v)))
            except (TypeError, ValueError):
                raise DbError("bad_value", "Son kiriting")
        else:
            v = str(v).strip()[:3000]
            if k == "top_mode" and v not in ("auto", "manual"):
                raise DbError("bad_value", "top_mode noto‘g‘ri")
        _x("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, str(v)))
    return get_settings()


def get_text(key: str, default: str = "") -> str:
    r = _q("SELECT value FROM settings WHERE key=?", (key,), one=True)
    return r["value"] if r else default


def set_text(key: str, value: str):
    _x("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))


# ---------------- media ----------------
def media_get(key: str):
    return _q("SELECT * FROM media WHERE key=?", (key,), one=True)


def media_save(key: str, mime: str, data: bytes) -> int:
    lim = AD_MAX if key.startswith("ad_") else (POSTER_MAX if key.startswith("poster_") else MEDIA_MAX)
    if len(data) > lim:
        raise DbError("big", f"Fayl juda katta (eng ko‘pi {lim / 1e6:.1f} MB)")
    r = media_get(key)
    ver = (r["ver"] + 1) if r else 1
    _x("INSERT INTO media(key,mime,data,ver) VALUES(?,?,?,?) ON CONFLICT(key) DO UPDATE SET mime=excluded.mime,data=excluded.data,ver=excluded.ver",
       (key, mime, data, ver))
    return ver


def media_delete(key: str):
    _x("DELETE FROM media WHERE key=?", (key,))


def media_meta(key: str) -> dict:
    r = _q("SELECT ver, mime FROM media WHERE key=?", (key,), one=True)
    return {"ver": r["ver"], "mime": r["mime"]} if r else {"ver": 0, "mime": ""}


# ---------------- foydalanuvchilar ----------------
def ensure_user(uid: int, username: str, first_name: str, photo: str):
    r = _q("SELECT * FROM users WHERE user_id=?", (uid,), one=True)
    if not r:
        _x("INSERT INTO users(user_id,username,first_name,photo,joined,last_seen) VALUES(?,?,?,?,?,?)", (uid, username, first_name, photo, now(), now()))
    else:
        _x("UPDATE users SET username=?, first_name=?, photo=?, last_seen=? WHERE user_id=?", (username, first_name, photo or r["photo"], now(), uid))
    return _q("SELECT * FROM users WHERE user_id=?", (uid,), one=True)


def get_user(uid: int):
    return _q("SELECT * FROM users WHERE user_id=?", (uid,), one=True)


def set_hist(uid: int, on: bool):
    _x("UPDATE users SET hist_on=? WHERE user_id=?", (1 if on else 0, uid))


def clear_history(uid: int):
    _x("DELETE FROM history WHERE user_id=?", (uid,))


def set_adult(uid: int):
    _x("UPDATE users SET adult_ok=1 WHERE user_id=?", (uid,))


def all_user_ids():
    return [r["user_id"] for r in _q("SELECT user_id FROM users WHERE banned=0")]


# ---------------- matn yordamchilari ----------------
def norm_tags(s) -> list:
    """'#Horror, romantika  #Drama' -> ['horror','romantika','drama']"""
    if isinstance(s, (list, tuple)):
        s = " ".join(str(x) for x in s)
    out = []
    for w in re.findall(r"[\w‘’ʻ']+", str(s or "").lower()):
        w = w.strip("_'‘’ʻ")[:24]
        if w and w not in out:
            out.append(w)
    return out[:12]


def pack(lst) -> str:
    return "," + ",".join(lst) + "," if lst else ","


def unpack(s) -> list:
    return [x for x in (s or "").split(",") if x]


def _norm_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower().replace("‘", "'").replace("’", "'").replace("ʻ", "'"))


# ---------------- ruxsatlar ----------------
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")


def perm_get(uid: int):
    return _q("SELECT * FROM perms WHERE user_id=?", (uid,), one=True)


def can_post(uid: int) -> bool:
    if uid in config.ADMIN_IDS:
        return True
    r = perm_get(uid)
    return bool(r and r["status"] == "approved")


def perm_request(uid: int, d: dict) -> dict:
    cur = perm_get(uid)
    if cur and cur["status"] in ("approved", "pending"):
        raise DbError("exists", "So‘rov allaqachon yuborilgan" if cur["status"] == "pending" else "Sizga ruxsat berilgan")
    first, last = str(d.get("first_name", "")).strip()[:40], str(d.get("last_name", "")).strip()[:40]
    phone = re.sub(r"[^\d+]", "", str(d.get("phone", "")))
    email = str(d.get("email", "")).strip()[:100]
    try:
        year = int(d.get("year"))
    except (TypeError, ValueError):
        year = 0
    if not first or not last:
        raise DbError("bad_name", "Ism va familyani yozing")
    if not 1900 <= year <= datetime.now().year:
        raise DbError("bad_year", "Tug‘ilgan yilingizni to‘g‘ri yozing")
    if len(re.sub(r"\D", "", phone)) < 9:
        raise DbError("bad_phone", "Telefon raqamini to‘g‘ri yozing")
    if not EMAIL_RE.match(email):
        raise DbError("bad_email", "E-mailni to‘g‘ri yozing")
    _x("INSERT INTO perms(user_id,status,first_name,last_name,year,phone,email,created,decided) VALUES(?,?,?,?,?,?,?,?,0) "
       "ON CONFLICT(user_id) DO UPDATE SET status='pending',first_name=excluded.first_name,last_name=excluded.last_name,year=excluded.year,"
       "phone=excluded.phone,email=excluded.email,created=excluded.created,decided=0", (uid, "pending", first, last, year, phone, email, now()))
    return dict(perm_get(uid))


def perm_decide(uid: int, ok: bool):
    r = perm_get(uid)
    if not r:
        raise DbError("none", "So‘rov topilmadi")
    _x("UPDATE perms SET status=?, decided=? WHERE user_id=?", ("approved" if ok else "rejected", now(), uid))


def perm_list(status: str):
    rows = _q("SELECT p.*, u.username FROM perms p LEFT JOIN users u ON u.user_id=p.user_id WHERE p.status=? ORDER BY p.created DESC LIMIT 200", (status,))
    return [dict(r) for r in rows]


# ---------------- yuklangan videolar ----------------
def upload_add(uid: int, kind: str, file_id: str, uniq: str, size: int, duration: int, name: str) -> int:
    r = _q("SELECT id FROM uploads WHERE user_id=? AND uniq=? AND used=0", (uid, uniq), one=True)
    if r:
        return r["id"]
    return _x("INSERT INTO uploads(user_id,file_id,uniq,kind,size,duration,name,created) VALUES(?,?,?,?,?,?,?,?)",
              (uid, file_id, uniq, kind, size or 0, duration or 0, (name or "")[:120], now()))


def uploads_pending(uid: int):
    return [dict(r) for r in _q("SELECT id,kind,size,duration,name,created FROM uploads WHERE user_id=? AND used=0 ORDER BY id DESC LIMIT 30", (uid,))]


# ---------------- kinolar ----------------
def next_code() -> int:
    r = _q("SELECT MAX(code) AS m FROM movies", one=True)
    return (r["m"] or 0) + 1


def movie_get(mid: int):
    return _q("SELECT * FROM movies WHERE id=?", (mid,), one=True)


def movie_by_code(code: int):
    return _q("SELECT * FROM movies WHERE code=? AND active=1", (code,), one=True)


def movie_public(r, uid: int = 0) -> dict:
    d = {"id": r["id"], "code": r["code"], "title": r["title"], "year": r["year"], "descr": r["descr"], "tags": unpack(r["tags"]),
         "emotions": unpack(r["emotions"]), "age": r["age"], "quality": r["quality"], "lang": r["lang"], "views": r["views"], "likes": r["likes"],
         "duration": r["duration"], "size": r["file_size"], "created": r["created"], "active": r["active"],
         "poster": f"/media/poster_{r['id']}?v={r['poster_ver']}" if r["poster_ver"] else ""}
    return d


def _clean_movie(d: dict, is_admin: bool, base: dict = None) -> dict:
    """Maydonlarni tekshiradi. base — tahrirlashda mavjud qiymatlar."""
    b = base or {}
    out = {}
    title = str(d.get("title", b.get("title", ""))).strip()
    if not 1 <= len(title) <= 120:
        raise DbError("bad_title", "Kino nomini yozing (120 belgigacha)")
    out["title"] = title
    try:
        year = int(d.get("year", b.get("year", 0)) or 0)
    except (TypeError, ValueError):
        year = 0
    if year and not 1888 <= year <= datetime.now().year + 2:
        raise DbError("bad_year", "Yil noto‘g‘ri")
    out["year"] = year
    out["descr"] = str(d.get("descr", b.get("descr", ""))).strip()[:1500]
    out["tags"] = pack(norm_tags(d.get("tags", unpack(b.get("tags", ",")))))
    out["emotions"] = pack(norm_tags(d.get("emotions", unpack(b.get("emotions", ",")))))
    try:
        age = int(d.get("age", b.get("age", 0)) or 0)
    except (TypeError, ValueError):
        age = 0
    if age not in AGES:
        raise DbError("bad_age", "Yosh chegarasi noto‘g‘ri")
    out["age"] = age
    q = str(d.get("quality", b.get("quality", ""))).strip()
    if q and q not in QUALITIES:
        raise DbError("bad_quality", "Sifat noto‘g‘ri")
    out["quality"] = q
    out["lang"] = str(d.get("lang", b.get("lang", ""))).strip()[:40]
    if is_admin:                                                   # qo'shimcha so'zlar va to'g'ridan-to'g'ri havola — faqat admin
        out["aliases"] = ",".join(_norm_text(x) for x in re.split(r"[,\n]", str(d.get("aliases", b.get("aliases", "")))) if _norm_text(x))[:300]
        su = str(d.get("stream_url", b.get("stream_url", ""))).strip()[:600]
        if su and not re.match(r"^https?://", su, re.I):
            raise DbError("bad_url", "Video havolasi https:// bilan boshlansin")
        out["stream_url"] = su
        au = str(d.get("ad_url", b.get("ad_url", ""))).strip()[:500]
        if au and not re.match(r"^(https?://|tg://)", au, re.I):
            raise DbError("bad_url", "Reklama havolasi https:// bilan boshlansin")
        out["ad_url"] = au
    return out


def movie_create(uid: int, d: dict, is_admin: bool) -> int:
    up = _q("SELECT * FROM uploads WHERE id=?", (int(d.get("upload_id") or 0),), one=True)
    if not up or up["used"] or (up["user_id"] != uid and not is_admin):
        raise DbError("no_upload", "Avval videoni botga yuboring va ro‘yxatdan tanlang")
    f = _clean_movie(d, is_admin)
    code = 0
    if is_admin and d.get("code"):
        try:
            code = int(d["code"])
        except (TypeError, ValueError):
            raise DbError("bad_code", "Kod raqam bo‘lsin")
        if code < 1 or movie_by_code_any(code):
            raise DbError("code_taken", "Bu kod band")
    code = code or next_code()
    cols = ["code", "file_id", "file_kind", "file_size", "duration", "owner", "created"] + list(f)
    vals = [code, up["file_id"], up["kind"], up["size"], up["duration"], uid, now()] + list(f.values())
    mid = _x(f"INSERT INTO movies({','.join(cols)}) VALUES({','.join('?' * len(cols))})", vals)
    _x("UPDATE uploads SET used=1 WHERE id=?", (up["id"],))
    return mid


def movie_by_code_any(code: int):
    return _q("SELECT id FROM movies WHERE code=?", (code,), one=True)


def movie_update(mid: int, uid: int, d: dict, is_admin: bool):
    m = movie_get(mid)
    if not m or (m["owner"] != uid and not is_admin):
        raise DbError("forbidden", "Bu kinoni o‘zgartira olmaysiz")
    f = _clean_movie(d, is_admin, dict(m))
    if is_admin and d.get("code") and int(d["code"]) != m["code"]:
        code = int(d["code"])
        if code < 1 or movie_by_code_any(code):
            raise DbError("code_taken", "Bu kod band")
        f["code"] = code
    if is_admin:
        f["active"] = 1 if d.get("active", m["active"]) else 0
        f["top_pos"] = max(0, min(999, int(d.get("top_pos", m["top_pos"]) or 0)))
    _x(f"UPDATE movies SET {','.join(k + '=?' for k in f)} WHERE id=?", list(f.values()) + [mid])


def movie_set_media(mid: int, which: str, ver: int):
    _x("UPDATE movies SET poster_ver=? WHERE id=?" if which == "poster" else "UPDATE movies SET ad_ver=? WHERE id=?", (ver, mid))


def movie_delete(mid: int, uid: int, is_admin: bool):
    m = movie_get(mid)
    if not m or (m["owner"] != uid and not is_admin):
        raise DbError("forbidden", "Bu kinoni o‘chira olmaysiz")
    for t in ("likes", "saves", "history"):
        _x(f"DELETE FROM {t} WHERE movie_id=?", (mid,))
    _x("DELETE FROM movies WHERE id=?", (mid,))
    media_delete(f"poster_{mid}")
    media_delete(f"ad_m{mid}")


def list_movies(offset=0, limit=20, tag="", sort="new", only_active=True):
    rows = _q("SELECT * FROM movies" + (" WHERE active=1" if only_active else "") + (" ORDER BY views DESC, id DESC" if sort == "views" else " ORDER BY id DESC"))
    if tag:
        t = _norm_text(tag).lstrip("#")
        rows = [r for r in rows if t in unpack(r["tags"]) or t in unpack(r["emotions"])]
    return rows[offset:offset + limit], len(rows)


def search(q: str, limit=30, include_inactive=False):
    qn = _norm_text(q).lstrip("#")
    if not qn:
        return []
    rows = _q("SELECT * FROM movies" + ("" if include_inactive else " WHERE active=1") + " ORDER BY views DESC")
    out = []
    code = None
    m = re.match(r"^(?:kod|code|kino|№)?[\s:#-]*(\d{1,7})$", qn)
    if m:
        code = int(m.group(1))
    for r in rows:
        title = _norm_text(r["title"])
        score = 0
        if code is not None and r["code"] == code:
            score = 100
        elif title == qn or qn in [a for a in (r["aliases"] or "").split(",") if a]:
            score = 90
        elif title.startswith(qn):
            score = 60
        elif qn in title:
            score = 40
        elif qn in (r["aliases"] or "") or qn in unpack(r["tags"]) or qn in unpack(r["emotions"]):
            score = 20
        if score:
            out.append((score, r["views"], r))
    out.sort(key=lambda x: (-x[0], -x[1]))
    return [x[2] for x in out[:limit]]


def popular_tags(limit=14):
    cnt = {}
    for r in _q("SELECT tags, emotions FROM movies WHERE active=1"):
        for t in unpack(r["tags"]) + unpack(r["emotions"]):
            cnt[t] = cnt.get(t, 0) + 1
    return [t for t, _ in sorted(cnt.items(), key=lambda x: -x[1])[:limit]]


def top_movies():
    st = get_settings()
    n = max(1, st["top_count"])
    if st["top_mode"] == "manual":
        rows = _q("SELECT * FROM movies WHERE active=1 AND top_pos>0 ORDER BY top_pos ASC, id DESC LIMIT ?", (n,))
        if rows:
            return rows
    return _q("SELECT * FROM movies WHERE active=1 ORDER BY views DESC, likes DESC, id DESC LIMIT ?", (n,))


# ---------------- ijtimoiy: like / saqlash / tarix / tavsiya ----------------
def _affinity_add(uid: int, mv, w: float):
    for t in unpack(mv["tags"]):
        _x("INSERT INTO affinity(user_id,tag,score) VALUES(?,?,?) ON CONFLICT(user_id,tag) DO UPDATE SET score=score+?", (uid, t, w, w))
    for t in unpack(mv["emotions"]):
        _x("INSERT INTO affinity(user_id,tag,score) VALUES(?,?,?) ON CONFLICT(user_id,tag) DO UPDATE SET score=score+?", (uid, t, w * 1.5, w * 1.5))


def toggle(kind: str, uid: int, mid: int) -> bool:
    """kind: 'likes' | 'saves'. Yangi holatni (True = qo'yildi) qaytaradi."""
    mv = movie_get(mid)
    if not mv:
        raise DbError("none", "Kino topilmadi")
    have = _q(f"SELECT 1 FROM {kind} WHERE user_id=? AND movie_id=?", (uid, mid), one=True)
    if have:
        _x(f"DELETE FROM {kind} WHERE user_id=? AND movie_id=?", (uid, mid))
        on = False
    else:
        _x(f"INSERT INTO {kind}(user_id,movie_id,ts) VALUES(?,?,?)", (uid, mid, now()))
        _affinity_add(uid, mv, 3.0 if kind == "likes" else 2.0)
        on = True
    if kind == "likes":
        _x("UPDATE movies SET likes=(SELECT COUNT(*) FROM likes WHERE movie_id=?) WHERE id=?", (mid, mid))
    return on


def flags(uid: int, mid: int) -> dict:
    return {"liked": bool(_q("SELECT 1 FROM likes WHERE user_id=? AND movie_id=?", (uid, mid), one=True)),
            "saved": bool(_q("SELECT 1 FROM saves WHERE user_id=? AND movie_id=?", (uid, mid), one=True))}


def record_view(uid: int, mid: int):
    """Kino ko'rildi: ko'rishlar soni, (tarix yoqilgan bo'lsa) tarix va qiziqish balli."""
    mv = movie_get(mid)
    if not mv:
        return
    last = _VIEW_SEEN.get((uid, mid), 0)
    if now() - last < 600:
        return
    _VIEW_SEEN[(uid, mid)] = now()
    _x("UPDATE movies SET views=views+1 WHERE id=?", (mid,))
    u = get_user(uid)
    if u and u["hist_on"]:
        _x("INSERT INTO history(user_id,movie_id,ts) VALUES(?,?,?) ON CONFLICT(user_id,movie_id) DO UPDATE SET ts=excluded.ts", (uid, mid, now()))
        _affinity_add(uid, mv, 1.0)


def my_list(kind: str, uid: int, limit=100):
    tbl = {"like": "likes", "save": "saves", "history": "history"}[kind]
    return _q(f"SELECT m.* FROM {tbl} t JOIN movies m ON m.id=t.movie_id WHERE t.user_id=? AND m.active=1 ORDER BY t.ts DESC LIMIT ?", (uid, limit))


def counts(uid: int) -> dict:
    return {k: _q(f"SELECT COUNT(*) c FROM {t} WHERE user_id=?", (uid,), one=True)["c"] for k, t in (("like", "likes"), ("save", "saves"), ("history", "history"))}


def recommend(uid: int, limit=12):
    """YouTube kabi: ko'rgan/yoqtirgan kinolarning hashtag va emotsiyalariga mos kinolar."""
    aff = {r["tag"]: r["score"] for r in _q("SELECT tag,score FROM affinity WHERE user_id=?", (uid,))}
    if not aff:
        return []
    seen = {r["movie_id"] for r in _q("SELECT movie_id FROM history WHERE user_id=?", (uid,))}
    out = []
    for r in _q("SELECT * FROM movies WHERE active=1"):
        s = sum(aff.get(t, 0) for t in set(unpack(r["tags"]) + unpack(r["emotions"])))
        if s <= 0:
            continue
        if r["id"] in seen:
            s *= 0.25
        out.append((s + min(r["views"], 1000) * 0.001, r))
    out.sort(key=lambda x: -x[0])
    return [x[1] for x in out[:limit]]


# ---------------- reklama (bot orqali yuborishda) ----------------
def forced_due(uid: int, every_min: int) -> bool:
    """Botga yuborishda: oxirgi majburiy reklamadan beri `every_min` daqiqa o'tgan bo'lsa True. Birinchi marta — faqat vaqtni boshlaydi."""
    u = get_user(uid)
    if not u:
        return False
    if not u["last_forced"]:
        _x("UPDATE users SET last_forced=? WHERE user_id=?", (now(), uid))
        return False
    if now() - u["last_forced"] >= every_min * 60:
        _x("UPDATE users SET last_forced=? WHERE user_id=?", (now(), uid))
        return True
    return False


def stats() -> dict:
    one = lambda s: _q(s, one=True)["c"]
    top = [{"title": r["title"], "code": r["code"], "views": r["views"]} for r in _q("SELECT title,code,views FROM movies ORDER BY views DESC LIMIT 5")]
    return {"users": one("SELECT COUNT(*) c FROM users"), "movies": one("SELECT COUNT(*) c FROM movies"), "views": one("SELECT COALESCE(SUM(views),0) c FROM movies"),
            "likes": one("SELECT COUNT(*) c FROM likes"), "pending": one("SELECT COUNT(*) c FROM perms WHERE status='pending'"),
            "approved": one("SELECT COUNT(*) c FROM perms WHERE status='approved'"), "top": top}
