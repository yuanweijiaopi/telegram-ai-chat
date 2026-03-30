import asyncio
import json
import logging
import os
import random
import time
import socks
from telethon import TelegramClient, events
from telethon.errors import FloodWaitError
from dotenv import load_dotenv
from characters import BEHAVIOR_POLICY, CHARACTERS, GLOBAL_RULES
from behavior import (
    build_system_prompt,
    detect_message_meta,
    enrich_message_meta,
    is_recent_duplicate_entry,
    merge_policy,
    record_message,
    should_send_after_delay,
    should_reply,
)
from openai import AsyncOpenAI

load_dotenv()

logging.getLogger("telethon").setLevel(logging.ERROR)

_missing = [v for v in ("TELEGRAM_API_ID", "TELEGRAM_API_HASH", "TELEGRAM_GROUP_ID", "AI_API_KEY", "AI_MODEL") if not os.getenv(v)]
if _missing:
    raise EnvironmentError(f"缺少必需的环境变量：{', '.join(_missing)}，请检查 .env 文件")

API_ID = int(os.getenv("TELEGRAM_API_ID"))
API_HASH = os.getenv("TELEGRAM_API_HASH")
GROUP_ID = int(os.getenv("TELEGRAM_GROUP_ID"))

REPLY_DELAY_MIN = int(os.getenv("REPLY_DELAY_MIN", 15))
REPLY_DELAY_MAX = int(os.getenv("REPLY_DELAY_MAX", 60))

# 通用 AI 客户端，切换模型只需修改 .env
ai = AsyncOpenAI(
    api_key=os.getenv("AI_API_KEY"),
    base_url=os.getenv("AI_BASE_URL"),
)
AI_MODEL = os.getenv("AI_MODEL")

chat_history = []  # 所有角色共享的聊天记录
reply_lock = asyncio.Lock()  # 防止多个角色同时抢着回复
last_reply_at = {}
managed_sender_ids = {}
policy = merge_policy(
    BEHAVIOR_POLICY,
    {
        "max_context": int(os.getenv("MAX_CONTEXT", BEHAVIOR_POLICY["max_context"])),
        "max_history": int(os.getenv("MAX_HISTORY", BEHAVIOR_POLICY["max_history"])),
        "min_seconds_between_replies": int(
            os.getenv(
                "MIN_SECONDS_BETWEEN_REPLIES",
                BEHAVIOR_POLICY["min_seconds_between_replies"],
            )
        ),
        "min_seconds_between_replies_human": int(
            os.getenv(
                "MIN_SECONDS_BETWEEN_REPLIES_HUMAN",
                os.getenv(
                    "MIN_SECONDS_BETWEEN_REPLIES",
                    BEHAVIOR_POLICY.get("min_seconds_between_replies_human", 45),
                ),
            )
        ),
        "min_seconds_between_replies_character": int(
            os.getenv(
                "MIN_SECONDS_BETWEEN_REPLIES_CHARACTER",
                BEHAVIOR_POLICY.get("min_seconds_between_replies_character", 8),
            )
        ),
        "mention_reply_bonus": float(
            os.getenv(
                "MENTION_REPLY_BONUS",
                BEHAVIOR_POLICY.get("mention_reply_bonus", 0.25),
            )
        ),
        "quiet_window_seconds": int(
            os.getenv(
                "QUIET_WINDOW_SECONDS",
                BEHAVIOR_POLICY.get("quiet_window_seconds", 180),
            )
        ),
        "recent_reply_window_seconds": int(
            os.getenv(
                "RECENT_REPLY_WINDOW_SECONDS",
                BEHAVIOR_POLICY.get("recent_reply_window_seconds", 90),
            )
        ),
        "stale_pending_reply_seconds": int(
            os.getenv(
                "STALE_PENDING_REPLY_SECONDS",
                BEHAVIOR_POLICY.get("stale_pending_reply_seconds", 25),
            )
        ),
        "same_sender_streak_limit": int(
            os.getenv(
                "SAME_SENDER_STREAK_LIMIT",
                BEHAVIOR_POLICY.get("same_sender_streak_limit", 3),
            )
        ),
    },
)
policy["other_names"] = [character["name"] for character in CHARACTERS]

