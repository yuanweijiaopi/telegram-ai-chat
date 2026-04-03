import asyncio
import json
import logging
import os
import random
import re
import time
import httpx
import socks
from dotenv import load_dotenv
load_dotenv()
from telethon import TelegramClient, events
from telethon.errors import FloodWaitError
from characters import BEHAVIOR_POLICY, CHARACTERS, GLOBAL_RULES
from behavior import (
    build_system_prompt,
    is_recent_duplicate_entry,
    merge_policy,
    record_message,
)
from session_manager import (
    cleanup_orphaned_sessions,
    validate_no_duplicate_phones,
    validate_session_identity,
)
from difflib import SequenceMatcher
from openai import AsyncOpenAI

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
    # openai==1.0.0 默认会给 httpx.AsyncClient 传入已废弃的 proxies 参数；
    # 显式提供客户端，兼容当前环境中的 httpx 0.28+。
    http_client=httpx.AsyncClient(),
)
AI_MODEL = os.getenv("AI_MODEL")

chat_history = []  # 所有角色共享的聊天记录
last_reply_at = {}
managed_sender_ids = {}
_reply_queue: asyncio.Queue = asyncio.Queue(maxsize=50)  # AI Town 协调器队列，限制深度防止堆积
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
policy["always_reply"] = os.getenv("ALWAYS_REPLY", "true").lower() == "true"

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


def _is_too_similar_to_recent(reply: str, history: list, threshold: float = 0.6, window: int = 5) -> bool:
    for item in history[-window:]:
        ratio = SequenceMatcher(None, reply, item.get("text", "")).ratio()
        if ratio > threshold:
            return True
    return False


def sanitize_model_text(text: str | None) -> str:
    if not text:
        return ""
    cleaned = text.strip().strip("\"' \n\t")
    return cleaned


def strip_character_prefix(text: str, character: dict) -> str:
    cleaned = sanitize_model_text(text)
    if not cleaned:
        return ""

    names = [character.get("name", "").strip()]
    telegram_name = (character.get("telegram_name") or "").strip()
    if telegram_name:
        names.append(telegram_name)

    for name in names:
        if not name:
            continue
        pattern = rf"^\s*{re.escape(name)}\s*[：:,-]\s*"
        cleaned = re.sub(pattern, "", cleaned, count=1).strip()
    return cleaned


def format_login_identity(character: dict) -> str:
    phone = (character.get("phone") or "").strip()
    suffix = phone[-4:] if len(phone) >= 4 else phone or "未知号码"
    return f"{character['name']}({suffix})"


def format_telegram_identity(me, character: dict) -> str:
    display_name = getattr(me, "first_name", None) or getattr(me, "username", None)
    if display_name:
        return display_name
    return format_login_identity(character)


async def resolve_login_identity(client: TelegramClient, character: dict) -> str:
    await client.connect()
    existing_me = await client.get_me()
    if existing_me is not None:
        return format_telegram_identity(existing_me, character)
    return format_login_identity(character)


def build_proxy():
    proxy_host = os.getenv("PROXY_HOST")
    proxy_port = os.getenv("PROXY_PORT")
    try:
        if proxy_host and proxy_port:
            return (socks.SOCKS5, proxy_host, int(proxy_port))
    except ValueError:
        print(f"警告：PROXY_PORT 值无效（{proxy_port}），已跳过代理配置")
    return None


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


async def ai_reply_with_new_angle(character: dict, history: list[dict]) -> str:
    """在重复风险较高时，强制换一个角度重新生成回复"""
    return await generate_with_retry(
        character=character,
        history=history,
        mode="reply",
        user_content=(
            "请继续这个对话，但必须换一个新角度。"
            "不要复述上一句，不要同义改写，不要只换几个词。"
            "可以补充新信息、换个吐槽点、推进一下话题，像真人接话。"
        ),
        max_tokens=120,
    )


async def ai_reply_unique(character: dict, history: list[dict]) -> str:
    """借鉴 AI Town 的唯一性保证：最多重试3次，确保内容不与近期消息重复"""
    reply = await ai_reply(character, history)
    reply = strip_character_prefix(reply, character)

    for attempt in range(3):
        # 有内容且不重复，直接用
        if reply and not _is_too_similar_to_recent(reply, history):
            break
        # 空内容或太相似，都继续重试
        print(f"[{character['name']}] 内容{'为空' if not reply else '重复'}，换角度重试（第{attempt + 1}次）")
        log_strategy("reply_similar_retry", character=character["name"], attempt=attempt + 1)
        reply = await ai_reply_with_new_angle(character, history)
        reply = strip_character_prefix(reply, character)

    return reply


