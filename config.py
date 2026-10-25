import os
import pathlib

BASE_DIR = pathlib.Path(__file__).resolve().parent


def _load_env(path: pathlib.Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env(BASE_DIR / ".env")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
BOT_USERNAME = os.getenv("BOT_USERNAME", "").strip()
PUBLIC_URL = os.getenv("PUBLIC_URL", "http://localhost:8080").rstrip("/")
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8080"))
DB_PATH = os.getenv("DB_PATH", str(BASE_DIR / "data" / "starosta.sqlite3"))
UPLOAD_DIR = pathlib.Path(os.getenv("UPLOAD_DIR", str(BASE_DIR / "data" / "uploads")))
WEB_DIR = BASE_DIR / "web"
TIMEZONE = os.getenv("TIMEZONE", "Europe/Moscow")
DEV_MODE = os.getenv("DEV_MODE", "0") == "1" or not BOT_TOKEN
SUBSCRIPTION_DAYS = int(os.getenv("SUBSCRIPTION_DAYS", "30"))
