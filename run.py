import logging
import pathlib
import re
import sys

import bot_handlers
import config
import db
import scheduler
import server
import tgapi
import tgapi


def check() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(name)-10s %(message)s")
    print("BOT_TOKEN:", "задан" if config.BOT_TOKEN else "ПУСТ — впишите токен в .env")
    print("PUBLIC_URL:", config.PUBLIC_URL)
    if not config.BOT_TOKEN:
        return 1
    try:
        me = tgapi.call("getMe")
    except tgapi.TelegramError as exc:
        print("getMe не удался:", exc)
        print("Проверьте доступ к api.telegram.org с этого сервера и корректность токена.")
        return 1

    username = me.get("username") or ""
    print("bot id:", me["id"])
    print("bot username:", "@" + username)
    print("bot name:", me.get("first_name"))

    env_path = pathlib.Path(__file__).with_name(".env")
    if env_path.exists() and username:
        text = env_path.read_text(encoding="utf-8")
        updated = re.sub(r"^BOT_USERNAME=.*$", "BOT_USERNAME=" + username, text, flags=re.M)
        if updated != text:
            env_path.write_text(updated, encoding="utf-8")
            print("BOT_USERNAME записан в .env")

    tgapi.set_my_commands()
    print("команды бота обновлены")
    if config.PUBLIC_URL.startswith("https://"):
        tgapi.set_menu_button()
        print("кнопка меню приложения установлена")
    else:
        print("PUBLIC_URL не https — кнопка меню не установлена, Mini App Telegram не откроет")

    db.init()
    print("база готова:", config.DB_PATH)
    return 0


def main() -> int:
    if "--check" in sys.argv:
        return check()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)-10s %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )
    log = logging.getLogger("main")

    db.init()
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    demo_id = db.seed_demo()
    log.info("demo group ready: id=%s code=DEMO00", demo_id)

    if not config.BOT_TOKEN:
        log.warning("BOT_TOKEN не задан: Mini App работает в демо-режиме, бот выключен")
    elif not config.PUBLIC_URL.startswith("https://"):
        log.warning("PUBLIC_URL должен быть https — иначе Telegram не откроет Mini App")
    else:
        try:
            me = tgapi.call("getMe", timeout=15)
            if me.get("username"):
                config.BOT_USERNAME = me["username"]
                log.info("бот: @%s", me["username"])
        except Exception as exc:
            log.warning("getMe недоступен, BOT_USERNAME остаётся %r: %s", config.BOT_USERNAME, exc)

    bot_handlers.start()
    scheduler.start()

    httpd = server.serve()
    log.info("Mini App: %s", config.PUBLIC_URL)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        log.info("stopping")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