def make_handler(client: TelegramClient, character: dict, me_id: int):
    """每个角色只负责收消息入队，回复由 reply_coordinator 统一分配（AI Town 模式）"""

    @client.on(events.NewMessage(chats=GROUP_ID))
    async def handler(event):
        if not event.text or event.sender_id == me_id:
            return
        sender = await event.get_sender()
        sender_name = managed_sender_ids.get(event.sender_id, getattr(sender, "first_name", "未知"))
        source = "character" if event.sender_id in managed_sender_ids else "human"
        print(f"[{character['name']}] 收到消息: {event.text[:30]}")
        try:
            _reply_queue.put_nowait({
                "text": event.text,
                "sender_name": sender_name,
                "source": source,
                "timestamp": time.time(),
            })
        except asyncio.QueueFull:
            print(f"[{character['name']}] 队列已满，丢弃消息: {event.text[:30]}")
            log_strategy("queue_full_drop", sender=sender_name, text=event.text[:30])

    return handler


async def reply_coordinator(clients: list[TelegramClient]):
    """
    借鉴 AI Town 单线程协调器：
    - 所有消息统一入队，每次只处理一条
    - 随机指定一个角色回复，其他角色不抢
    - 配合 ai_reply_unique 保证内容不重复
    """
    client_map = {character["name"]: clients[i] for i, character in enumerate(CHARACTERS)}

    while True:
        item = await _reply_queue.get()
        text = item["text"]
        sender_name = item["sender_name"]
        source = item["source"]
        is_retry = item.get("is_retry", False)

        # 非重试消息才记录历史；重试时历史已记录，直接跳到发送
        if not is_retry:
            if not is_recent_duplicate_entry(chat_history, name=sender_name, text=text):
                record_message(chat_history, policy, name=sender_name, text=text, source=source)
            else:
                log_strategy("history_skip_duplicate", sender=sender_name, text=text)
                continue

        # 重试时复用原角色，否则随机指定一个（排除发送者）
        if is_retry and "assigned_character" in item:
            character = next((c for c in CHARACTERS if c["name"] == item["assigned_character"]), None)
            if not character:
                continue
        else:
            candidates = [c for c in CHARACTERS if c["name"] != sender_name]
            if not candidates:
                continue
            character = random.choice(candidates)
        client = client_map[character["name"]]

        # 重试不再等待，直接发；首次处理才延迟+过期检查
        if not is_retry:
            delay = random.randint(REPLY_DELAY_MIN, REPLY_DELAY_MAX)
            log_strategy("reply_scheduled", character=character["name"], delay=delay, trigger=text[:30])
            await asyncio.sleep(delay)

            msg_age = time.time() - item["timestamp"]
            if msg_age > REPLY_DELAY_MAX * 2:
                log_strategy("reply_stale_skipped", character=character["name"], age=int(msg_age), text=text[:30])
                print(f"[{character['name']}] 消息已过期（{int(msg_age)}s），跳过")
                continue

        try:
            reply = await ai_reply_unique(character, chat_history)
            if not reply:
                log_strategy("reply_empty", character=character["name"])
                print(f"[{character['name']}] 跳过空回复")
                continue

            await client.send_message(GROUP_ID, reply)
            record_message(chat_history, policy, name=character["name"], text=reply, source="character")
            print(f"[{character['name']}] {reply}")
            log_strategy("reply_sent", character=character["name"], text=reply)

        except FloodWaitError as e:
            print(f"[{character['name']}] 触发限流，等待 {e.seconds}s")
            log_strategy("reply_flood_wait", character=character["name"], seconds=e.seconds)
            await asyncio.sleep(e.seconds)
            # 标记为重试并重置时间戳，避免重入队后立即过期
            try:
                _reply_queue.put_nowait({
                    **item,
                    "is_retry": True,
                    "assigned_character": character["name"],
                    "timestamp": time.time(),
                })
            except asyncio.QueueFull:
                log_strategy("reply_flood_requeue_failed", character=character["name"])
        except Exception as e:
            print(f"[{character['name']}] 出错：{e}")
            log_strategy("reply_error", character=character["name"], error=str(e))


