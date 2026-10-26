import base64
import datetime as dt
import json
import pathlib
import re

import auth
import config
import db
import tgapi
import xlsx

WEEKDAYS = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
STATUS_WORDS = {"present": "был", "late": "опоздал", "absent": "не был", "silent": "не ответил"}
KINDS = {"Лек", "Сем", "Лаб", "Пр"}


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def today() -> dt.date:
    return dt.date.today()


def parity_of(day: dt.date) -> str:
    return "num" if day.isocalendar()[1] % 2 == 0 else "den"


def parity_label(value: str) -> str:
    return {"num": "Числитель", "den": "Знаменатель", "both": "Каждая неделя"}.get(value, value)


def initials(name: str) -> str:
    parts = [p for p in name.replace("ё", "е").split() if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[1][0]).upper()


class Ctx:
    def __init__(self, tg_user: dict):
        self.tg_id = int(tg_user["id"])
        self.tg_name = " ".join(
            filter(None, [tg_user.get("first_name"), tg_user.get("last_name")])
        ) or tg_user.get("username", "Студент")
        self._membership = None
        self._loaded = False

    def membership(self):
        if self._loaded:
            return self._membership
        self._loaded = True
        row = db.q1(
            "SELECT u.* FROM users u JOIN active_group a ON a.tg_id = u.tg_id AND a.group_id = u.group_id "
            "WHERE u.tg_id = ?",
            (self.tg_id,),
        )
        if not row:
            row = db.q1(
                "SELECT * FROM users WHERE tg_id = ? ORDER BY id DESC LIMIT 1", (self.tg_id,)
            )
        if not row and config.DEV_MODE:
            demo = db.q1("SELECT * FROM groups WHERE code = 'DEMO00'")
            if demo:
                db.run(
                    "INSERT OR IGNORE INTO users (tg_id, group_id, full_name, role, is_active, created_at) "
                    "VALUES (?, ?, ?, 'starosta', 1, ?)",
                    (self.tg_id, demo["id"], self.tg_name, db.now()),
                )
                db.run(
                    "INSERT OR REPLACE INTO active_group (tg_id, group_id) VALUES (?, ?)",
                    (self.tg_id, demo["id"]),
                )
                row = db.q1(
                    "SELECT * FROM users WHERE tg_id = ? AND group_id = ?",
                    (self.tg_id, demo["id"]),
                )
        self._membership = db.to_dict(row)
        return self._membership

    def require_group(self) -> dict:
        member = self.membership()
        if not member:
            raise ApiError("no_group", 409)
        group = db.q1("SELECT * FROM groups WHERE id = ?", (member["group_id"],))
        if not group:
            raise ApiError("no_group", 409)
        return db.to_dict(group)

    def role(self) -> str:
        member = self.membership()
        return member["role"] if member else "student"

    def require_owner(self) -> dict:
        group = self.require_group()
        member = self.membership()
        if group["owner_tg_id"] and group["owner_tg_id"] != self.tg_id and member["role"] != "starosta":
            raise ApiError("Только староста может менять это", 403)
        return group

    def guard_demo(self, group: dict):
        return None

    def user_row(self) -> dict:
        member = self.membership()
        if not member:
            raise ApiError("no_group", 409)
        return member


def lesson_stats(group_id: int, date_str: str, lesson_id: int) -> dict:
    rows = db.q(
        "SELECT m.user_id, m.status FROM marks m WHERE m.group_id = ? AND m.date = ? AND m.lesson_id = ?",
        (group_id, date_str, lesson_id),
    )
    marks = {int(r["user_id"]): r["status"] for r in rows}
    students = db.q(
        "SELECT id FROM users WHERE group_id = ? AND is_active = 1", (group_id,)
    )
    present = late = absent = other = 0
    for student in students:
        status = marks.get(int(student["id"]), "silent")
        if status == "present":
            present += 1
        elif status == "late":
            late += 1
        elif status == "absent":
            absent += 1
        else:
            other += 1
    return {
        "present": present,
        "late": late,
        "absent": absent,
        "silent": other,
        "total": len(students),
        "marked": present + late + absent,
    }


def group_lessons(group_id: int) -> list:
    rows = db.q(
        "SELECT * FROM lessons WHERE group_id = ? ORDER BY weekday, start_time, id", (group_id,)
    )
    return db.all_dicts(rows)


def lessons_for_date(group_id: int, day: dt.date, parity: str | None = None) -> list:
    week_parity = parity or parity_of(day)
    rows = db.q(
        "SELECT * FROM lessons WHERE group_id = ? AND weekday = ? "
        "AND (parity = 'both' OR parity = ?) ORDER BY start_time, id",
        (group_id, day.isoweekday(), week_parity),
    )
    return db.all_dicts(rows)


