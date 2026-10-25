# Староста бот

Telegram Mini App для старосты учебной группы: список группы, расписание с числителем и знаменателем, автоматические опросы перед парами, журнал посещаемости, прогулы и выгрузка отчёта в Excel. Интерфейс собран по макетам из папки `староста` — тёмная тема, фиолетовый акцент, нижняя навигация, демо-режим.

Проект работает на чистом Python 3.10+ без единой сторонней библиотеки: HTTP-сервер, Bot API, проверка `initData`, SQLite и генератор `.xlsx` — всё на стандартной библиотеке.

## Что внутри

```
starosta-bot/
├── run.py            точка входа: БД, демо-группа, бот, планировщик, HTTP-сервер
├── config.py         настройки из .env
├── db.py             схема SQLite, хелперы, демо-данные (AT-21, 26 студентов, 45 пар)
├── auth.py           проверка подписи Telegram initData (HMAC-SHA256)
├── tgapi.py          клиент Bot API на urllib: сообщения, кнопки, файлы
├── api.py            все JSON-эндпоинты и бизнес-логика
├── server.py         HTTP-сервер: статика Mini App + /api/*
├── bot_handlers.py   /start, приглашения, кнопки опроса
├── scheduler.py      опросы за N минут до пары, сводка старосте после пары
├── xlsx.py           генератор Excel без зависимостей
├── web/              Mini App: index.html, app.js, style.css
└── docs/             скриншоты работающего интерфейса
```

## Запуск локально

```powershell
cd starosta-bot
Copy-Item .env.example .env
python run.py
```

Откройте http://localhost:8080 — приложение поднимется в демо-режиме (`DEV_MODE`), с готовой группой **AT-21**, код `DEMO00`. В демо-группе кнопки нажимаются, но сервер изменения не принимает — ровно как обещает плашка «Можно нажимать — ничего не сохранится».

Чтобы проверить в браузере сразу нужный экран:

- `http://localhost:8080/?onb=0` — пропустить онбординг
- `http://localhost:8080/?onb=0&route=schedule` — расписание (`home`, `students`, `schedule`, `settings`, `reports`, `absences`, `journal`, `announcements`, `materials`, `day`)
- `http://localhost:8080/?join=DEMO00` — подставить код приглашения

## Настройка `.env`

| Переменная | Что задаёт |
|---|---|
| `BOT_TOKEN` | токен от @BotFather |
| `BOT_USERNAME` | username бота без `@` — нужен для ссылок `t.me/...?startapp=join_КОД` |
| `PUBLIC_URL` | публичный **https**-адрес приложения, например `https://starosta.example.ru` |
| `HOST`, `PORT` | адрес и порт HTTP-сервера (по умолчанию `0.0.0.0:8080`) |
| `DB_PATH` | путь к файлу SQLite (по умолчанию `data/starosta.sqlite3`) |
| `SUBSCRIPTION_DAYS` | на сколько дней продлевается подписка кнопкой «Продлить» |
| `DEV_MODE` | `1` — пускать без Telegram, с демо-группой |

Если `BOT_TOKEN` пуст, поднимается только Mini App в демо-режиме — удобно для вёрстки.

## Регистрация в Telegram

1. @BotFather → `/newbot` → получите токен, впишите в `.env`.
2. `/setmenubutton` (или `/mybots` → Bot Settings → Menu Button) → укажите `PUBLIC_URL`. Кнопку меню сервис ставит и сам при старте — `setChatMenuButton` в `tgapi.py`.
3. `/setdomain` не требуется, но домен должен быть на HTTPS с валидным сертификатом: Telegram не откроет Mini App по http.
4. Команды бота (`/start`, `/app`, `/invite`, `/help`) регистрируются автоматически при запуске.

## Деплой на VPS

Нужен домен, указывающий на сервер, и любой reverse-proxy с TLS. Ниже — минимальный вариант с Caddy (сертификат сам).

```bash
# 1. код на сервер
git clone <репозиторий> /opt/starosta && cd /opt/starosta
python3 -m venv .venv && . .venv/bin/activate
pip install --upgrade pip           # сторонних пакетов нет, только venv

# 2. настройки
cp .env.example .env && nano .env   # BOT_TOKEN, BOT_USERNAME, PUBLIC_URL

# 3. пробный запуск
python run.py                       # должно появиться "listening on http://0.0.0.0:8080"

# 4. самопроверка токена и домена (на сервере, где есть доступ к api.telegram.org)
python run.py --check
```