async def login_character(character: dict) -> TelegramClient:
    """登录单个角色账号"""
    os.makedirs("sessions", exist_ok=True)
    proxy = build_proxy()
    client = TelegramClient(character["session_file"], API_ID, API_HASH, proxy=proxy)

    # 校验 session 文件与角色手机号是否一致
    await client.connect()
    ok, reason = await validate_session_identity(client, character)
    await client.disconnect()
    if not ok:
        raise RuntimeError(f"[{character['name']}] Session 与角色不匹配：{reason}")

    login_identity = await resolve_login_identity(client, character)

    def ask_code() -> str:
        return input(f"[{login_identity}] 请输入收到的验证码: ").strip()

    def ask_password() -> str:
        return input(f"[{login_identity}] 请输入二步验证密码: ").strip()

    await client.start(
        phone=character["phone"],
        code_callback=ask_code,
        password=ask_password,
    )
    me = await client.get_me()
    managed_sender_ids[me.id] = character["name"]
    print(f"✓ {character['name']} 登录成功 ({me.first_name})")
    make_handler(client, character, me.id)
    return client



TOPIC_START_DELAY = int(os.getenv("TOPIC_START_DELAY", 30))
TOPIC_RETRY_DELAY_ON_EMPTY = int(os.getenv("TOPIC_RETRY_DELAY_ON_EMPTY", 15))

_ALL_TOPIC_DIRECTIONS = [
    "工作、加班、老板、同事",
    "吃饭、外卖、今天吃什么",
    "钱、消费、买了什么",
    "手机、App、刷到的内容",
    "睡眠、作息、熬夜",
    "交通、堵车、出行",
    "游戏、娱乐、追剧",
    "朋友、聚会、社交",
    "天气、季节、身体状态",
    "随便一件今天发生的小事",
]

_custom = [d for d in os.getenv("TOPIC_DIRECTIONS_CUSTOM", "").split("||") if d.strip()]
_all_directions = _ALL_TOPIC_DIRECTIONS + _custom
_enabled = os.getenv("TOPIC_DIRECTIONS_ENABLED", "")
_TOPIC_DIRECTIONS = (
    [d for d in _all_directions if d in _enabled.split("||")]
    if _enabled else _all_directions
)
_topic_index = 0


def _pick_topic_direction() -> str:
    global _topic_index
    directions = _TOPIC_DIRECTIONS if _TOPIC_DIRECTIONS else _ALL_TOPIC_DIRECTIONS
    direction = directions[_topic_index % len(directions)]
    _topic_index += 1
    return direction


async def auto_topic(clients: list[TelegramClient]):
    """定时随机挑一个角色发起话题"""
    interval = int(os.getenv("TOPIC_INTERVAL", 1800))  # 默认30分钟
    await asyncio.sleep(TOPIC_START_DELAY)  # 启动后先等一会儿
    while True:
        character = random.choice(CHARACTERS)
        client = clients[CHARACTERS.index(character)]

        msg = await generate_with_retry(
            character=character,
            history=chat_history,
            mode="topic",
            user_content=(
                f"从以下话题方向中随机选一个（今天选：{_pick_topic_direction()}），"
                "用你的风格自然说出来，像随口一句，不要像提问模板。"
            ),
            max_tokens=120,
        )
        msg = strip_character_prefix(msg, character)
        if not msg:
            log_strategy("topic_skipped", character=character["name"], topic_seed="ai_generated")
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
            topic_seed="ai_generated",
            text=msg,
        )
        await asyncio.sleep(interval)


async def main():
    # ── Session 启动检查 ──────────────────────────────────────────
    validate_no_duplicate_phones(CHARACTERS)

    orphaned = cleanup_orphaned_sessions(CHARACTERS)
    if orphaned:
        print(f"已清理 {len(orphaned)} 个孤立 session 文件：")
        for f in orphaned:
            print(f"  删除：{f}")

    # ─────────────────────────────────────────────────────────────
    print("正在登录所有角色...")
    clients = []
    proxy = build_proxy()
    for character in CHARACTERS:
        preview_client = TelegramClient(character["session_file"], API_ID, API_HASH, proxy=proxy)
        try:
            login_identity = await resolve_login_identity(preview_client, character)
        finally:
            await preview_client.disconnect()

        print(f"开始登录 {login_identity}")
        client = await login_character(character)
        me = await client.get_me()
        clients.append(client)

    print(f"\n所有角色已就绪，监听群 {GROUP_ID} 中...\n")
    await asyncio.gather(
        *[c.run_until_disconnected() for c in clients],
        auto_topic(clients),
        reply_coordinator(clients),
    )


if __name__ == "__main__":
    asyncio.run(main())