def demark_date(value: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ApiError("Некорректная дата")


def period_range(group: dict, period: str) -> tuple[dt.date, dt.date]:
    now_date = today()
    if period == "week":
        start = now_date - dt.timedelta(days=now_date.weekday())
        return start, start + dt.timedelta(days=6)
    if period == "month":
        start = now_date.replace(day=1)
        next_month = (start + dt.timedelta(days=32)).replace(day=1)
        return start, next_month - dt.timedelta(days=1)
    semester = db.q1("SELECT * FROM semesters WHERE group_id = ?", (group["id"],))
    if semester:
        return demark_date(semester["starts"]), demark_date(semester["ends"])
    return now_date.replace(month=1, day=1), now_date


def period_lessons(group_id: int, start: dt.date, stop: dt.date) -> list:
    result = []
    cursor = start
    lessons = group_lessons(group_id)
    while cursor <= stop:
        day_parity = parity_of(cursor)
        for lesson in lessons:
            if int(lesson["weekday"]) != cursor.isoweekday():
                continue
            if lesson["parity"] != "both" and lesson["parity"] != day_parity:
                continue
            result.append((cursor, lesson))
        cursor += dt.timedelta(days=1)
    return result


def build_report(group: dict, period: str) -> tuple[bytes, str]:
    start, stop = period_range(group, period)
    pairs = period_lessons(group["id"], start, stop)
    students = db.q(
        "SELECT * FROM users WHERE group_id = ? AND is_active = 1 ORDER BY full_name",
        (group["id"],),
    )
    marks = db.q(
        "SELECT date, lesson_id, user_id, status, excused FROM marks "
        "WHERE group_id = ? AND date >= ? AND date <= ?",
        (group["id"], start.isoformat(), stop.isoformat()),
    )
    index = {}
    for row in marks:
        index[(row["date"], lesson_id_of(row), int(row["user_id"]))] = row

    header_top = [
        group["name"],
        f"{period_label(period)}: {start.strftime('%d.%m.%Y')} — {stop.strftime('%d.%m.%Y')}",
        group["university"],
    ]
    header = ["№", "Студент"] + [
        f"{d.strftime('%d.%m')} {lesson['subject'].split()[0]}" for d, lesson in pairs
    ] + ["Был", "Опоздал", "Не был", "Не ответил", "Пропуски", "Уваж."]

    rows = [header_top, header]
    totals = {"present": 0, "late": 0, "absent": 0, "silent": 0}
    for number, student in enumerate(students, start=1):
        counts = {"present": 0, "late": 0, "absent": 0, "silent": 0}
        excused = 0
        cells = []
        for date_value, lesson in pairs:
            row = index.get((date_value.isoformat(), int(lesson["id"]), int(student["id"])))
            status = row["status"] if row else "silent"
            if status in counts:
                counts[status] += 1
            if row and row["excused"]:
                excused += 1
            cells.append(STATUS_WORDS.get(status, "—"))
        misses = counts["absent"] + counts["silent"]
        rows.append(
            [number, student["full_name"]]
            + cells
            + [counts["present"], counts["late"], counts["absent"], counts["silent"], misses, excused]
        )
        for key in totals:
            totals[key] += counts[key]

    widths = [5, 32] + [9] * len(pairs) + [8, 9, 8, 11, 10, 7]
    content = xlsx.build(rows, sheet_name=period_label(period), widths=widths, header_rows=1)
    filename = f"Посещаемость_{group['name']}_{period_label(period).lower()}_{today().isoformat()}.xlsx"
    return content, filename


def lesson_id_of(row) -> int:
    return int(row["lesson_id"])


def period_label(period: str) -> str:
    return {"week": "Неделя", "month": "Месяц", "semester": "Семестр"}.get(period, "Период")


def group_payload(group: dict) -> dict:
    subscription_until = group.get("subscription_until") or ""
    days_left = 0
    if subscription_until:
        try:
            days_left = (dt.date.fromisoformat(subscription_until) - today()).days
        except ValueError:
            days_left = 0
    invite_code = group["code"]
    link = f"https://t.me/{config.BOT_USERNAME}?startapp=join_{invite_code}"
    if not config.BOT_USERNAME:
        link = f"{config.PUBLIC_URL}/?startapp=join_{invite_code}"
    return {
        "id": group["id"],
        "name": group["name"],
        "university": group["university"],
        "code": invite_code,
        "initials": initials(group["name"]),
        "is_demo": bool(group["is_demo"]),
        "poll_minutes_before": group["poll_minutes_before"],
        "summary_after": group["summary_after"],
        "absence_threshold": group["absence_threshold"],
        "tz": group["tz"],
        "floating_schedule": bool(group["floating_schedule"]),
        "parity_override": group["parity_override"],
        "subscription_until": subscription_until,
        "subscription_days": days_left,
        "invite_link": link,
        "invite_text": (
            f"👋 Ребята, подключил группу к «Помощнику старосты». "
            f"Открывайте ссылку и вступайте: {link}\nКод группы: {invite_code}"
        ),
    }


def bootstrap(ctx: Ctx) -> dict:
    member = ctx.membership()
    if not member:
        return {"has_group": False, "user": {"tg_id": ctx.tg_id, "name": ctx.tg_name}, "demo": config.DEV_MODE}
    group = db.q1("SELECT * FROM groups WHERE id = ?", (member["group_id"],))
    if not group:
        return {"has_group": False, "user": {"tg_id": ctx.tg_id, "name": ctx.tg_name}, "demo": config.DEV_MODE}
    group = db.to_dict(group)
    groups = db.q(
        "SELECT g.id, g.name FROM groups g JOIN users u ON u.group_id = g.id WHERE u.tg_id = ?",
        (ctx.tg_id,),
    )
    return {
        "has_group": True,
        "demo": config.DEV_MODE,
        "user": {
            "tg_id": ctx.tg_id,
            "name": member["full_name"] or ctx.tg_name,
            "role": member["role"],
            "id": member["id"],
            "is_self_added": bool(member["role"] == "starosta"),
        },
        "group": group_payload(group),
        "groups": db.all_dicts(groups),
        "is_owner": group["owner_tg_id"] in (0, ctx.tg_id),
    }


def home(ctx: Ctx) -> dict:
    group = ctx.require_group()
    now_date = today()
    week_parity = group["parity_override"] or parity_of(now_date)
    day_lessons = lessons_for_date(group["id"], now_date, week_parity)
    current = None
    if day_lessons:
        now_time = dt.datetime.now().strftime("%H:%M")
        for lesson in day_lessons:
            if lesson["start_time"] <= now_time <= lesson["end_time"]:
                current = lesson
                break
        if current is None:
            upcoming = [l for l in day_lessons if l["start_time"] > now_time]
            current = upcoming[0] if upcoming else day_lessons[-1]
        payload_lesson = dict(current)
        payload_lesson["stats"] = lesson_stats(group["id"], now_date.isoformat(), int(current["id"]))
        current = payload_lesson
    announcements = db.q(
        "SELECT * FROM announcements WHERE group_id = ? ORDER BY pinned DESC, created_at DESC LIMIT 3",
        (group["id"],),
    )
    return {
        "date": now_date.isoformat(),
        "weekday": WEEKDAYS[now_date.weekday()],
        "parity": week_parity,
        "parity_label": parity_label(week_parity),
        "lesson": current,
        "lessons": day_lessons,
        "announcements": db.all_dicts(announcements),
        "students": db.q1(
            "SELECT COUNT(*) AS c FROM users WHERE group_id = ? AND is_active = 1", (group["id"],)
        )["c"],
    }


def day_view(ctx: Ctx, date_str: str) -> dict:
    group = ctx.require_group()
    day = demark_date(date_str)
    week_parity = group["parity_override"] or parity_of(day)
    lessons = lessons_for_date(group["id"], day, week_parity)
    students = db.q(
        "SELECT id, full_name, role FROM users WHERE group_id = ? AND is_active = 1 ORDER BY full_name",
        (group["id"],),
    )
    marks_rows = db.q(
        "SELECT lesson_id, user_id, status, excused FROM marks WHERE group_id = ? AND date = ?",
        (group["id"], date_str),
    )
    marks = {}
    for row in marks_rows:
        marks.setdefault(str(row["lesson_id"]), {})[str(row["user_id"])] = {
            "status": row["status"],
            "excused": bool(row["excused"]),
        }
    out_lessons = []
    for lesson in lessons:
        item = dict(lesson)
        item["stats"] = lesson_stats(group["id"], date_str, int(lesson["id"]))
        out_lessons.append(item)
    return {
        "date": date_str,
        "weekday": WEEKDAYS[day.weekday()],
        "parity": week_parity,
        "parity_label": parity_label(week_parity),
        "is_today": day == today(),
        "students": [{"id": s["id"], "name": s["full_name"], "initials": initials(s["full_name"]), "role": s["role"]} for s in students],
        "lessons": out_lessons,
        "marks": marks,
    }


def students_view(ctx: Ctx) -> dict:
    group = ctx.require_group()
    rows = db.q(
        "SELECT * FROM users WHERE group_id = ? ORDER BY is_active DESC, full_name", (group["id"],)
    )
    items = []
    for row in rows:
        items.append(
            {
                "id": row["id"],
                "name": row["full_name"] or "Без имени",
                "initials": initials(row["full_name"] or "?"),
                "role": row["role"],
                "is_active": bool(row["is_active"]),
                "linked": row["tg_id"] > 0,
            }
        )
    active = sum(1 for i in items if i["is_active"])
    return {
        "count": len(items),
        "active": active,
        "has_self": any(i["role"] == "starosta" and i["is_active"] for i in items),
        "list": [i for i in items if i["is_active"]],
        "inactive": [i for i in items if not i["is_active"]],
    }


def schedule_view(ctx: Ctx) -> dict:
    group = ctx.require_group()
    semester = db.q1("SELECT * FROM semesters WHERE group_id = ?", (group["id"],))
    current_parity = group["parity_override"] or parity_of(today())
    lessons = group_lessons(group["id"])
    days = []
    for weekday in range(1, 8):
        items = [l for l in lessons if int(l["weekday"]) == weekday]
        if not items:
            continue
        days.append(
            {
                "weekday": weekday,
                "title": WEEKDAYS[weekday - 1],
                "lessons": items,
            }
        )
    return {
        "semester": db.to_dict(semester),
        "parity": current_parity,
        "parity_label": parity_label(current_parity),
        "days": days,
        "floating": bool(group["floating_schedule"]),
    }


def journal_view(ctx: Ctx, month: str) -> dict:
    group = ctx.require_group()
    try:
        year, mon = [int(p) for p in month.split("-")]
        first = dt.date(year, mon, 1)
    except (ValueError, AttributeError):
        first = today().replace(day=1)
    next_month = (first + dt.timedelta(days=32)).replace(day=1)
    last = next_month - dt.timedelta(days=1)
    rows = db.q(
        "SELECT date, COUNT(*) AS c FROM marks WHERE group_id = ? AND date >= ? AND date <= ? GROUP BY date",
        (group["id"], first.isoformat(), last.isoformat()),
    )
    marked = {r["date"]: r["c"] for r in rows}
    return {
        "month": first.strftime("%Y-%m"),
        "title": first.strftime("%B %Y"),
        "month_label": f"{['Январь','Февраль','Март','Апрель','Май','Июнь','Июль','Август','Сентябрь','Октябрь','Ноябрь','Декабрь'][first.month - 1]} {first.year}",
        "first_weekday": first.weekday() + 1,
        "days_in_month": last.day,
        "marked": marked,
        "today": today().isoformat(),
    }


def absences_view(ctx: Ctx) -> dict:
    group = ctx.require_group()
    students = db.q(
        "SELECT id, full_name FROM users WHERE group_id = ? AND is_active = 1 ORDER BY full_name",
        (group["id"],),
    )
    total_lessons = db.q1(
        "SELECT COUNT(DISTINCT date || '-' || lesson_id) AS c FROM marks WHERE group_id = ?",
        (group["id"],),
    )["c"]
    rows = db.q(
        "SELECT m.user_id, m.status, m.excused, l.subject FROM marks m "
        "JOIN lessons l ON l.id = m.lesson_id WHERE m.group_id = ?",
        (group["id"],),
    )
    agg = {}
    for row in rows:
        item = agg.setdefault(
            int(row["user_id"]),
            {
                "present": 0,
                "late": 0,
                "absent": 0,
                "silent": 0,
                "excused": 0,
                "subjects": {},
            },
        )
        status = row["status"] if row["status"] in ("present", "late", "absent", "silent") else "silent"
        item[status] += 1
        item["excused"] += int(row["excused"] or 0)
        if status in ("absent", "silent"):
            subject = row["subject"] or "—"
            item["subjects"][subject] = item["subjects"].get(subject, 0) + 1

    result = []
    threshold = int(group["absence_threshold"])
    for student in students:
        stat = agg.get(
            int(student["id"]),
            {"present": 0, "late": 0, "absent": 0, "silent": 0, "excused": 0, "subjects": {}},
        )
        worst_subject = ""
        worst = 0
        for subject, count in stat["subjects"].items():
            if count > worst:
                worst = count
                worst_subject = subject
        result.append(
            {
                "id": student["id"],
                "name": student["full_name"],
                "initials": initials(student["full_name"]),
                "absences": worst,
                "total_absences": stat["absent"] + stat["silent"],
                "subject": worst_subject,
                "excused": stat["excused"],
                "present": stat["present"] + stat["late"],
                "total": total_lessons,
                "risk": worst >= threshold,
            }
        )
    result.sort(key=lambda x: (-x["absences"], -x["total_absences"], x["name"]))
    return {
        "threshold": threshold,
        "total_lessons": total_lessons,
        "risk": sum(1 for r in result if r["risk"]),
        "students": result,
    }


def announcements_view(ctx: Ctx) -> dict:
    group = ctx.require_group()
    rows = db.q(
        "SELECT * FROM announcements WHERE group_id = ? ORDER BY pinned DESC, created_at DESC",
        (group["id"],),
    )
    items = []
    for row in rows:
        created = row["created_at"]
        stamp = ""
        try:
            parsed = dt.datetime.fromisoformat(created)
            stamp = parsed.strftime("%d.%m, %H:%M")
        except ValueError:
            stamp = created
        items.append(
            {
                "id": row["id"],
                "title": row["title"],
                "body": row["body"],
                "pinned": bool(row["pinned"]),
                "created_at": stamp,
            }
        )
    return {"list": items}


def materials_view(ctx: Ctx) -> dict:
    group = ctx.require_group()
    rows = db.q(
        "SELECT * FROM materials WHERE group_id = ? ORDER BY created_at DESC", (group["id"],)
    )
    items = []
    for row in rows:
        items.append(
            {
                "id": row["id"],
                "title": row["title"],
                "subject": row["subject"],
                "size": row["size"],
                "created_at": row["created_at"][:10],
            }
        )
    return {"list": items}


def my_day(ctx: Ctx) -> dict:
    group = ctx.require_group()
    member = ctx.user_row()
    now_date = today()
    week_parity = group["parity_override"] or parity_of(now_date)
    lessons = lessons_for_date(group["id"], now_date, week_parity)
    rows = db.q(
        "SELECT lesson_id, status FROM marks WHERE group_id = ? AND date = ? AND user_id = ?",
        (group["id"], now_date.isoformat(), member["id"]),
    )
    my_marks = {str(r["lesson_id"]): r["status"] for r in rows}
    items = []
    for lesson in lessons:
        item = dict(lesson)
        item["my_status"] = my_marks.get(str(lesson["id"]))
        items.append(item)
    return {
        "date": now_date.isoformat(),
        "weekday": WEEKDAYS[now_date.weekday()],
        "parity_label": parity_label(week_parity),
        "name": member["full_name"] or ctx.tg_name,
        "lessons": items,
    }


def my_stats(ctx: Ctx) -> dict:
    group = ctx.require_group()
    member = ctx.user_row()
    rows = db.q(
        "SELECT m.date, m.status, m.excused, l.subject, l.start_time "
        "FROM marks m JOIN lessons l ON l.id = m.lesson_id "
        "WHERE m.group_id = ? AND m.user_id = ? ORDER BY m.date DESC, l.start_time",
        (group["id"], member["id"]),
    )
    totals = {"present": 0, "late": 0, "absent": 0, "silent": 0}
    excused_total = 0
    subjects = {}
    for row in rows:
        status = row["status"] if row["status"] in totals else "silent"
        totals[status] += 1
        if row["excused"]:
            excused_total += 1
        subject = row["subject"] or "Без предмета"
        item = subjects.get(subject)
        if item is None:
            item = {
                "subject": subject,
                "total": 0,
                "present": 0,
                "late": 0,
                "absent": 0,
                "silent": 0,
                "details": [],
            }
            subjects[subject] = item
        item["total"] += 1
        item[status] += 1
        if status != "present" or row["excused"]:
            item["details"].append(
                {
                    "date": row["date"],
                    "time": row["start_time"],
                    "status": status,
                    "excused": bool(row["excused"]),
                }
            )

    subject_list = []
    for item in subjects.values():
        attended = item["present"] + item["late"]
        misses = item["absent"] + item["silent"]
        item["attended"] = attended
        item["misses"] = misses
        item["percent"] = round(attended * 100 / item["total"]) if item["total"] else 0
        subject_list.append(item)
    subject_list.sort(key=lambda s: (-s["misses"], s["subject"]))

    attended_total = totals["present"] + totals["late"]
    total = sum(totals.values())
    return {
        "name": member["full_name"] or ctx.tg_name,
        "total": total,
        "attended": attended_total,
        "misses": totals["absent"] + totals["silent"],
        "without_reason": totals["absent"] + totals["silent"] - excused_total,
        "excused": excused_total,
        "percent": round(attended_total * 100 / total) if total else 0,
        "subjects": subject_list,
    }


def answer_all_today(ctx: Ctx) -> dict:
    group = ctx.require_group()
    ctx.guard_demo(group)
    member = ctx.user_row()
    now_date = today()
    parity = group["parity_override"] or parity_of(now_date)
    lessons = lessons_for_date(group["id"], now_date, parity)
    for lesson in lessons:
        db.run(
            "INSERT INTO marks (group_id, lesson_id, date, user_id, status, source, excused, updated_at) "
            "VALUES (?, ?, ?, ?, 'present', 'self', 0, ?) "
            "ON CONFLICT(date, lesson_id, user_id) DO UPDATE SET status = 'present', updated_at = excluded.updated_at",
            (group["id"], lesson["id"], now_date.isoformat(), member["id"], db.now()),
        )
    return my_day(ctx)


def parse_body(raw: bytes) -> dict:
    if not raw:
        return {}
    try:
        data = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ApiError("Некорректный JSON")
    if not isinstance(data, dict):
        raise ApiError("Ожидался объект JSON")
    return data


def _require(value, field: str):
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ApiError(f"Заполните поле «{field}»")
    return value.strip() if isinstance(value, str) else value


def create_group(ctx: Ctx, body: dict) -> dict:
    name = _require(body.get("name"), "Название группы")
    university = (body.get("university") or "").strip()
    full_name = (body.get("full_name") or ctx.tg_name).strip()
    code = db.unique_code()
    created = db.now()
    cur = db.run(
        "INSERT INTO groups (code, name, university, owner_tg_id, subscription_until, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            code,
            name[:60],
            university[:120],
            ctx.tg_id,
            (today() + dt.timedelta(days=config.SUBSCRIPTION_DAYS)).isoformat(),
            created,
        ),
    )
    gid = int(cur.lastrowid)
    first_day = today().replace(month=9, day=1) if today().month >= 9 else today().replace(month=2, day=7)
    db.run(
        "INSERT INTO semesters (group_id, starts, ends) VALUES (?, ?, ?)",
        (gid, first_day.isoformat(), (first_day + dt.timedelta(days=120)).isoformat()),
    )
    db.run(
        "INSERT INTO users (tg_id, group_id, full_name, role, is_active, created_at) VALUES (?, ?, ?, 'starosta', 1, ?)",
        (ctx.tg_id, gid, full_name, created),
    )
    db.run("INSERT OR REPLACE INTO active_group (tg_id, group_id) VALUES (?, ?)", (ctx.tg_id, gid))
    ctx._loaded = False
    ctx._membership = None
    return bootstrap(ctx)


