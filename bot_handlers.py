import datetime as dt
import json
import logging
import threading
import time

import config
import db
import tgapi

log = logging.getLogger("bot")

WELCOME = (
    "Привет! Это бот-помощник старосты: список группы, расписание и учёт посещаемости "
    "— всё в приложении.\n\n"
    "Нажми кнопку ниже, чтобы открыть его. Там можно создать группу (как староста) "
    "или вступить по коду (как студент).\n\n"
    "Перед каждой парой бот будет присылать сюда опрос — просто отвечай на него."
)

ABOUT = (
    "<b>Что умеет этот бот?</b>\n"
    "Я твой личный помощник-староста. Я сам узнаю у студентов, кто будет на паре, "
    "и пришлю тебе аккуратный список. Рутины — ноль."
)

ANSWER_LABELS = {
    "present": "✅ Буду на паре",
    "late": "⏰ Опаздываю",
    "absent": "❌ Не смогу прийти",
}


def app_url(join_code: str = "") -> str:
    url = config.PUBLIC_URL
    if join_code:
        return f"{url}?join={join_code}"
    return url


def app_keyboard(text: str = "🚀 Открыть приложение", join_code: str = "") -> dict:
    return {"inline_keyboard": [[{"text": text, "web_app": {"url": app_url(join_code)}}]]}


def poll_keyboard(poll_id: int) -> dict:
    return {
        "inline_keyboard": [
            [
                {"text": "✅ Буду на паре", "callback_data": f"p{poll_id}:present"},
                {"text": "⏰ Опаздываю", "callback_data": f"p{poll_id}:late"},
            ],
            [{"text": "❌ Не смогу прийти", "callback_data": f"p{poll_id}:absent"}],
        ]
    }


def handle_update(update: dict) -> None:
    if "callback_query" in update:
        return handle_callback(update["callback_query"])
    message = update.get("message")
    if not message:
        return
    text = (message.get("text") or "").strip()
    chat_id = message["chat"]["id"]
    tg_id = message["from"]["id"]
    if not text.startswith("/"):
        return

    command, _, payload = text.partition(" ")
    command = command.split("@")[0].lower()
    payload = payload.strip()

    if command == "/start":
        join_code = ""
        if payload.startswith("join_"):
            join_code = payload[5:].upper()
            group = db.q1("SELECT * FROM groups WHERE code = ?", (join_code,))
            if group:
                tgapi.send_message(
                    chat_id,
                    f"Вступаем в группу <b>{group['name']}</b>.\n"
                    f"Откройте приложение — код <code>{join_code}</code> подставится сам, "
                    f"останется указать ФИО.",
                    reply_markup=app_keyboard("🚀 Вступить в группу", join_code),
                )
                return
            tgapi.send_message(chat_id, "Код приглашения не найден. Проверьте ссылку.")
            return
        tgapi.send_message(
            chat_id,
            WELCOME,
            reply_markup=app_keyboard("🚀 Открыть приложение"),
        )
        return

    if command in ("/app", "/open"):
        tgapi.send_message(chat_id, "Открываю приложение.", reply_markup=app_keyboard())
        return

    if command == "/invite":
        member = db.q1(
            "SELECT * FROM users WHERE tg_id = ? ORDER BY id DESC LIMIT 1", (tg_id,)
        )
        if not member:
            tgapi.send_message(chat_id, "Сначала откройте приложение и создайте группу.")
            return
        group = db.q1("SELECT * FROM groups WHERE id = ?", (member["group_id"],))
        if not group:
            tgapi.send_message(chat_id, "Группа не найдена.")
            return
        if member["role"] != "starosta":
            tgapi.send_message(chat_id, f"Вы в группе <b>{group['name']}</b> как студент.")
            return
        tgapi.send_message(
            chat_id,
            f"Код приглашения группы <b>{group['name']}</b>:\n<code>{group['code']}</code>\n\n"
            f"Ссылка: {app_url(group['code'])}",
            reply_markup=app_keyboard("Открыть приложение"),
        )
        return

    if command == "/help":
        tgapi.send_message(chat_id, ABOUT + "\n\n" + WELCOME, reply_markup=app_keyboard())
        return


