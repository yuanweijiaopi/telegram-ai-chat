import asyncio
import socks
from telethon import TelegramClient
from dotenv import load_dotenv
import os

load_dotenv()

async def main():
    proxy = (socks.SOCKS5, '127.0.0.1', int(os.getenv('PROXY_PORT', 50656)))
    client = TelegramClient('sessions/laowang.session', int(os.getenv('TELEGRAM_API_ID')), os.getenv('TELEGRAM_API_HASH'), proxy=proxy)
    await client.start()
    async for dialog in client.iter_dialogs():
        print(dialog.id, dialog.name)
    await client.disconnect()

asyncio.run(main())