def join_group(ctx: Ctx, body: dict) -> dict:
    code = (body.get("code") or "").strip().upper()
    full_name = (body.get("full_name") or "").strip()
    if not code:
        raise ApiError("Введите код группы")
    if not full_name:
        raise ApiError("Укажите ФИО")
    group = db.q1("SELECT * FROM groups WHERE code = ?", (code,))
    if not group:
        raise ApiError("Группа с таким кодом не найдена", 404)
    existing = db.q1(
        "SELECT * FROM users WHERE tg_id = ? AND group_id = ?", (ctx.tg_id, group["id"])
    )
    if existing:
        db.run(
            "UPDATE users SET full_name = ?, is_active = 1 WHERE id = ?",
            (full_name[:120], existing["id"]),
        )
    else:
        db.run(
            "INSERT INTO users (tg_id, group_id, full_name, role, is_active, created_at) "
            "VALUES (?, ?, ?, 'student', 1, ?)",
            (ctx.tg_id, group["id"], full_name[:120], db.now()),
        )
    db.run("INSERT OR REPLACE INTO active_group (tg_id, group_id) VALUES (?, ?)", (ctx.tg_id, group["id"]))
    ctx._loaded = False
    ctx._membership = None
    return bootstrap(ctx)


def switch_group(ctx: Ctx, body: dict) -> dict:
    group_id = int(body.get("group_id") or 0)
    member = db.q1("SELECT * FROM users WHERE tg_id = ? AND group_id = ?", (ctx.tg_id, group_id))
    if not member:
        raise ApiError("Нет доступа к группе", 403)
    db.run("INSERT OR REPLACE INTO active_group (tg_id, group_id) VALUES (?, ?)", (ctx.tg_id, group_id))
    ctx._loaded = False
    ctx._membership = None
    return bootstrap(ctx)