`--check` дергает `getMe`, подставляет `BOT_USERNAME` в `.env`, регистрирует команды и кнопку меню, проверяет базу. Если `getMe` падает по таймауту — сервер не видит `api.telegram.org` (неверный токен даёт `401`, а не таймаут).

Caddy (`/etc/caddy/Caddyfile`):

```
starosta.example.ru {
    reverse_proxy 127.0.0.1:8080
}
```

systemd (`/etc/systemd/system/starosta.service`):

```ini
[Unit]
Description=Starosta Telegram Mini App
After=network.target

[Service]
WorkingDirectory=/opt/starosta
ExecStart=/opt/starosta/.venv/bin/python run.py
Restart=always
User=www-data
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload && systemctl enable --now starosta
curl https://starosta.example.ru/health
```

Дальше в @BotFather указываете тот же `PUBLIC_URL` как Menu Button и открываете бота.

Альтернатива без своего сервера: любой хостинг, где живёт долгоживущий Python-процесс (не «serverless» с холодным стартом — планировщику опросов нужен постоянный процесс).

## Как это работает

**Староста.** Создаёт группу кнопкой «+ Своя группа», получает код приглашения, заполняет расписание. Перед каждой парой планировщик рассылает студентам опрос с тремя кнопками; через `summary_after` минут после конца пары старосте приходит сводка: на паре / опаздывают / не придут / молчат. Молчание засчитывается как пропуск.

**Студент.** Переходит по ссылке приглашения (`t.me/бот?startapp=join_КОД`), код подставляется сам, остаётся указать ФИО. Отвечает на опросы кнопкой в чате, может поправить свой статус в приложении.

**Отчёты.** `Отчёты` → период (неделя / месяц / семестр) → «Прислать отчёт в чат»: бот отправляет `.xlsx` файлом. Строки — студенты, столбцы — пары, в ячейках статусы «был / опоздал / не был / не ответил», справа итоги и уважительные пропуски. Ссылка «Скачать прямо здесь» отдаёт тот же файл напрямую.

**Демо-группа** (`DEMO00`) засеяна при первом запуске: 26 студентов, 6 учебных дней, 45 прошедших пар с отметками, два объявления. Запись в неё заблокирована на сервере.

## Основные эндпоинты

Все запросы — с заголовком `X-Init-Data` (подпись Telegram, проверяется по HMAC). Ответ: `{"ok": true, "data": ...}` или `{"ok": false, "error": "..."}`.

| Метод | Путь | Назначение |
|---|---|---|
| GET | `/api/bootstrap` | пользователь, группа, подписка, роль |
| POST | `/api/group/create` | создать группу |
| POST | `/api/group/join` | вступить по коду |
| PATCH | `/api/group/settings` | опросы, порог, часовой пояс, неделя |
| GET/POST | `/api/schedule` | расписание группы / добавить пару |
| GET | `/api/day?date=` | пары дня и отметки |
| POST | `/api/marks`, `/api/marks/bulk` | поставить отметку / всех «на паре» |
| GET | `/api/absences` | прогулы по предметам |
| GET | `/api/journal?month=` | календарь с отмеченными днями |
| GET/POST | `/api/announcements` | объявления (с уведомлением в чат) |
| GET/POST | `/api/materials` | база знаний (файл в base64, до 20 МБ) |
| POST | `/api/report/send` | отправить Excel в чат |
| GET | `/api/report.xlsx?period=` | скачать Excel напрямую |

## Ограничения текущей версии

- Плавающее расписание хранится флагом: дни недели фиксированные, ручной сбор недели по датам не реализован.
- Подписка продлевается без платёжного шлюза — кнопка «Продлить» просто добавляет 30 дней (подключайте ЮKassa/Telegram Stars в `api.renew_subscription`).
- Материалы базы знаний лежат в `data/uploads` на диске сервера; для нескольких инстансов нужен объектный сторедж.
- Напоминания идут по часовому поясу сервера; поле «Часовой пояс» пока только отображается в интерфейсе.
- SQLite рассчитан на группу-десяток и один процесс; при росте — PostgreSQL.
