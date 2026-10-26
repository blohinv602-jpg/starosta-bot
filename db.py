import datetime as dt
import random
import sqlite3
import threading

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    university TEXT NOT NULL DEFAULT '',
    owner_tg_id INTEGER NOT NULL DEFAULT 0,
    is_demo INTEGER NOT NULL DEFAULT 0,
    poll_minutes_before INTEGER NOT NULL DEFAULT 15,
    summary_after INTEGER NOT NULL DEFAULT 10,
    absence_threshold INTEGER NOT NULL DEFAULT 3,
    tz TEXT NOT NULL DEFAULT 'Москва',
    floating_schedule INTEGER NOT NULL DEFAULT 0,
    parity_override TEXT NOT NULL DEFAULT '',
    subscription_until TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS active_group (
    tg_id INTEGER PRIMARY KEY,
    group_id INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id INTEGER NOT NULL,
    group_id INTEGER NOT NULL,
    full_name TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL DEFAULT 'student',
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    UNIQUE (tg_id, group_id)
);

CREATE TABLE IF NOT EXISTS semesters (
    group_id INTEGER PRIMARY KEY,
    starts TEXT NOT NULL,
    ends TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS lessons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id INTEGER NOT NULL,
    weekday INTEGER NOT NULL,
    parity TEXT NOT NULL DEFAULT 'both',
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    subject TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'Лек',
    room TEXT NOT NULL DEFAULT '',
    teacher TEXT NOT NULL DEFAULT '',
    has_hw INTEGER NOT NULL DEFAULT 0,
    position INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS polls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id INTEGER NOT NULL,
    lesson_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    sent_at TEXT NOT NULL,
    UNIQUE (lesson_id, date)
);

CREATE TABLE IF NOT EXISTS answers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    poll_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    status TEXT NOT NULL,
    at TEXT NOT NULL,
    UNIQUE (poll_id, user_id)
);

CREATE TABLE IF NOT EXISTS marks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id INTEGER NOT NULL,
    lesson_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    status TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'poll',
    excused INTEGER NOT NULL DEFAULT 0,
    comment TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    UNIQUE (date, lesson_id, user_id)
);

CREATE TABLE IF NOT EXISTS announcements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    pinned INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS materials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id INTEGER NOT NULL,
    subject TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL,
    file_path TEXT NOT NULL DEFAULT '',
    size INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_marks_group_date ON marks (group_id, date);
CREATE INDEX IF NOT EXISTS idx_lessons_group ON lessons (group_id, weekday);
CREATE INDEX IF NOT EXISTS idx_users_group ON users (group_id);

CREATE TABLE IF NOT EXISTS lesson_changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id INTEGER NOT NULL,
    lesson_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    kind TEXT NOT NULL,
    new_start TEXT NOT NULL DEFAULT '',
    new_end TEXT NOT NULL DEFAULT '',
    new_room TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE (lesson_id, date)
);