def update_settings(ctx: Ctx, body: dict) -> dict:
    group = ctx.require_owner()
    ctx.guard_demo(group)
    fields = []
    params = []
    for key, limit in (
        ("poll_minutes_before", 240),
        ("summary_after", 240),
        ("absence_threshold", 99),
    ):
        if key in body and body[key] is not None:
            try:
                value = max(0, min(limit, int(body[key])))
            except (TypeError, ValueError):
                raise ApiError("Введите число")
            fields.append(f"{key} = ?")
            params.append(value)
    if "tz" in body and body["tz"]:
        fields.append("tz = ?")
        params.append(str(body["tz"])[:60])
    if "floating_schedule" in body:
        fields.append("floating_schedule = ?")
        params.append(1 if body["floating_schedule"] else 0)
    if "name" in body and body["name"]:
        fields.append("name = ?")
        params.append(str(body["name"])[:60])
    if "university" in body:
        fields.append("university = ?")
        params.append(str(body["university"])[:120])
    if "parity_override" in body:
        value = body["parity_override"]
        if value not in ("", "num", "den"):
            raise ApiError("Некорректная неделя")
        fields.append("parity_override = ?")
        params.append(value)
    if not fields:
        return bootstrap(ctx)
    params.append(group["id"])
    db.run(f"UPDATE groups SET {', '.join(fields)} WHERE id = ?", tuple(params))
    return bootstrap(ctx)


