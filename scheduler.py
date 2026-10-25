import datetime as dt
import logging
import threading
import time

import bot_handlers
import config
import db
import tgapi

log = logging.getLogger("scheduler")

TICK_SECONDS = 20


def _at(value: str) -> dt.time:
    hours, minutes = value.split(":")
    return dt.time(int(hours), int(minutes))


def _parity(day: dt.date) -> str:
    return "num" if day.isocalendar()[1] % 2 == 0 else "den"


def _staff(group_id: int) -> list:
    return db.q(
        "SELECT * FROM users WHERE group_id = ? AND is_active = 1 AND role = 'starosta' AND tg_id > 0",
        (group_id,),
    )


def summary_text(group: dict, lesson: dict, date_str: str) -> str:
    stats = bot_handlers_stats(group["id"], date_str, int(lesson["id"]))
    return (
        f"📊 <b>{lesson['subject']}</b> · {lesson['start_time']}–{lesson['end_time']}\n"
        f"{date_str}\n\n"
        f"✅ На паре: {stats['present']}\n"
        f"⏰ Опаздывают: {stats['late']}\n"
        f"❌ Не придут: {stats['absent']}\n"
        f"🤐 Молчат: {stats['silent']}"
    )


def bot_handlers_stats(group_id: int, date_str: str, lesson_id: int) -> dict:
    rows = db.q(
        "SELECT user_id, status FROM marks WHERE group_id = ? AND date = ? AND lesson_id = ?",
        (group_id, date_str, lesson_id),
    )
    by_user = {int(r["user_id"]): r["status"] for r in rows}
    students = db.q(
        "SELECT id FROM users WHERE group_id = ? AND is_active = 1", (group_id,)
    )
    stats = {"present": 0, "late": 0, "absent": 0, "silent": 0}
    for student in students:
        status = by_user.get(int(student["id"]), "silent")
        if status not in stats:
            status = "silent"
        stats[status] += 1
    return stats


def tick() -> None:
    now = dt.datetime.now()
    today = now.date()
    date_str = today.isoformat()

    groups = db.q("SELECT * FROM groups WHERE is_demo = 0")
    for group in groups:
        parity = group["parity_override"] or _parity(today)
        lessons = db.q(
            "SELECT * FROM lessons WHERE group_id = ? AND weekday = ? "
            "AND (parity = 'both' OR parity = ?) ORDER BY start_time",
            (group["id"], today.isoweekday(), parity),
        )
        for lesson in lessons:
            start_dt = dt.datetime.combine(today, _at(lesson["start_time"]))
            end_dt = dt.datetime.combine(today, _at(lesson["end_time"]))
            if end_dt <= start_dt:
                end_dt += dt.timedelta(days=1)
            send_from = start_dt - dt.timedelta(minutes=int(group["poll_minutes_before"]))

            if send_from <= now < end_dt:
                poll = db.q1(
                    "SELECT * FROM polls WHERE lesson_id = ? AND date = ?",
                    (lesson["id"], date_str),
                )
                if not poll:
                    poll_id = bot_handlers.send_poll(group, lesson, date_str)
                    log.info("poll %s created for group %s", poll_id, group["name"])

            close_after = end_dt + dt.timedelta(minutes=int(group["summary_after"]))
            if now >= close_after:
                poll = db.q1(
                    "SELECT * FROM polls WHERE lesson_id = ? AND date = ? AND status = 'open'",
                    (lesson["id"], date_str),
                )
                if not poll:
                    continue
                db.run("UPDATE polls SET status = 'closed' WHERE id = ?", (poll["id"],))
                students = db.q(
                    "SELECT id FROM users WHERE group_id = ? AND is_active = 1", (group["id"],)
                )
                answered = {
                    int(r["user_id"])
                    for r in db.q("SELECT user_id FROM answers WHERE poll_id = ?", (poll["id"],))
                }
                for student in students:
                    if int(student["id"]) in answered:
                        continue
                    db.run(
                        "INSERT INTO marks (group_id, lesson_id, date, user_id, status, source, excused, updated_at) "
                        "VALUES (?, ?, ?, ?, 'silent', 'poll', 0, ?) "
                        "ON CONFLICT(date, lesson_id, user_id) DO UPDATE SET status = 'silent', updated_at = excluded.updated_at",
                        (group["id"], lesson["id"], date_str, student["id"], db.now()),
                    )
                for staff in _staff(group["id"]):
                    try:
                        tgapi.send_message(staff["tg_id"], summary_text(group, lesson, date_str))
                    except tgapi.TelegramError:
                        continue


def loop() -> None:
    log.info("scheduler started")
    while True:
        try:
            tick()
        except Exception:
            log.exception("scheduler tick failed")
        time.sleep(TICK_SECONDS)


def start() -> threading.Thread:
    thread = threading.Thread(target=loop, name="scheduler", daemon=True)
    thread.start()
    return thread
