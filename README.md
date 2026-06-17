# Ticket Tracking Telegram Bot 🚆🚌

Poyezd (eticket.railway.uz) va Avtobus (avtoticket.uz) chiptalarining bo'sh joylarini avtomatik ravishda kuzatib boruvchi va chipta paydo bo'lganda foydalanuvchiga Telegram orqali tezkor xabarnoma yuboruvchi asinxron Telegram Bot tizimi.

---

## 🚀 Texnologiyalar (Tech Stack)

- **Language:** Python 3.12 (Slim base image)
- **Framework:** [Aiogram v3](https://github.com/aiogram/aiogram) (Telegram Bot API)
- **Database:** PostgreSQL 16
- **ORM / Migrations:** SQLAlchemy 2.0 & Alembic
- **HTTP Client:** [Httpx](https://github.com/encode/httpx) (To'liq asinxron)
- **Containerization:** Docker & Docker Compose

---

## ⚡ Asosiy Imkoniyatlar va Optimallashtirishlar

1. **Guruh-asosli So'rovlar (Group-Based Tracker):** Tizim bir xil yo'nalish va sanaga qo'yilgan kuzatuvlarni guruhlaydi va tashqi API ga faqat bitta unikal so'rov yuboradi. Bu Chromium/Playwright yordamida har bir kuzatuv uchun alohida brauzer ishga tushirish muammosini yo'qotadi.
2. **Playwright-Free Scraper:** Poezd chiptalari seansini simulyatsiya qilish orqali butunlay HTTP (`httpx`) so'rovlariga o'tkazildi. Bu xizmat hajmini **3GB dan 180MB gacha** kamaytirdi, RAM va CPU sarfini deyarli nolga tushirdi.
3. **Retry & Backoff:** Tarmoq uzilishlari yoki vaqtincha `429 Too Many Requests` xatoliklarida tizim 3 martagacha exponential kutish (backoff) bilan qayta urinadi.
4. **Admin ogohlantirishlari (Critical Alerts):** Har qanday persistent blok yoki xatoliklarda background worker Telegram orqali adminni zudlik bilan xabardor qiladi.
5. **Ma'lumotlar Bazasi Indekslari:** Tez-tez filter qilinadigan `subscriptions` va `users` ustunlariga B-Tree indekslari qo'shildi (`idx_subscriptions_active_date`).
6. **Xavfsiz Production Arxitekturasi:** PostgreSQL porti tashqariga yopilgan. Konteynerlar o'zaro virtual tarmoqda ishlaydi va resurs limitlari o'rnatilgan.

---

## 🛠️ Loyihani Ishga Tushirish (Quick Start)

### 1. Muhit Sozlamalari (.env)

Loyiha ildiz papkasida `.env` faylini yarating va quyidagi o'zgaruvchilarni sozlang:

```env
BOT_TOKEN=your_telegram_bot_token
ADMIN_ID=your_telegram_user_id

# Database Settings
POSTGRES_USER=postgres
POSTGRES_PASSWORD=your_secure_password
POSTGRES_DB=ticket_track
DATABASE_URL=postgresql+asyncpg://postgres:your_secure_password@db:5432/ticket_track
```

### 2. Ishga tushirish (Docker Compose)

#### Development muhiti uchun (Local build):
```bash
docker compose up --build -d
```

#### Production (Jonli) muhiti uchun (Volumesiz, cheklangan resurslar bilan):
```bash
docker compose -f docker-compose.prod.yml up --build -d
```

### 3. Ma'lumotlar Bazasi Migratsiyalari (Alembic)

Konteyner ishga tushganidan so'ng jadvallar va indekslarni yaratish uchun migratsiyani HEAD versiyaga yangilang:

```bash
docker compose exec bot alembic upgrade head
```

---

## 📂 Loyiha Tuzilishi (Project Structure)

```
├── alembic.ini             # Alembic sozlamalari
├── bot/                    # Telegram Bot kodi
│   ├── core/               # Konfiguratsiya va sozlamalar
│   ├── handlers/           # Telegram handlerlar (start, search, tracking, admin)
│   ├── keyboards/          # Inline tugmalar
│   └── Dockerfile          # Bot Dockerfile (Python 3.12-slim)
├── shared/                 # Bot va Tracker ulashadigan kodlar
│   ├── database.py         # DB ulanish seansi
│   ├── models.py           # SQLAlchemy modellar (User, Subscription, State)
│   ├── translations.py     # Ko'p tillilik (UZ, RU, EN) tarjimalari
│   └── migrations/         # Alembic migratsiya fayllari
├── tracker/                # Background worker (Kuzatuvchi jarayon)
│   ├── avtoticket.py       # Avtobus API skraperi (Async HTTP)
│   ├── railway.py          # Poezd API skraperi (Async HTTP)
│   ├── scheduler.py        # Obunalarni guruhlab tekshiruvchi loop
│   └── Dockerfile          # Tracker Dockerfile (Python 3.12-slim)
├── docker-compose.yml      # Dev compose fayli (Port binds va local volumes)
└── docker-compose.prod.yml # Prod compose fayli (Secure, self-contained)
```

---

## 📈 Unumdorlik Ko'rsatkichlari (Production Benchmarks)

- **Baza hajmi yuklamasi:** Indekslar hisobiga faol obunalar millisoniyada filtrlanadi.
- **Sessiya vaqti:** Har bir route tekshirish o'rtacha 0.4s vaqt oladi.
- **Xotira sarfi (Memory Footprint):**
  - Bot container: **~35MB**
  - Tracker container: **~45MB**
  - DB container: **~20MB**