def add_lesson(ctx: Ctx, body: dict) -> dict:
    group = ctx.require_owner()
    ctx.guard_demo(group)
    subject = _require(body.get("subject"), "Предмет")
    start_time = _require(body.get("start_time"), "Начало")
    end_time = _require(body.get("end_time"), "Конец")
    weekday = int(body.get("weekday") or 1)
    parity = body.get("parity") or "both"
    if parity not in ("both", "num", "den"):
        raise ApiError("Некорректная неделя")
    kind = body.get("kind") or "Лек"
    if kind not in KINDS:
        kind = "Лек"
    db.run(
        "INSERT INTO lessons (group_id, weekday, parity, start_time, end_time, subject, kind, room, teacher, has_hw, position) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            group["id"],
            weekday,
            parity,
            start_time[:5],
            end_time[:5],
            subject[:120],
            kind,
            (body.get("room") or "")[:32],
            (body.get("teacher") or "")[:60],
            1 if body.get("has_hw") else 0,
            0,
        ),
    )
    return schedule_view(ctx)


def update_lesson(ctx: Ctx, lesson_id: int, body: dict) -> dict:
    group = ctx.require_owner()
    ctx.guard_demo(group)
    lesson = db.q1("SELECT * FROM lessons WHERE id = ? AND group_id = ?", (lesson_id, group["id"]))
    if not lesson:
        raise ApiError("Пара не найдена", 404)
    fields = []
    params = []
    for key in ("start_time", "end_time", "subject", "kind", "room", "teacher", "parity"):
        if key in body and body[key] not in (None, ""):
            fields.append(f"{key} = ?")
            params.append(str(body[key])[:120])
    if "has_hw" in body:
        fields.append("has_hw = ?")
        params.append(1 if body["has_hw"] else 0)
    if fields:
        params.append(lesson_id)
        db.run(f"UPDATE lessons SET {', '.join(fields)} WHERE id = ?", tuple(params))
    return schedule_view(ctx)


