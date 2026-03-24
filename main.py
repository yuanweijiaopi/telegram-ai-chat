import asyncio
import random
import os
from telethon import TelegramClient, events
from telethon.errors import FloodWaitError
from dotenv import load_dotenv
from characters import CHARACTERS
import anthropic

load_dotenv()

API_ID = int(os.getenv("TELEGRAM_API_ID"))
API_HASH = os.getenv("TELEGRAM_API_HASH")
GROUP_ID = int(os.getenv("TELEGRAM_GROUP_ID"))
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

REPLY_DELAY_MIN = int(os.getenv("REPLY_DELAY_MIN", 15))
REPLY_DELAY_MAX = int(os.getenv("REPLY_DELAY_MAX", 60))
MAX_CONTEXT = 10  # 记忆最近几条消息

ai = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
chat_history = []  # 所有角色共享的聊天记录
reply_lock = asyncio.Lock()  # 防止多个角色同时抢着回复


async def ai_reply(character: dict, history: list[dict]) -> str:
    """调用 Claude 生成角色回复"""
    other_names = [c["name"] for c in CHARACTERS if c["name"] != character["name"]]
    context = "\n".join(f"{m['name']}: {m['text']}" for m in history[-MAX_CONTEXT:])

    response = ai.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=120,
        system=(
            f"{character['system']}\n\n"
            f"群里的其他人有：{'、'.join(other_names)}。\n"
            f"最近的聊天记录：\n{context}\n\n"
            "请以你的身份自然地回复，简短像真人聊天（1~2句话），"
            "只输出要说的话，不要加任何名字前缀或引号。"
        ),
        messages=[{"role": "user", "content": "请继续这个对话"}],
    )
    return response.content[0].text.strip()


def make_handler(client: TelegramClient, character: dict):
    """为每个角色生成消息处理器"""

    @client.on(events.NewMessage(chats=GROUP_ID))
    async def handler(event):
        if not event.text:
            return

        # 忽略自己发的消息
        me = await client.get_me()
        if event.sender_id == me.id:
            return

        # 记录到共享历史
        sender = await event.get_sender()
        sender_name = getattr(sender, "first_name", "未知")
        chat_history.append({"name": sender_name, "text": event.text})
        if len(chat_history) > 50:
            chat_history.pop(0)

        # 按概率决定是否回复
        if random.random() > character["reply_prob"]:
            return

        # 随机延迟，模拟真人
        delay = random.randint(REPLY_DELAY_MIN, REPLY_DELAY_MAX)
        await asyncio.sleep(delay)

        async with reply_lock:
            try:
                reply = await ai_reply(character, chat_history)
                await client.send_message(GROUP_ID, reply)
                # 把自己的回复也加入历史
                chat_history.append({"name": character["name"], "text": reply})
                print(f"[{character['name']}] {reply}")
            except FloodWaitError as e:
                print(f"[{character['name']}] 触发限流，等待 {e.seconds}s")
                await asyncio.sleep(e.seconds)
            except Exception as e:
                print(f"[{character['name']}] 出错：{e}")

    return handler


async def login_character(character: dict) -> TelegramClient:
    """登录单个角色账号"""
    os.makedirs("sessions", exist_ok=True)
    client = TelegramClient(character["session_file"], API_ID, API_HASH)
    await client.start(phone=character["phone"])
    me = await client.get_me()
    print(f"✓ {character['name']} 登录成功 ({me.first_name})")
    make_handler(client, character)
    return client


async def main():
    print("正在登录所有角色...")
    clients = await asyncio.gather(*[login_character(c) for c in CHARACTERS])

    print(f"\n所有角色已就绪，监听群 {GROUP_ID} 中...\n")
    await asyncio.gather(*[c.run_until_disconnected() for c in clients])


if __name__ == "__main__":
    asyncio.run(main())
