import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"


def main() -> None:
    load_dotenv(ENV_FILE)
    print(repr(os.getenv("CHARACTER_XIAOMING_PHONE")))
    print(repr(os.getenv("CHARACTER_LAOWANG_PHONE")))


if __name__ == "__main__":
    main()