def delete_lesson(ctx: Ctx, lesson_id: int) -> dict:
    group = ctx.require_owner()
    ctx.guard_demo(group)
    db.run("DELETE FROM lessons WHERE id = ? AND group_id = ?", (lesson_id, group["id"]))
    return schedule_view(ctx)


def set_mark(ctx: Ctx, body: dict) -> dict:
    group = ctx.require_owner()
    ctx.guard_demo(group)
    date_str = _require(body.get("date"), "Дата")
    lesson_id = int(body.get("lesson_id") or 0)
    student_id = int(body.get("user_id") or 0)
    status = body.get("status")
    if status not in ("present", "late", "absent", "silent", ""):
        raise ApiError("Некорректный статус")
    if not lesson_id or not student_id:
        raise ApiError("Не указана пара или студент")
    if status == "":
        db.run(
            "DELETE FROM marks WHERE date = ? AND lesson_id = ? AND user_id = ?",
            (date_str, lesson_id, student_id),
        )
    else:
        db.run(
            "INSERT INTO marks (group_id, lesson_id, date, user_id, status, source, excused, updated_at) "
            "VALUES (?, ?, ?, ?, ?, 'manual', 0, ?) "
            "ON CONFLICT(date, lesson_id, user_id) DO UPDATE SET status = excluded.status, "
            "source = 'manual', updated_at = excluded.updated_at",
            (group["id"], lesson_id, date_str, student_id, status, db.now()),
        )
    if body.get("excused") is not None:
        db.run(
            "UPDATE marks SET excused = ? WHERE date = ? AND lesson_id = ? AND user_id = ?",
            (1 if body["excused"] else 0, date_str, lesson_id, student_id),
        )
    return day_view(ctx, date_str)


