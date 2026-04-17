from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
LOG_DIR = PROJECT_ROOT / "logs"
RUN_DIR = PROJECT_ROOT / "run"
SESSIONS_DIR = PROJECT_ROOT / "sessions"

ENV_FILE = PROJECT_ROOT / ".env"
CHAT_LOG = LOG_DIR / "chat.log"
STRATEGY_LOG = LOG_DIR / "strategy.log"
LOTTERY_DB_PATH = DATA_DIR / "lottery.db"
LOTTERY_BOT_LOG = LOG_DIR / "lottery_bot.log"
CHAT_PID_FILE = RUN_DIR / "chat.pid"
LOTTERY_PID_FILE = RUN_DIR / "lottery_bot.pid"


def ensure_runtime_dirs() -> None:
    for directory in (DATA_DIR, LOG_DIR, RUN_DIR, SESSIONS_DIR):
        directory.mkdir(parents=True, exist_ok=True)


ensure_runtime_dirs()
