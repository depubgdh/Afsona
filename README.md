# Kino bot — Telegram bot + Mini App

## Ishga tushirish
1. @BotFather'da bot yarating, tokenni oling.
2. `.env.example` dagi qiymatlarni muhit o'zgaruvchisi qiling (`BOT_TOKEN`, `ADMIN_IDS`, `WEBAPP_URL`).
3. `pip install -r requirements.txt`, so'ng `python main.py` (bot va Mini App bitta jarayonda; `WEBAPP_URL` — shu serverning https manzili).
4. Admin: `/admin` yoki Mini App → ⚙. Sinov (Telegramsiz): `python dev_server.py` → `http://localhost:8771/?dev=1`.

## Foydalanuvchi uchun
- Botga **kino kodini** yozing: `1`, `[1]`, `[ 1 ]`, `kod1`, `[kod1]`, `[kod : 1 ]`, `[ kod:1]`, `[/1]`, `/1`, `#1` — hammasi bir xil ishlaydi. Admin faqat raqamni belgilaydi.
- Kino **nomi** yozilsa, bot topilganlarni tugmalar bilan ko'rsatadi.
- Mini App: **Kinolar** (tepa chapda 🔍 qidiruv: nom yoki kod; ustida TOP kinolar; «Siz uchun» tavsiyalar; hashtag/janr tugmalari; 16:9 kartalar), **Profil** (yoqtirgan, saqlangan, tarix; tarixni yozishni o'chirish), **Kino joylash**.
- Tavsiyalar YouTube kabi: ko'rgan/yoqtirgan/saqlagan kinolarning hashtag va emotsiyalariga mos kinolar ko'proq chiqadi.
- 18+ kinolar oldidan yoshni tasdiqlash so'raladi.

## Kino joylash va ruxsat
- Faqat admin ruxsat bergan kishilar joylaydi. Ruxsat uchun so'rov: ism, familya, tug'ilgan yili, telefon, e-mail. So'rov adminga botda ✅/❌ tugmalari bilan keladi (yoki Admin → So'rovlar).
- Joylash: 1) video faylni botga yuboring; 2) Mini App → Kino joylash → videoni tanlab nomi, poster (16:9), hashtag, emotsiya, yosh chegarasi, sifat (480p–4K), til yozing. Kod avtomatik beriladi.
- Admin qo'shimcha: kodni o'zi tanlaydi, qo'shimcha qidiruv so'zlari, to'g'ridan-to'g'ri video havolasi, shu kinoga alohida reklama, kinoni yashirish/o'chirish, TOP ro'yxat.

## Reklama
- **Umumiy reklama**: kino ustida (Mini App pleyerida), botda kino tagida havola tugmasi. Kinoning o'z reklamasi bo'lsa, o'sha ko'rinadi.
- **Majburiy reklama**: Mini App pleyerida har N daqiqalik (standart 30) ko'rishdan keyin to'liq ekranda; botda — oxirgi reklamadan N daqiqa o'tgach, kinodan oldin yuboriladi. Tagida havola tugmasi.
- Rasm, GIF yoki MP4 (6 MB gacha) va havola — Admin → Reklama.

## Katta kinolar haqida (muhim)
Telegram oddiy Bot API orqali fayllarni 20 MB gacha beradi. Shuning uchun:
- Kino botga **har qanday hajmda** yuboriladi va foydalanuvchiga bot orqali chiqadi (file_id).
- **Mini App ichida ko'rsatish** (va 30 daqiqalik reklama) uchun: kino ≤ 20 MB, yoki admin «video havolasi» (.mp4) qo'ygan, yoki o'z Bot API serveringiz (`BOT_API_URL`, `telegram-bot-api --local`) ulangan bo'lishi kerak. Aks holda Mini App «Botga yuborish» tugmasini ko'rsatadi.