def bulk_mark(ctx: Ctx, body: dict) -> dict:
    group = ctx.require_owner()
    ctx.guard_demo(group)
    date_str = _require(body.get("date"), "Дата")
    lesson_id = int(body.get("lesson_id") or 0)
    status = body.get("status") or "present"
    students = db.q("SELECT id FROM users WHERE group_id = ? AND is_active = 1", (group["id"],))
    for student in students:
        db.run(
            "INSERT INTO marks (group_id, lesson_id, date, user_id, status, source, excused, updated_at) "
            "VALUES (?, ?, ?, ?, ?, 'manual', 0, ?) "
            "ON CONFLICT(date, lesson_id, user_id) DO UPDATE SET status = excluded.status, updated_at = excluded.updated_at",
            (group["id"], lesson_id, date_str, student["id"], status, db.now()),
        )
    return day_view(ctx, date_str)


def answer_self(ctx: Ctx, body: dict) -> dict:
    group = ctx.require_group()
    ctx.guard_demo(group)
    member = ctx.user_row()
    date_str = _require(body.get("date"), "Дата")
    lesson_id = int(body.get("lesson_id") or 0)
    status = body.get("status")
    if status not in ("present", "late", "absent"):
        raise ApiError("Некорректный статус")
    db.run(
        "INSERT INTO marks (group_id, lesson_id, date, user_id, status, source, excused, updated_at) "
        "VALUES (?, ?, ?, ?, ?, 'self', 0, ?) "
        "ON CONFLICT(date, lesson_id, user_id) DO UPDATE SET status = excluded.status, updated_at = excluded.updated_at",
        (group["id"], lesson_id, date_str, member["id"], status, db.now()),
    )
    return my_day(ctx)


def add_self(ctx: Ctx) -> dict:
    group = ctx.require_group()
    ctx.guard_demo(group)
    member = ctx.user_row()
    db.run("UPDATE users SET role = 'starosta' WHERE id = ?", (member["id"],))
    ctx._loaded = False
    ctx._membership = None
    return students_view(ctx)


def save_announcement(ctx: Ctx, body: dict) -> dict:
    group = ctx.require_owner()
    ctx.guard_demo(group)
    title = _require(body.get("title"), "Заголовок")
    text = _require(body.get("body"), "Текст")
    db.run(
        "INSERT INTO announcements (group_id, title, body, pinned, created_at) VALUES (?, ?, ?, ?, ?)",
        (group["id"], title[:120], text[:2000], 1 if body.get("pinned") else 0, db.now()),
    )
    notify_group(group, f"📌 <b>{title}</b>\n{text}")
    return announcements_view(ctx)


def notify_group(group: dict, text: str) -> None:
    rows = db.q(
        "SELECT tg_id FROM users WHERE group_id = ? AND is_active = 1 AND tg_id > 0",
        (group["id"],),
    )
    for row in rows:
        try:
            tgapi.send_message(row["tg_id"], text)
        except Exception:
            continue


def update_announcement(ctx: Ctx, item_id: int, body: dict) -> dict:
    group = ctx.require_owner()
    ctx.guard_demo(group)
    if "pinned" in body:
        db.run(
            "UPDATE announcements SET pinned = ? WHERE id = ? AND group_id = ?",
            (1 if body["pinned"] else 0, item_id, group["id"]),
        )
    return announcements_view(ctx)


def delete_announcement(ctx: Ctx, item_id: int) -> dict:
    group = ctx.require_owner()
    ctx.guard_demo(group)
    db.run("DELETE FROM announcements WHERE id = ? AND group_id = ?", (item_id, group["id"]))
    return announcements_view(ctx)


def save_material(ctx: Ctx, body: dict) -> dict:
    group = ctx.require_owner()
    ctx.guard_demo(group)
    title = _require(body.get("title"), "Название")
    payload = body.get("content") or ""
    if not payload:
        raise ApiError("Файл не приложен")
    try:
        raw = base64.b64decode(payload.split(",")[-1])
    except Exception:
        raise ApiError("Не удалось прочитать файл")
    if len(raw) > 20 * 1024 * 1024:
        raise ApiError("Файл больше 20 МБ")
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^\w.\- ]", "_", body.get("filename") or "material.bin")
    path = config.UPLOAD_DIR / f"{db.now().replace(':', '-')}_{safe_name}"
    path.write_bytes(raw)
    db.run(
        "INSERT INTO materials (group_id, subject, title, file_path, size, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (
            group["id"],
            (body.get("subject") or "")[:80],
            title[:160],
            str(path),
            len(raw),
            db.now(),
        ),
    )
    notify_group(group, f"📚 Новый материал: <b>{title}</b>\nОткройте «База знаний» в приложении.")
    return materials_view(ctx)


def delete_material(ctx: Ctx, item_id: int) -> dict:
    group = ctx.require_owner()
    ctx.guard_demo(group)
    row = db.q1("SELECT * FROM materials WHERE id = ? AND group_id = ?", (item_id, group["id"]))
    if row and row["file_path"]:
        try:
            pathlib.Path(row["file_path"]).unlink(missing_ok=True)
        except OSError:
            pass
    db.run("DELETE FROM materials WHERE id = ? AND group_id = ?", (item_id, group["id"]))
    return materials_view(ctx)


def invite_view(ctx: Ctx) -> dict:
    group = ctx.require_owner()
    return group_payload(group)


def reissue_invite(ctx: Ctx) -> dict:
    group = ctx.require_owner()
    ctx.guard_demo(group)
    db.run("UPDATE groups SET code = ? WHERE id = ?", (db.unique_code(), group["id"]))
    return group_payload(db.to_dict(db.q1("SELECT * FROM groups WHERE id = ?", (group["id"],))))


