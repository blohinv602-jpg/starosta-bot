import db

DEMO_CODE = "DEMO00"
DROP_TG_ID = 1456121449


def drop_demo_group() -> None:
    group = db.q1("SELECT * FROM groups WHERE code = ? AND is_demo = 1", (DEMO_CODE,))
    if not group:
        print("демо-группа не найдена")
        return
    gid = int(group["id"])
    db.run("DELETE FROM answers WHERE poll_id IN (SELECT id FROM polls WHERE group_id = ?)", (gid,))
    for table in (
        "marks",
        "polls",
        "lessons",
        "announcements",
        "materials",
        "semesters",
        "users",
        "active_group",
    ):
        db.run(f"DELETE FROM {table} WHERE group_id = ?", (gid,))
    db.run("DELETE FROM groups WHERE id = ?", (gid,))
    print("демо-группа удалена:", gid, DEMO_CODE)


def drop_user(tg_id: int) -> None:
    user = db.q1("SELECT * FROM users WHERE tg_id = ?", (tg_id,))
    if not user:
        print("пользователь не найден:", tg_id)
        return
    db.run("DELETE FROM answers WHERE user_id = ?", (user["id"],))
    db.run("DELETE FROM marks WHERE user_id = ?", (user["id"],))
    db.run("DELETE FROM users WHERE id = ?", (user["id"],))
    db.run("DELETE FROM active_group WHERE tg_id = ?", (tg_id,))
    print("пользователь удалён:", tg_id, user["full_name"])


def run() -> None:
    drop_demo_group()
    drop_user(DROP_TG_ID)