strategy_logger = logging.getLogger("strategy")
strategy_logger.setLevel(logging.INFO)
if not strategy_logger.handlers:
    handler = logging.FileHandler("strategy.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    strategy_logger.addHandler(handler)


def log_strategy(event_type: str, **payload):
    entry = {
        "ts": int(time.time()),
        "event": event_type,
        **payload,
    }
    strategy_logger.info(json.dumps(entry, ensure_ascii=False))


def sanitize_model_text(text: str | None) -> str:
    if not text:
        return ""
    cleaned = text.strip().strip("\"' \n\t")
    return cleaned


def format_recent_history(history: list[dict], limit: int = 4) -> str:
    recent = history[-limit:]
    lines = []
    for item in recent:
        name = item.get("name", "未知")
        text = sanitize_model_text(item.get("text", ""))
        if not text:
            continue
        lines.append(f"{name}: {text}")
    return "\n".join(lines) or "暂无"


async def generate_with_retry(
    *,
    character: dict,
    history: list[dict],
    mode: str,
    user_content: str,
    max_tokens: int,
) -> str:
    """调用 AI 生成文本；若首轮为空，则用更短更直接的 prompt 重试一次"""
    primary_system_prompt = build_system_prompt(
        character,
        history,
        GLOBAL_RULES,
        policy,
        mode=mode,
    )
    response = await ai.chat.completions.create(
        model=AI_MODEL,
        max_tokens=max_tokens,
        messages=[
            {
                "role": "system",
                "content": primary_system_prompt,
            },
            {"role": "user", "content": user_content},
        ],
    )
    primary_finish_reason = getattr(response.choices[0], "finish_reason", None)
    content = sanitize_model_text(response.choices[0].message.content)
    if content:
        return content
    log_strategy(
        f"{mode}_primary_empty",
        character=character["name"],
        finish_reason=primary_finish_reason,
        user_content=user_content,
    )
    print(f"[{character['name']}] {mode} 首轮为空，finish_reason={primary_finish_reason}")

    retry_instruction = {
        "reply": (
            f"你是{character['name']}。现在在群里聊天。"
            "必须只输出 1 句中文短话，像顺嘴接一句。"
            "口语化，别解释，别总结，别空字符串。"
        ),
        "topic": (
            f"你是{character['name']}。现在在群里主动起个话头。"
            "必须只输出 1 句中文短话。"
            "口语化，像临时想到的，不要模板问句，不要空字符串。"
        ),
    }
    recent_history_text = format_recent_history(history, limit=4)
    retry_response = await ai.chat.completions.create(
        model=AI_MODEL,
        max_tokens=max(80, max_tokens),
        messages=[
            {
                "role": "system",
                "content": retry_instruction.get(mode, retry_instruction["reply"]),
            },
            {
                "role": "user",
                "content": (
                    f"最近聊天：\n{recent_history_text}\n\n"
                    f"当前需求：{user_content}\n\n"
                    "直接给我最终要发出去的那一句话。"
                ),
            },
        ],
    )
    retry_finish_reason = getattr(retry_response.choices[0], "finish_reason", None)
    retry_content = sanitize_model_text(retry_response.choices[0].message.content)
    if retry_content:
        log_strategy(
            f"{mode}_retried_success",
            character=character["name"],
        )
        return retry_content

    log_strategy(
        f"{mode}_retried_empty",
        character=character["name"],
        finish_reason=retry_finish_reason,
        user_content=user_content,
    )
    print(f"[{character['name']}] {mode} 重试仍为空，finish_reason={retry_finish_reason}")
    return ""


async def ai_reply(character: dict, history: list[dict]) -> str:
    """调用 AI 生成角色回复"""
    return await generate_with_retry(
        character=character,
        history=history,
        mode="reply",
        user_content="请继续这个对话",
        max_tokens=120,
    )


def make_handler(client: TelegramClient, character: dict, me_id: int):
    """为每个角色生成消息处理器"""

    @client.on(events.NewMessage(chats=GROUP_ID))
    async def handler(event):
        print(f"[{character['name']}] 收到消息: {event.text[:30] if event.text else '(非文字)'}")
        if not event.text:
            return

        # 忽略自己发的消息
        if event.sender_id == me_id:
            print(f"[{character['name']}] 忽略自己的消息")
            return

        # 记录到共享历史
        sender = await event.get_sender()
        sender_name = managed_sender_ids.get(event.sender_id, getattr(sender, "first_name", "未知"))
        source = "character" if event.sender_id in managed_sender_ids else "human"
        message_meta = detect_message_meta(
            text=event.text,
            sender_name=sender_name,
            source=source,
            character_name=character["name"],
            aliases=[character["name"], f"@{character['name']}"],
        )
        if not is_recent_duplicate_entry(chat_history, name=sender_name, text=event.text):
            record_message(
                chat_history,
                policy,
                name=sender_name,
                text=event.text,
                source=source,
            )
            message_meta = enrich_message_meta(chat_history, policy, message_meta)
        else:
            message_meta = enrich_message_meta(chat_history, policy, message_meta)
            log_strategy(
                "history_skip_duplicate",
                character=character["name"],
                sender=sender_name,
                text=event.text,
            )

        ok_to_reply, reason = should_reply(
            character,
            chat_history,
            policy,
            last_reply_at,
            message_meta,
        )
        if not ok_to_reply:
            print(f"[{character['name']}] 跳过回复: {reason}")
            log_strategy(
                "reply_skip",
                character=character["name"],
                reason=reason,
                message_meta=message_meta,
                history_size=len(chat_history),
            )
            return

        # 随机延迟，模拟真人
        delay = random.randint(REPLY_DELAY_MIN, REPLY_DELAY_MAX)
        log_strategy(
            "reply_scheduled",
            character=character["name"],
            delay=delay,
            message_meta=message_meta,
        )
        pending_text = event.text
        pending_sender = sender_name
        await asyncio.sleep(delay)

        async with reply_lock:
            try:
                can_send, final_reason = should_send_after_delay(
                    character,
                    chat_history,
                    policy,
                    pending_text,
                    pending_sender,
                    message_meta,
                )
                if not can_send:
                    log_strategy(
                        "reply_cancelled",
                        character=character["name"],
                        reason=final_reason,
                        message_meta=message_meta,
                    )
                    print(f"[{character['name']}] 取消回复: {final_reason}")
                    return

                reply = await ai_reply(character, chat_history)
                reply = sanitize_model_text(reply)
                if not reply:
                    log_strategy(
                        "reply_empty",
                        character=character["name"],
                        message_meta=message_meta,
                    )
                    print(f"[{character['name']}] 跳过空回复")
                    return
                await client.send_message(GROUP_ID, reply)
                last_reply_at[character["name"]] = time.time()
                record_message(
                    chat_history,
                    policy,
                    name=character["name"],
                    text=reply,
                    source="character",
                )
                print(f"[{character['name']}] {reply}")
                log_strategy(
                    "reply_sent",
                    character=character["name"],
                    text=reply,
                    message_meta=message_meta,
                )
            except FloodWaitError as e:
                print(f"[{character['name']}] 触发限流，等待 {e.seconds}s")
                log_strategy(
                    "reply_flood_wait",
                    character=character["name"],
                    seconds=e.seconds,
                )
                await asyncio.sleep(e.seconds)
            except Exception as e:
                print(f"[{character['name']}] 出错：{e}")
                log_strategy(
                    "reply_error",
                    character=character["name"],
                    error=str(e),
                )

    return handler


async def login_character(character: dict) -> TelegramClient:
    """登录单个角色账号"""
    os.makedirs("sessions", exist_ok=True)
    proxy = None
    proxy_host = os.getenv("PROXY_HOST")
    proxy_port = os.getenv("PROXY_PORT")
    if proxy_host and proxy_port:
        proxy = (socks.SOCKS5, proxy_host, int(proxy_port))
    client = TelegramClient(character["session_file"], API_ID, API_HASH, proxy=proxy)
    await client.start(phone=character["phone"])
    me = await client.get_me()
    managed_sender_ids[me.id] = character["name"]
    print(f"✓ {character['name']} 登录成功 ({me.first_name})")
    make_handler(client, character, me.id)
    return client


TOPICS = [
    "刚刷到一个离谱视频，给我看笑了",
    "今天突然有点不想上班，草",
    "最近晚上老睡不踏实，不知道是不是咖啡喝多了",
    "刚点的外卖居然还行，难得",
    "我发现有些app更新完更难用了",
    "最近天气一变，人就容易烦",
    "刚路过便利店，差点又买一堆没用的东西",
    "有时候真想把手机扔远一点，太吵了",
]

TOPIC_START_DELAY = int(os.getenv("TOPIC_START_DELAY", 30))
TOPIC_RETRY_DELAY_ON_EMPTY = int(os.getenv("TOPIC_RETRY_DELAY_ON_EMPTY", 15))


async def auto_topic(clients: list[TelegramClient]):
    """定时随机挑一个角色发起话题"""
    interval = int(os.getenv("TOPIC_INTERVAL", 1800))  # 默认30分钟
    await asyncio.sleep(TOPIC_START_DELAY)  # 启动后先等一会儿
    while True:
        character = random.choice(CHARACTERS)
        client = clients[CHARACTERS.index(character)]
        topic = random.choice(TOPICS)

        msg = await generate_with_retry(
            character=character,
            history=chat_history,
            mode="topic",
            user_content=topic,
            max_tokens=120,
        )
        msg = sanitize_model_text(msg)
        if not msg:
            log_strategy("topic_skipped", character=character["name"], topic_seed=topic)
            print(
                f"[{character['name']}] 发题为空，"
                f"{TOPIC_RETRY_DELAY_ON_EMPTY}s 后重试"
            )
            await asyncio.sleep(TOPIC_RETRY_DELAY_ON_EMPTY)
            continue
        await client.send_message(GROUP_ID, msg)
        record_message(
            chat_history,
            policy,
            name=character["name"],
            text=msg,
            source="character",
        )
        last_reply_at[character["name"]] = time.time()
        print(f"[{character['name']}] 发起话题: {msg}")
        log_strategy(
            "topic_sent",
            character=character["name"],
            topic_seed=topic,
            text=msg,
        )
        await asyncio.sleep(interval)


async def main():
    print("正在登录所有角色...")
    clients = await asyncio.gather(*[login_character(c) for c in CHARACTERS])

    print(f"\n所有角色已就绪，监听群 {GROUP_ID} 中...\n")
    await asyncio.gather(
        *[c.run_until_disconnected() for c in clients],
        auto_topic(clients),
    )


if __name__ == "__main__":
    asyncio.run(main())