def renew_subscription(ctx: Ctx) -> dict:
    group = ctx.require_owner()
    ctx.guard_demo(group)
    base = today()
    if group["subscription_until"]:
        try:
            base = max(base, dt.date.fromisoformat(group["subscription_until"]))
        except ValueError:
            pass
    db.run(
        "UPDATE groups SET subscription_until = ? WHERE id = ?",
        ((base + dt.timedelta(days=config.SUBSCRIPTION_DAYS)).isoformat(), group["id"]),
    )
    return bootstrap(ctx)


def send_report(ctx: Ctx, period: str) -> dict:
    group = ctx.require_group()
    content, filename = build_report(group, period)
    if config.BOT_TOKEN and ctx.tg_id > 0:
        try:
            tgapi.send_document(
                ctx.tg_id,
                filename,
                content,
                caption=f"Отчёт по посещаемости · {group['name']} · {period_label(period).lower()}",
            )
            return {"sent": True, "filename": filename}
        except tgapi.TelegramError as exc:
            raise ApiError(f"Не удалось отправить файл: {exc}", 502)
    return {"sent": False, "filename": filename}


def route(ctx: Ctx, method: str, path: str, query: dict, body: dict, raw: bytes):
    if path == "/api/bootstrap" and method == "GET":
        return bootstrap(ctx)
    if path == "/api/group/create" and method == "POST":
        return create_group(ctx, body)
    if path == "/api/group/join" and method == "POST":
        return join_group(ctx, body)
    if path == "/api/group/switch" and method == "POST":
        return switch_group(ctx, body)
    if path == "/api/group/settings" and method == "PATCH":
        return update_settings(ctx, body)
    if path == "/api/group/semester" and method == "PATCH":
        group = ctx.require_owner()
        ctx.guard_demo(group)
        starts = _require(body.get("starts"), "Начало семестра")
        ends = _require(body.get("ends"), "Конец семестра")
        db.run(
            "INSERT INTO semesters (group_id, starts, ends) VALUES (?, ?, ?) "
            "ON CONFLICT(group_id) DO UPDATE SET starts = excluded.starts, ends = excluded.ends",
            (group["id"], starts[:10], ends[:10]),
        )
        return schedule_view(ctx)
    if path == "/api/group/invite" and method == "GET":
        return invite_view(ctx)
    if path == "/api/group/invite/reissue" and method == "POST":
        return reissue_invite(ctx)
    if path == "/api/subscription/renew" and method == "POST":
        return renew_subscription(ctx)
    if path == "/api/home" and method == "GET":
        return home(ctx)
    if path == "/api/day" and method == "GET":
        return day_view(ctx, query.get("date") or today().isoformat())
    if path == "/api/marks" and method == "POST":
        return set_mark(ctx, body)
    if path == "/api/marks/bulk" and method == "POST":
        return bulk_mark(ctx, body)
    if path == "/api/students" and method == "GET":
        return students_view(ctx)
    if path == "/api/students/self" and method == "POST":
        return add_self(ctx)
    match = re.fullmatch(r"/api/students/(\d+)", path)
    if match and method == "PATCH":
        group = ctx.require_owner()
        ctx.guard_demo(group)
        if "is_active" in body:
            db.run(
                "UPDATE users SET is_active = ? WHERE id = ? AND group_id = ?",
                (1 if body["is_active"] else 0, int(match.group(1)), group["id"]),
            )
        if body.get("name"):
            db.run(
                "UPDATE users SET full_name = ? WHERE id = ? AND group_id = ?",
                (str(body["name"])[:120], int(match.group(1)), group["id"]),
            )
        return students_view(ctx)
    if path == "/api/schedule" and method == "GET":
        return schedule_view(ctx)
    if path == "/api/schedule" and method == "POST":
        return add_lesson(ctx, body)
    match = re.fullmatch(r"/api/schedule/(\d+)", path)
    if match and method == "PATCH":
        return update_lesson(ctx, int(match.group(1)), body)
    if match and method == "DELETE":
        return delete_lesson(ctx, int(match.group(1)))
    if path == "/api/journal" and method == "GET":
        return journal_view(ctx, query.get("month") or today().strftime("%Y-%m"))
    if path == "/api/absences" and method == "GET":
        return absences_view(ctx)
    if path == "/api/announcements" and method == "GET":
        return announcements_view(ctx)
    if path == "/api/announcements" and method == "POST":
        return save_announcement(ctx, body)
    match = re.fullmatch(r"/api/announcements/(\d+)", path)
    if match and method == "PATCH":
        return update_announcement(ctx, int(match.group(1)), body)
    if match and method == "DELETE":
        return delete_announcement(ctx, int(match.group(1)))
    if path == "/api/materials" and method == "GET":
        return materials_view(ctx)
    if path == "/api/materials" and method == "POST":
        return save_material(ctx, body)
    match = re.fullmatch(r"/api/materials/(\d+)", path)
    if match and method == "DELETE":
        return delete_material(ctx, int(match.group(1)))
    if path == "/api/me/today" and method == "GET":
        return my_day(ctx)
    if path == "/api/me/answer" and method == "POST":
        return answer_self(ctx, body)
    if path == "/api/me/stats" and method == "GET":
        return my_stats(ctx)
    if path == "/api/me/answer-all" and method == "POST":
        return answer_all_today(ctx)
    if path == "/api/report/send" and method == "POST":
        return send_report(ctx, body.get("period") or "month")
    raise ApiError("Не найдено", 404)