def handle_callback(query: dict) -> None:
    data = query.get("data") or ""
    callback_id = query["id"]
    message = query.get("message") or {}
    chat_id = (message.get("chat") or {}).get("id")
    message_id = message.get("message_id")
    tg_id = query["from"]["id"]

    if not data.startswith("p") or ":" not in data:
        tgapi.answer_callback_query(callback_id)
        return

    poll_part, _, status = data[1:].partition(":")
    try:
        poll_id = int(poll_part)
    except ValueError:
        tgapi.answer_callback_query(callback_id)
        return
    if status not in ANSWER_LABELS:
        tgapi.answer_callback_query(callback_id)
        return

    poll = db.q1("SELECT * FROM polls WHERE id = ?", (poll_id,))
    if not poll:
        tgapi.answer_callback_query(callback_id, "Опрос уже закрыт", show_alert=True)
        return

    member = db.q1(
        "SELECT * FROM users WHERE tg_id = ? AND group_id = ?", (tg_id, poll["group_id"])
    )
    if not member:
        tgapi.answer_callback_query(callback_id, "Вы не в этой группе", show_alert=True)
        return

    db.run(
        "INSERT INTO answers (poll_id, user_id, status, at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(poll_id, user_id) DO UPDATE SET status = excluded.status, at = excluded.at",
        (poll_id, member["id"], status, db.now()),
    )
    db.run(
        "INSERT INTO marks (group_id, lesson_id, date, user_id, status, source, excused, updated_at) "
        "VALUES (?, ?, ?, ?, ?, 'poll', 0, ?) "
        "ON CONFLICT(date, lesson_id, user_id) DO UPDATE SET status = excluded.status, "
        "source = 'poll', updated_at = excluded.updated_at",
        (poll["group_id"], poll["lesson_id"], poll["date"], member["id"], status, db.now()),
    )

    lesson = db.q1("SELECT * FROM lessons WHERE id = ?", (poll["lesson_id"],))
    subject = lesson["subject"] if lesson else "Пара"
    window = f"{lesson['start_time']}–{lesson['end_time']}" if lesson else ""

    tgapi.answer_callback_query(callback_id, f"Записано: {ANSWER_LABELS[status]}")
    if chat_id and message_id:
        try:
            tgapi.edit_message_text(
                chat_id,
                message_id,
                f"<b>{subject}</b> · {window}\n"
                f"Ваш ответ: {ANSWER_LABELS[status]}\n"
                f"<i>Передумали — откройте приложение и поправьте отметку.</i>",
            )
        except tgapi.TelegramError:
            pass


def send_poll(group: dict, lesson: dict, date_str: str) -> int | None:
    existing = db.q1(
        "SELECT * FROM polls WHERE lesson_id = ? AND date = ?", (lesson["id"], date_str)
    )
    if existing:
        return int(existing["id"])

    cur = db.run(
        "INSERT INTO polls (group_id, lesson_id, date, status, sent_at) VALUES (?, ?, ?, 'open', ?)",
        (group["id"], lesson["id"], date_str, db.now()),
    )
    poll_id = int(cur.lastrowid)

    students = db.q(
        "SELECT * FROM users WHERE group_id = ? AND is_active = 1 AND role = 'student' AND tg_id > 0",
        (group["id"],),
    )
    text = (
        f"⏰ Через {group['poll_minutes_before']} мин пара\n"
        f"<b>{lesson['subject']}</b> · {lesson['start_time']}–{lesson['end_time']}"
        + (f" · ауд. {lesson['room']}" if lesson["room"] else "")
        + "\n\nБудете?"
    )
    for student in students:
        try:
            tgapi.send_message(student["tg_id"], text, reply_markup=poll_keyboard(poll_id))
        except tgapi.TelegramError:
            continue
    return poll_id


def polling_loop() -> None:
    if not config.BOT_TOKEN:
        log.warning("BOT_TOKEN пуст — бот не запущен, работает только приложение")
        return
    tgapi.set_my_commands()
    tgapi.set_menu_button()
    offset = None
    log.info("bot polling started")
    while True:
        try:
            updates = tgapi.get_updates(offset, timeout=25) or []
        except Exception:
            time.sleep(3)
            continue
        for update in updates:
            offset = update.get("update_id", 0) + 1
            try:
                handle_update(update)
            except Exception:
                log.exception("update failed: %s", json.dumps(update)[:300])


def start() -> threading.Thread:
    thread = threading.Thread(target=polling_loop, name="bot-polling", daemon=True)
    thread.start()
    return thread