CREATE TABLE IF NOT EXISTS homework (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id INTEGER NOT NULL,
    lesson_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    body TEXT NOT NULL,
    author TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_homework_lesson ON homework (lesson_id, date);
"""

_local = threading.local()


def now() -> str:
    return dt.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def connect() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(config.DB_PATH, timeout=20, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        _local.conn = conn
    return conn


def q(sql: str, params=()):
    return connect().execute(sql, params).fetchall()


def q1(sql: str, params=()):
    return connect().execute(sql, params).fetchone()


def run(sql: str, params=()):
    conn = connect()
    cur = conn.execute(sql, params)
    conn.commit()
    return cur


def init() -> None:
    import pathlib

    pathlib.Path(config.DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = connect()
    conn.executescript(SCHEMA)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(lessons)")}
    if "note" not in columns:
        conn.execute("ALTER TABLE lessons ADD COLUMN note TEXT NOT NULL DEFAULT ''")
    conn.commit()


def to_dict(row) -> dict:
    return dict(row) if row is not None else None


def all_dicts(rows) -> list:
    return [dict(r) for r in rows]


ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def unique_code(length: int = 6) -> str:
    import secrets

    while True:
        code = "".join(secrets.choice(ALPHABET) for _ in range(length))
        if not q1("SELECT 1 FROM groups WHERE code = ?", (code,)):
            return code


DEMO_STUDENTS = [
    "Андреев Максим",
    "Белова Анна",
    "Васильев Илья",
    "Григорьева Полина",
    "Давыдов Артём",
    "Егоров Кирилл",
    "Зайцева Дарья",
    "Ильин Никита",
    "Козлова Мария",
    "Лебедев Арсений",
    "Морозов Денис",
    "Никитина Софья",
    "Орлов Владимир",
    "Петрова Алиса",
    "Романова Ева",
    "Сергеев Матвей",
    "Тихонова Ксения",
    "Ульянов Пётр",
    "Фёдорова Виктория",
    "Харитонов Егор",
    "Царёва Юлия",
    "Чернов Александр",
    "Шишкин Роман",
    "Щербакова Алина",
    "Юдин Глеб",
    "Яковлев Марк",
]

DEMO_ABSENCES = {
    "Васильев Илья": 15,
    "Зайцева Дарья": 13,
    "Ильин Никита": 8,
    "Яковлев Марк": 6,
    "Романова Ева": 8,
    "Сергеев Матвей": 8,
    "Тихонова Ксения": 8,
    "Андреев Максим": 4,
    "Белова Анна": 2,
}

DEMO_EXCUSED = {
    "Ильин Никита": 1,
    "Яковлев Марк": 2,
    "Романова Ева": 2,
}


def _demo_lessons() -> list:
    return [
        (1, "both", "08:15", "09:45", "Основы конструирования приборов", "Лек", "427", "Карпов Д. А.", 0),
        (1, "den", "08:15", "09:45", "Основы конструирования приборов", "Лек", "427", "Карпов Д. А.", 0),
        (1, "both", "09:55", "11:25", "Теоретическая механика", "Лек", "Акт. зал", "Беляев С. Н.", 0),
        (1, "both", "12:20", "13:50", "Элективные дисциплины по физической культуре", "Сем", "Спортзал", "Дроздов П. П.", 1),
        (2, "both", "08:15", "09:45", "Сопротивление материалов", "Лек", "312", "Гусев А. В.", 0),
        (2, "den", "09:55", "11:25", "Сопротивление материалов", "Лаб", "118", "Гусев А. В.", 1),
        (2, "both", "12:20", "13:50", "Материаловедение", "Сем", "205", "Орлова М. И.", 0),
        (3, "both", "09:55", "11:25", "Материаловедение", "Лек", "401", "Орлова М. И.", 0),
        (3, "num", "12:20", "13:50", "Материаловедение", "Лаб", "548", "Орлова М. И.", 1),
        (3, "both", "14:00", "15:30", "Инженерная графика", "Сем", "305", "Соколов И. П.", 0),
        (4, "both", "08:15", "09:45", "Теоретическая механика", "Сем", "210", "Беляев С. Н.", 1),
        (4, "both", "12:20", "13:50", "Профессиональные графические пакеты", "Лек", "305", "Соколов И. П.", 0),
        (5, "both", "08:15", "09:45", "Профессиональные графические пакеты", "Лек", "305", "Соколов И. П.", 0),
        (5, "both", "17:15", "18:45", "Профессиональные графические пакеты", "Лаб", "305", "Соколов И. П.", 1),
        (6, "both", "09:55", "11:25", "Основы конструирования приборов", "Сем", "427", "Карпов Д. А.", 0),
    ]


def seed_demo() -> int:
    existing = q1("SELECT id FROM groups WHERE code = 'DEMO00'")
    if existing:
        return int(existing["id"])

    today = dt.date.today()
    created = now()
    cur = run(
        "INSERT INTO groups (code, name, university, owner_tg_id, is_demo, subscription_until, created_at) "
        "VALUES (?, ?, ?, 0, 1, ?, ?)",
        ("DEMO00", "AT-21", "Технический университет", (today + dt.timedelta(days=23)).isoformat(), created),
    )
    gid = int(cur.lastrowid)

    semester_start = today.replace(month=9, day=1) if today.month >= 9 else today.replace(month=2, day=7)
    semester_end = semester_start + dt.timedelta(days=120)
    run(
        "INSERT INTO semesters (group_id, starts, ends) VALUES (?, ?, ?)",
        (gid, semester_start.isoformat(), semester_end.isoformat()),
    )

    for idx, name in enumerate(DEMO_STUDENTS):
        run(
            "INSERT INTO users (tg_id, group_id, full_name, role, is_active, created_at) VALUES (?, ?, ?, 'student', 1, ?)",
            (-(idx + 1), gid, name, created),
        )

    rnd = random.Random(1024)
    for i, (wd, parity, start, end, subject, kind, room, teacher, hw) in enumerate(_demo_lessons()):
        run(
            "INSERT INTO lessons (group_id, weekday, parity, start_time, end_time, subject, kind, room, teacher, has_hw, position) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (gid, wd, parity, start, end, subject, kind, room, teacher, hw, i),
        )

    run(
        "INSERT INTO announcements (group_id, title, body, pinned, created_at) VALUES (?, ?, ?, 1, ?)",
        (
            gid,
            "Зачётные книжки",
            "До пятницы сдать зачётки в деканат, кабинет 214. Кто не сдаст — не будет допуска к сессии.",
            (today - dt.timedelta(days=1)).strftime("%Y-%m-%dT21:24:00"),
        ),
    )
    run(
        "INSERT INTO announcements (group_id, title, body, pinned, created_at) VALUES (?, ?, ?, 0, ?)",
        (
            gid,
            "Перенос лабораторной",
            "Лабораторная по материаловедению в четверг переносится в аудиторию 548.",
            (today - dt.timedelta(days=1)).strftime("%Y-%m-%dT21:24:00"),
        ),
    )

    lessons = q("SELECT * FROM lessons WHERE group_id = ? ORDER BY weekday, start_time", (gid,))
    users = q("SELECT * FROM users WHERE group_id = ?", (gid,))

    def parity_of(day: dt.date) -> str:
        week = day.isocalendar()[1]
        return "num" if week % 2 == 0 else "den"

    past_dates = []
    cursor = today - dt.timedelta(days=1)
    while len(past_dates) < 45 and cursor > semester_start:
        if cursor.weekday() < 6:
            day_lessons = [
                l for l in lessons
                if int(l["weekday"]) == cursor.isoweekday() and (l["parity"] == "both" or l["parity"] == parity_of(cursor))
            ]
            for lesson in day_lessons:
                past_dates.append((cursor.isoformat(), lesson))
                if len(past_dates) >= 45:
                    break
        cursor -= dt.timedelta(days=1)

    past_dates.reverse()

    absence_budget = {}
    for user in users:
        name = user["full_name"]
        absence_budget[user["id"]] = DEMO_ABSENCES.get(name, rnd.randint(0, 5))
    excused_budget = dict(DEMO_EXCUSED)

    total = len(past_dates)
    stamps = {u["id"]: 0 for u in users}
    for date_str, lesson in past_dates:
        for user in users:
            uid = user["id"]
            remaining = total - stamps[uid]
            stamps[uid] += 1
            budget = absence_budget[uid]
            absent = rnd.random() < (budget / remaining if remaining else 0) if budget > 0 else False
            if absent:
                absence_budget[uid] = max(0, budget - 1)
                excused = 0
                if excused_budget.get(user["full_name"], 0) > 0 and rnd.random() < 0.25:
                    excused = 1
                status = "absent"
            else:
                status = "late" if rnd.random() < 0.04 else "present"
                excused = 0
            run(
                "INSERT OR IGNORE INTO marks (group_id, lesson_id, date, user_id, status, source, excused, updated_at) "
                "VALUES (?, ?, ?, ?, ?, 'seed', ?, ?)",
                (gid, lesson["id"], date_str, uid, status, excused, created),
            )

    return gid
