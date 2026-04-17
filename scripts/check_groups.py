import asyncio
import os
from pathlib import Path
import sys

import socks
from dotenv import load_dotenv
from telethon import TelegramClient

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from chat_app.characters import CHARACTERS

load_dotenv(ENV_FILE)


def build_proxy():
    proxy_host = os.getenv("PROXY_HOST")
    proxy_port = os.getenv("PROXY_PORT")
    if proxy_host and proxy_port:
        return (socks.SOCKS5, proxy_host, int(proxy_port))
    return None


async def main():
    api_id = int(os.getenv("TELEGRAM_API_ID"))
    api_hash = os.getenv("TELEGRAM_API_HASH")
    proxy = build_proxy()

    for character in CHARACTERS:
        client = TelegramClient(character["session_file"], api_id, api_hash, proxy=proxy)
        try:
            await client.connect()
            me = await client.get_me()
            if me is None:
                print(f"[{character['name']}] 未登录")
                continue

            account_name = me.first_name or me.username or character["name"]
            print(f"\n=== {character['name']} / {account_name} ===")
            async for dialog in client.iter_dialogs():
                if getattr(dialog, "is_group", False) or getattr(dialog, "is_channel", False):
                    print(dialog.id, dialog.name)
        finally:
            await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
