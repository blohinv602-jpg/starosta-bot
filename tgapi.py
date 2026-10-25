import json
import logging
import urllib.error
import urllib.request
import uuid

import config

log = logging.getLogger("tg")

API_BASE = "https://api.telegram.org/bot{token}/{method}"


class TelegramError(Exception):
    pass


def call(method: str, timeout: int = 25, **params):
    if not config.BOT_TOKEN:
        raise TelegramError("BOT_TOKEN is not configured")
    url = API_BASE.format(token=config.BOT_TOKEN, method=method)
    payload = json.dumps(params, ensure_ascii=False).encode()
    request = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode(errors="replace")
        log.warning("telegram %s failed: %s %s", method, exc.code, raw[:300])
        raise TelegramError(raw[:300])
    except (urllib.error.URLError, TimeoutError) as exc:
        log.warning("telegram %s network error: %s", method, exc)
        raise TelegramError(str(exc))
    if not body.get("ok"):
        log.warning("telegram %s error: %s", method, str(body)[:300])
        raise TelegramError(str(body)[:300])
    return body.get("result")


def send_message(chat_id, text, reply_markup=None, parse_mode="HTML", preview=False):
    params = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "link_preview_options": {"is_disabled": not preview},
    }
    if reply_markup:
        params["reply_markup"] = reply_markup
    return call("sendMessage", **params)


def edit_message_text(chat_id, message_id, text, reply_markup=None, parse_mode="HTML"):
    params = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": parse_mode}
    if reply_markup is not None:
        params["reply_markup"] = reply_markup
    return call("editMessageText", **params)


def answer_callback_query(callback_id, text=None, show_alert=False):
    params = {"callback_query_id": callback_id, "show_alert": show_alert}
    if text:
        params["text"] = text
    try:
        return call("answerCallbackQuery", **params)
    except TelegramError:
        return None


def send_document(chat_id, filename, content: bytes, caption: str = ""):
    if not config.BOT_TOKEN:
        raise TelegramError("BOT_TOKEN is not configured")
    boundary = uuid.uuid4().hex
    body = bytearray()

    def field(name, value):
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        body.extend(str(value).encode())
        body.extend(b"\r\n")

    field("chat_id", chat_id)
    if caption:
        field("caption", caption)
    body.extend(f"--{boundary}\r\n".encode())
    body.extend(
        f'Content-Disposition: form-data; name="document"; filename="{filename}"\r\n'.encode()
    )
    body.extend(b"Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet\r\n\r\n")
    body.extend(content)
    body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode())

    request = urllib.request.Request(
        API_BASE.format(token=config.BOT_TOKEN, method="sendDocument"),
        data=bytes(body),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode())
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
        log.warning("sendDocument failed: %s", exc)
        raise TelegramError(str(exc))


def set_my_commands():
    commands = [
        {"command": "start", "description": "Открыть приложение"},
        {"command": "app", "description": "Мини-приложение"},
        {"command": "invite", "description": "Код приглашения в группу"},
        {"command": "help", "description": "Как это работает"},
    ]
    try:
        call("setMyCommands", commands=commands)
    except TelegramError:
        pass


def set_menu_button():
    if not config.PUBLIC_URL.startswith("https://"):
        return
    try:
        call(
            "setChatMenuButton",
            menu_button={
                "type": "web_app",
                "text": "Староста",
                "web_app": {"url": config.PUBLIC_URL},
            },
        )
    except TelegramError:
        pass


def get_updates(offset=None, timeout=30):
    params = {"timeout": timeout, "allowed_updates": ["message", "callback_query"]}
    if offset is not None:
        params["offset"] = offset
    return call("getUpdates", timeout=timeout + 10, **params)


def answer_web_app_query(query_id, result):
    return call("answerWebAppQuery", web_app_query_id=query_id, result=result)
