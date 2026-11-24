# Kino bot + Mini App (v2)

Telegram bot: kino kodini yozasiz — bot kinoni yuboradi. Mini App: qidiruv, top kinolar, ko'rish (video/YouTube/sayt), profil, kino joylash, admin panel.

## Render sozlamalari
Build: `pip install -r requirements.txt`   Start: `python main.py`

Environment (Render → Environment):
| Nom | Qiymat |
|---|---|
| BOT_TOKEN | @BotFather bergan token |
| ADMIN_IDS | Sizning Telegram ID (raqam, @userinfobot dan). Bir nechta bo'lsa vergul bilan |
| WEBAPP_URL | Render manzilingiz, masalan https://kinobot.onrender.com (bo'sh qolsa RENDER_EXTERNAL_URL olinadi) |
| DB_PATH | /data/kinobot.sqlite3 (Render Disk ni /data ga ulang — aks holda bazа har deployda o'chadi) |
| BOT_USERNAME | ixtiyoriy (@siz) |
| BOT_API_URL | ixtiyoriy: o'z Bot API serveringiz (katta filmlarni Mini App'da ko'rsatish uchun) |

PORT avtomatik. Bepul tarif uxlab qoladi — pullik tarif yoki /health ga ping tavsiya etiladi.
BotFather: /setmenubutton shart emas (bot o'zi qo'yadi). Bot Mini App uchun Domain sifatida WEBAPP_URL ni oladi.

## Majburiy obuna
1. Botni kanal/guruhga ADMIN qiling — Mini App → Admin → Obuna ro'yxatida o'zi chiqadi (chiqmasa @username yoki t.me havola bilan qo'shing, «Yangilash»).
2. Kerakli kanallarni yoqing (eng ko'pi 15). Bot kod yozilganda, /start dan keyin va Mini App ochilganda obunani tekshiradi; «Tekshirish» tugmasi bor.

## Kino qo'shish (admin)
- Botga video yuborish → Mini App → Kino joylash.
- Telegram havola: guruh/kanaldagi post havolasini (t.me/kanal/123) Mini App'da «Telegram havola»ga yoki botga to'g'ridan-to'g'ri yuboring — bot videoni oladi (bot o'sha chatda a'zo bo'lishi, kontent himoyalanmagan bo'lishi kerak).
- YouTube / sayt havolasi: kod yozish shart emas, Mini App ichida ko'rsatiladi (.mp4, .m3u8, YouTube, boshqa sayt pleyeri).

## Eslatma
- Telegramda turgan katta (20 MB+) filmlar Mini App'da faqat o'z Bot API serveringiz (BOT_API_URL) yoki «video havolasi» bilan ko'rinadi; aks holda botga yuboriladi.
- Sayt pleyerida (iframe) majburiy reklama vaqt bo'yicha chiqadi, pleyerni to'xtata olmaydi.
- Mini App'da emoji yo'q; ranglar index.html boshidagi `:root` da.
