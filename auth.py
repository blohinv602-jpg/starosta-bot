import hashlib
import hmac
import json
import time
import urllib.parse

import config


class AuthError(Exception):
    pass


def _secret_key() -> bytes:
    return hmac.new(b"WebAppData", config.BOT_TOKEN.encode(), hashlib.sha256).digest()


def parse(init_data: str, max_age: int = 86400) -> dict:
    if config.DEV_MODE and not config.BOT_TOKEN:
        return {"id": 1000001, "first_name": "Владислав", "username": "dev"}
    if not init_data:
        raise AuthError("empty init data")

    pairs = urllib.parse.parse_qsl(init_data, keep_blank_values=True)
    data = dict(pairs)
    received_hash = data.pop("hash", "")
    if not received_hash:
        raise AuthError("no hash")

    check_string = "\n".join(f"{key}={data[key]}" for key in sorted(data))
    calculated = hmac.new(_secret_key(), check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calculated, received_hash):
        raise AuthError("bad signature")

    if max_age:
        try:
            auth_date = int(data.get("auth_date", "0"))
        except ValueError:
            raise AuthError("bad auth_date")
        if auth_date and time.time() - auth_date > max_age:
            raise AuthError("expired")

    raw_user = data.get("user")
    if not raw_user:
        raise AuthError("no user")
    try:
        return json.loads(raw_user)
    except json.JSONDecodeError:
        raise AuthError("bad user json")
