import streamlit as st
import subprocess
import os
import signal
import time
import asyncio
import sys
import uuid
import json
import psutil
import socks
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from dotenv import dotenv_values

ENV_FILE = ".env"
PID_FILE = ".bot.pid"

st.set_page_config(page_title="Telegram AI 群聊配置", layout="centered")
st.title("Telegram AI 群聊配置")

# 读取现有 .env
env = dotenv_values(ENV_FILE) if os.path.exists(ENV_FILE) else {}


def save_env(data: dict):
    with open(ENV_FILE, "w", encoding="utf-8") as f:
        for k, v in data.items():
            encoded = json.dumps("" if v is None else str(v), ensure_ascii=False)
            f.write(f"{k}={encoded}\n")


def load_current_env() -> dict:
    return dict(dotenv_values(ENV_FILE)) if os.path.exists(ENV_FILE) else {}


def safe_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def is_running():
    if not os.path.exists(PID_FILE):
        return False
    try:
        pid = int(open(PID_FILE).read().strip())
        return psutil.pid_exists(pid)
    except Exception:
        return False


def start_bot():
    log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chat.log")
    proc = subprocess.Popen(
        [sys.executable, "-u", "main.py"],  # 使用当前解释器，避免 venv 漂移
        stdout=open(log_path, "a", encoding="utf-8"),
        stderr=subprocess.STDOUT,
        cwd=os.path.dirname(os.path.abspath(__file__)),
    )
    with open(PID_FILE, "w") as f:
        f.write(str(proc.pid))


def stop_bot():
    if not os.path.exists(PID_FILE):
        return
    try:
        pid = int(open(PID_FILE).read().strip())
        parent = psutil.Process(pid)
        for child in parent.children(recursive=True):
            child.kill()
        parent.kill()
    except Exception:
        pass
    os.remove(PID_FILE)


def session_file_for_character(name: str) -> str:
    safe_name = (name or "角色").replace("/", "_").replace("\\", "_").strip()
    return os.path.join("sessions", f"{safe_name}.session")


def ensure_character_ids(characters: list[dict]) -> list[dict]:
    normalized = []
    used_ids = set()
    for i, char in enumerate(characters):
        item = dict(char)
        base_id = (item.get("id") or item.get("name") or f"角色{i+1}").strip() or f"角色{i+1}"
        candidate_id = base_id
        suffix = 2
        while candidate_id in used_ids:
            candidate_id = f"{base_id}_{suffix}"
            suffix += 1
        item["id"] = candidate_id
        used_ids.add(candidate_id)
        normalized.append(item)
    return normalized


def build_proxy(proxy_host: str, proxy_port: str):
    if proxy_host and proxy_port:
        try:
            return (socks.SOCKS5, proxy_host, int(proxy_port))
        except ValueError as exc:
            raise ValueError("代理端口必须是数字") from exc
    return None


def format_account_name(me, fallback: str) -> str:
    return me.first_name or me.username or fallback


def normalize_base_url(url: str) -> str:
    return (url or "").rstrip("/")


def build_form_data(
    *,
    api_id: str,
    api_hash: str,
    group_id: str,
    ai_key: str,
    ai_url: str,
    ai_model: str,
    characters: list[dict],
    always_reply: bool,
    delay_min: int,
    delay_max: int,
    cooldown_human: int,
    cooldown_ai: int,
    topic_interval: int,
    topic_start: int,
    topic_directions: list[str],
    custom_list: list[str],
    use_proxy: bool,
    proxy_host: str,
    proxy_port: str,
) -> tuple[dict, list[dict]]:
    normalized_characters = ensure_character_ids(characters)
    current_env = load_current_env()
    data = {
        **current_env,
        "TELEGRAM_API_ID": api_id,
        "TELEGRAM_API_HASH": api_hash,
        "TELEGRAM_GROUP_ID": group_id,
        "AI_API_KEY": ai_key,
        "AI_BASE_URL": ai_url,
        "AI_MODEL": ai_model,
        "CHARACTERS_JSON": _json.dumps(normalized_characters, ensure_ascii=False),
        "ALWAYS_REPLY": "true" if always_reply else "false",
        "REPLY_DELAY_MIN": str(delay_min),
        "REPLY_DELAY_MAX": str(delay_max),
        "MIN_SECONDS_BETWEEN_REPLIES_HUMAN": str(cooldown_human),
        "MIN_SECONDS_BETWEEN_REPLIES_CHARACTER": str(cooldown_ai),
        "TOPIC_INTERVAL": str(topic_interval),
        "TOPIC_START_DELAY": str(topic_start),
        "TOPIC_DIRECTIONS_ENABLED": "||".join(topic_directions) if topic_directions else "",
        "TOPIC_DIRECTIONS_CUSTOM": "||".join(custom_list),
    }
    if use_proxy:
        data["PROXY_HOST"] = proxy_host
        data["PROXY_PORT"] = proxy_port
    else:
        data["PROXY_HOST"] = ""
        data["PROXY_PORT"] = ""
    return data, normalized_characters


def persist_form_state(
    *,
    api_id: str,
    api_hash: str,
    group_id: str,
    ai_key: str,
    ai_url: str,
    ai_model: str,
    characters: list[dict],
    always_reply: bool,
    delay_min: int,
    delay_max: int,
    cooldown_human: int,
    cooldown_ai: int,
    topic_interval: int,
    topic_start: int,
    topic_directions: list[str],
    custom_list: list[str],
    use_proxy: bool,
    proxy_host: str,
    proxy_port: str,
) -> list[dict]:
    data, normalized_characters = build_form_data(
        api_id=api_id,
        api_hash=api_hash,
        group_id=group_id,
        ai_key=ai_key,
        ai_url=ai_url,
        ai_model=ai_model,
        characters=characters,
        always_reply=always_reply,
        delay_min=delay_min,
        delay_max=delay_max,
        cooldown_human=cooldown_human,
        cooldown_ai=cooldown_ai,
        topic_interval=topic_interval,
        topic_start=topic_start,
        topic_directions=topic_directions,
        custom_list=custom_list,
        use_proxy=use_proxy,
        proxy_host=proxy_host,
        proxy_port=proxy_port,
    )
    st.session_state.characters = normalized_characters
    save_env(data)
    return normalized_characters


async def get_login_status(api_id: str, api_hash: str, proxy_host: str, proxy_port: str, character: dict) -> dict:
    client = TelegramClient(session_file_for_character(character["id"]), int(api_id), api_hash, proxy=build_proxy(proxy_host, proxy_port))
    try:
        await client.connect()
        me = await client.get_me()
        if me is None:
            return {"ok": False, "label": "未登录"}
        return {"ok": True, "label": f"已登录：{format_account_name(me, character['name'])}"}
    finally:
        await client.disconnect()


async def send_login_code(api_id: str, api_hash: str, proxy_host: str, proxy_port: str, character: dict) -> dict:
    client = TelegramClient(session_file_for_character(character["id"]), int(api_id), api_hash, proxy=build_proxy(proxy_host, proxy_port))
    try:
        await client.connect()
        me = await client.get_me()
        if me is not None:
            return {"status": "already", "account": format_account_name(me, character["name"])}
        sent = await client.send_code_request(character["phone"])
        return {"status": "code_sent", "phone_code_hash": sent.phone_code_hash}
    finally:
        await client.disconnect()


async def complete_login(api_id: str, api_hash: str, proxy_host: str, proxy_port: str, character: dict, code: str, phone_code_hash: str, password: str) -> dict:
    client = TelegramClient(session_file_for_character(character["id"]), int(api_id), api_hash, proxy=build_proxy(proxy_host, proxy_port))
    try:
        await client.connect()
        try:
            me = await client.sign_in(
                phone=character["phone"],
                code=code,
                phone_code_hash=phone_code_hash,
            )
        except SessionPasswordNeededError:
            if not password:
                return {"status": "password_required"}
            me = await client.sign_in(password=password)
        return {"status": "success", "account": format_account_name(me, character["name"])}
    finally:
        await client.disconnect()


async def all_characters_logged_in(api_id: str, api_hash: str, proxy_host: str, proxy_port: str, characters: list[dict]) -> tuple[bool, list[str]]:
    missing = []
    for char in characters:
        status = await get_login_status(api_id, api_hash, proxy_host, proxy_port, char)
        if not status["ok"]:
            missing.append(char["name"])
    return len(missing) == 0, missing


async def fetch_group_choices(api_id: str, api_hash: str, proxy_host: str, proxy_port: str, characters: list[dict]):
    if not api_id or not api_hash:
        raise ValueError("请先填写 Telegram API ID 和 API Hash")

    proxy = build_proxy(proxy_host, proxy_port)

    errors = []
    merged_groups = {}
    for char in characters:
        session_file = session_file_for_character(char.get("id", "").strip())
        if not os.path.exists(session_file):
            continue

        client = TelegramClient(session_file, int(api_id), api_hash, proxy=proxy)
        try:
            await client.connect()
            me = await client.get_me()
            if me is None:
                errors.append(f"{char.get('name', '未命名角色')} 未登录")
                continue

            found_for_account = False
            async for dialog in client.iter_dialogs():
                if getattr(dialog, "is_group", False) or getattr(dialog, "is_channel", False):
                    found_for_account = True
                    existing = merged_groups.get(dialog.id)
                    account_name = format_account_name(me, char.get("name", "未知账号"))
                    if existing:
                        if account_name not in existing["accounts"]:
                            existing["accounts"].append(account_name)
                        continue
                    merged_groups[dialog.id] = {
                        "id": dialog.id,
                        "name": dialog.name,
                        "type": "群组" if getattr(dialog, "is_group", False) else "频道/超级群",
                        "accounts": [account_name],
                    }

            if not found_for_account:
                errors.append(f"{format_account_name(me, char.get('name', '未知账号'))} 下未找到群组")
        except Exception as exc:
            errors.append(f"{char.get('name', '未命名角色')}: {exc}")
        finally:
            await client.disconnect()

    if merged_groups:
        return sorted(merged_groups.values(), key=lambda item: (item["name"] or "", str(item["id"])))

    detail = "；".join(errors) if errors else "没有找到可用的已登录会话"
    raise RuntimeError(detail)


# ── Telegram 配置 ──────────────────────────────────────
st.header("1. Telegram 配置")
col1, col2 = st.columns(2)
with col1:
    api_id = st.text_input("API ID", value=env.get("TELEGRAM_API_ID", ""))
with col2:
    api_hash = st.text_input("API Hash", value=env.get("TELEGRAM_API_HASH", ""), type="password")

if "group_id_input" not in st.session_state:
    st.session_state.group_id_input = env.get("TELEGRAM_GROUP_ID", "")

group_id = st.text_input("群组 ID（负数，如 -1002278401337）", key="group_id_input")

# ── AI 配置 ────────────────────────────────────────────
st.header("2. AI 配置")
PROVIDER_MAP = {
    "Groq（免费）": ("https://api.groq.com/openai/v1", "llama-3.3-70b-versatile"),
    "Gemini（免费）": ("https://generativelanguage.googleapis.com/v1beta/openai/", "gemini-2.0-flash"),
    "DeepSeek": ("https://api.deepseek.com", "deepseek-chat"),
    "OpenAI": ("https://api.openai.com/v1", "gpt-4o-mini"),
    "Claude": ("https://api.anthropic.com/v1/", "claude-sonnet-4-6"),
    "自定义": ("", ""),
}

saved_ai_url = env.get("AI_BASE_URL", "")
saved_ai_model = env.get("AI_MODEL", "")
provider_options = list(PROVIDER_MAP.keys())
initial_provider = "自定义"
for label, (candidate_url, candidate_model) in PROVIDER_MAP.items():
    if label == "自定义":
        continue
    if normalize_base_url(saved_ai_url) == normalize_base_url(candidate_url) and saved_ai_model == candidate_model:
        initial_provider = label
        break

provider = st.selectbox(
    "选择 AI 服务",
    provider_options,
    index=provider_options.index(initial_provider),
)

default_url, default_model = PROVIDER_MAP[provider]
ai_key = st.text_input("API Key", value=env.get("AI_API_KEY", ""), type="password")

if provider == "自定义":
    ai_url = st.text_input("Base URL", value=saved_ai_url)
    ai_model = st.text_input("模型名", value=saved_ai_model)
else:
    ai_url = default_url
    ai_model = default_model
    st.caption(f"Base URL: `{ai_url}`　模型: `{ai_model}`")

# ── 代理配置 ───────────────────────────────────────────
st.header("3. 代理配置（国内必填）")
use_proxy = st.checkbox("使用代理", value=bool(env.get("PROXY_HOST")))
if use_proxy:
    col1, col2 = st.columns(2)
    with col1:
        proxy_host = st.text_input("代理地址", value=env.get("PROXY_HOST", "127.0.0.1"))
    with col2:
        proxy_port = st.text_input("端口", value=env.get("PROXY_PORT", "50656"))
else:
    proxy_host = proxy_port = ""

# ── 角色配置 ───────────────────────────────────────────
st.header("4. 角色配置")

import json as _json

# 从 .env 读取角色列表
_chars_json = env.get("CHARACTERS_JSON", "")
try:
    _saved_chars = _json.loads(_chars_json) if _chars_json else []
except Exception:
    _saved_chars = []

if not _saved_chars:
    _saved_chars = [
        {"id": "小明", "name": "小明", "phone": env.get("CHARACTER_XIAOMING_PHONE", ""), "system": env.get("CHARACTER_XIAOMING_SYSTEM", "25岁打工人，嘴欠爱吐槽，说话简短口语化。")},
        {"id": "老王", "name": "老王", "phone": env.get("CHARACTER_LAOWANG_PHONE", ""), "system": env.get("CHARACTER_LAOWANG_SYSTEM", "28岁老油条，冷静毒舌，一句话戳心窝。")},
    ]

_saved_chars = ensure_character_ids(_saved_chars)

if "characters" not in st.session_state:
    st.session_state.characters = _saved_chars

# 添加角色按钮
if st.button("+ 添加角色"):
    new_name = f"角色{len(st.session_state.characters)+1}"
    st.session_state.characters.append({"id": f"{new_name}_{uuid.uuid4().hex[:8]}", "name": new_name, "phone": "", "system": ""})
    st.rerun()

chars_input = []
for i, char in enumerate(st.session_state.characters):
    with st.expander(f"角色 {i+1}：{char.get('name', '')}", expanded=True):
        col1, col2, col3 = st.columns([2, 3, 1])
        with col1:
            name = st.text_input("角色名", value=char.get("name", ""), key=f"name_{i}")
        with col2:
            phone = st.text_input("手机号", value=char.get("phone", ""), key=f"phone_{i}", placeholder="+8613800000001")
        with col3:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("删除", key=f"del_{i}", disabled=len(st.session_state.characters) <= 1):
                st.session_state.characters.pop(i)
                st.rerun()
        system = st.text_area("性格描述", value=char.get("system", ""), key=f"system_{i}", height=100)
        char_id = char.get("id") or (name.strip() if name.strip() else f"角色{i+1}")
        chars_input.append({"id": char_id, "name": name, "phone": phone, "system": system})

# ── 回复行为配置 ───────────────────────────────────────
st.header("5. 回复行为")

always_reply = st.toggle(
    "每条消息都回复",
    value=env.get("ALWAYS_REPLY", "true") == "true",
    help="开启后两个角色会回复每一条消息；关闭后按概率随机决定是否回复"
)

col1, col2 = st.columns(2)
with col1:
    delay_min = st.number_input("回复最短延迟（秒）", value=safe_int(env.get("REPLY_DELAY_MIN"), 5), min_value=0,
                                 help="收到消息后最少等多久再回，模拟真人思考")
with col2:
    delay_max = st.number_input("回复最长延迟（秒）", value=safe_int(env.get("REPLY_DELAY_MAX"), 15), min_value=0,
                                 help="收到消息后最多等多久再回")

col1, col2 = st.columns(2)
with col1:
    cooldown_human = st.number_input(
        "回复真人的冷却时间（秒）",
        value=safe_int(env.get("MIN_SECONDS_BETWEEN_REPLIES_HUMAN"), 30),
        min_value=0,
        help="同一角色两次回复真人之间的最短间隔"
    )
with col2:
    cooldown_ai = st.number_input(
        "角色互聊的冷却时间（秒）",
        value=safe_int(env.get("MIN_SECONDS_BETWEEN_REPLIES_CHARACTER"), 5),
        min_value=0,
        help="两个AI角色互相回复之间的最短间隔，越小对话越连贯"
    )

# ── 话题配置 ───────────────────────────────────────────
st.header("6. 自动发话题")
col1, col2 = st.columns(2)
with col1:
    topic_interval = st.number_input("发话题间隔（秒）", value=safe_int(env.get("TOPIC_INTERVAL"), 1800), min_value=60,
                                      help="无人说话时多久自动发起一个新话题，1800=30分钟")
with col2:
    topic_start = st.number_input("启动后多久发第一个话题（秒）", value=safe_int(env.get("TOPIC_START_DELAY"), 30), min_value=5)

ALL_DIRECTIONS = [
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
saved_enabled = env.get("TOPIC_DIRECTIONS_ENABLED", "")
saved_list = saved_enabled.split("||") if saved_enabled else ALL_DIRECTIONS

# 用户自定义话题（保存在 .env 里，用 || 分隔）
saved_custom = env.get("TOPIC_DIRECTIONS_CUSTOM", "")
custom_list = [d for d in saved_custom.split("||") if d.strip()] if saved_custom else []

# 合并预设 + 自定义，构成完整选项列表
all_options = ALL_DIRECTIONS + custom_list

col1, col2 = st.columns([4, 1])
with col1:
    new_direction = st.text_input("添加自定义话题方向", placeholder="如：健身、减肥、运动", label_visibility="visible")
with col2:
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("添加", use_container_width=True):
        if new_direction.strip() and new_direction.strip() not in all_options:
            custom_list.append(new_direction.strip())
            all_options = ALL_DIRECTIONS + custom_list
            st.rerun()

topic_directions = st.multiselect(
    "话题方向（勾选后 AI 只在这些范围内轮换）",
    options=all_options,
    default=[d for d in saved_list if d in all_options],
    help="至少选一个，不选则使用全部"
)

st.header("7. 账号登录")
for char in ensure_character_ids(chars_input):
    char_id = char["id"]
    login_state_key = f"login_status_{char_id}"
    code_hash_key = f"code_hash_{char_id}"
    code_input_key = f"code_input_{char_id}"
    password_input_key = f"password_input_{char_id}"

    with st.expander(f"登录：{char['name']}", expanded=False):
        st.caption(f"Session: `{session_file_for_character(char_id)}`")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("检查登录状态", key=f"check_login_{char_id}", use_container_width=True):
                try:
                    normalized_chars = persist_form_state(
                        api_id=api_id,
                        api_hash=api_hash,
                        group_id=group_id,
                        ai_key=ai_key,
                        ai_url=ai_url,
                        ai_model=ai_model,
                        characters=chars_input,
                        always_reply=always_reply,
                        delay_min=delay_min,
                        delay_max=delay_max,
                        cooldown_human=cooldown_human,
                        cooldown_ai=cooldown_ai,
                        topic_interval=topic_interval,
                        topic_start=topic_start,
                        topic_directions=topic_directions,
                        custom_list=custom_list,
                        use_proxy=use_proxy,
                        proxy_host=proxy_host,
                        proxy_port=proxy_port,
                    )
                    current_character = next(item for item in normalized_chars if item["id"] == char_id)
                    st.session_state[login_state_key] = asyncio.run(
                        get_login_status(api_id, api_hash, proxy_host, proxy_port, current_character)
                    )["label"]
                except Exception as e:
                    st.session_state[login_state_key] = f"检查失败：{e}"
        with col2:
            if st.button("发送验证码", key=f"send_code_{char_id}", use_container_width=True):
                try:
                    normalized_chars = persist_form_state(
                        api_id=api_id,
                        api_hash=api_hash,
                        group_id=group_id,
                        ai_key=ai_key,
                        ai_url=ai_url,
                        ai_model=ai_model,
                        characters=chars_input,
                        always_reply=always_reply,
                        delay_min=delay_min,
                        delay_max=delay_max,
                        cooldown_human=cooldown_human,
                        cooldown_ai=cooldown_ai,
                        topic_interval=topic_interval,
                        topic_start=topic_start,
                        topic_directions=topic_directions,
                        custom_list=custom_list,
                        use_proxy=use_proxy,
                        proxy_host=proxy_host,
                        proxy_port=proxy_port,
                    )
                    current_character = next(item for item in normalized_chars if item["id"] == char_id)
                    result = asyncio.run(
                        send_login_code(api_id, api_hash, proxy_host, proxy_port, current_character)
                    )
                    if result["status"] == "already":
                        st.session_state[login_state_key] = f"已登录：{result['account']}"
                        st.session_state.pop(code_hash_key, None)
                    else:
                        st.session_state[code_hash_key] = result["phone_code_hash"]
                        st.session_state[login_state_key] = "验证码已发送"
                except Exception as e:
                    st.session_state[login_state_key] = f"发送失败：{e}"

        st.caption(st.session_state.get(login_state_key, "未检查"))

        if st.session_state.get(code_hash_key):
            st.text_input("验证码", key=code_input_key, placeholder="输入 Telegram 发来的验证码")
            st.text_input("二步验证密码", key=password_input_key, type="password", placeholder="若未开启可留空")
            if st.button("完成登录", key=f"finish_login_{char_id}", use_container_width=True):
                try:
                    normalized_chars = persist_form_state(
                        api_id=api_id,
                        api_hash=api_hash,
                        group_id=group_id,
                        ai_key=ai_key,
                        ai_url=ai_url,
                        ai_model=ai_model,
                        characters=chars_input,
                        always_reply=always_reply,
                        delay_min=delay_min,
                        delay_max=delay_max,
                        cooldown_human=cooldown_human,
                        cooldown_ai=cooldown_ai,
                        topic_interval=topic_interval,
                        topic_start=topic_start,
                        topic_directions=topic_directions,
                        custom_list=custom_list,
                        use_proxy=use_proxy,
                        proxy_host=proxy_host,
                        proxy_port=proxy_port,
                    )
                    current_character = next(item for item in normalized_chars if item["id"] == char_id)
                    result = asyncio.run(
                        complete_login(
                            api_id,
                            api_hash,
                            proxy_host,
                            proxy_port,
                            current_character,
                            st.session_state.get(code_input_key, "").strip(),
                            st.session_state.get(code_hash_key, ""),
                            st.session_state.get(password_input_key, "").strip(),
                        )
                    )
                    if result["status"] == "password_required":
                        st.session_state[login_state_key] = "该账号已开启二步验证，请输入密码后再试"
                    else:
                        st.session_state[login_state_key] = f"已登录：{result['account']}"
                        st.session_state.pop(code_hash_key, None)
                except Exception as e:
                    st.session_state[login_state_key] = f"登录失败：{e}"

with st.expander("快速查看已登录群组 ID"):
    st.caption("读取当前已登录 Telegram 账号可见的群组，并可一键填入上面的群组 ID")
    if st.button("读取群组列表", use_container_width=True):
        try:
            normalized_chars = persist_form_state(
                api_id=api_id,
                api_hash=api_hash,
                group_id=group_id,
                ai_key=ai_key,
                ai_url=ai_url,
                ai_model=ai_model,
                characters=chars_input,
                always_reply=always_reply,
                delay_min=delay_min,
                delay_max=delay_max,
                cooldown_human=cooldown_human,
                cooldown_ai=cooldown_ai,
                topic_interval=topic_interval,
                topic_start=topic_start,
                topic_directions=topic_directions,
                custom_list=custom_list,
                use_proxy=use_proxy,
                proxy_host=proxy_host,
                proxy_port=proxy_port,
            )
            st.session_state.group_choices = asyncio.run(
                fetch_group_choices(
                    api_id=api_id,
                    api_hash=api_hash,
                    proxy_host=proxy_host,
                    proxy_port=proxy_port,
                    characters=normalized_chars,
                )
            )
            st.success(f"已读取到 {len(st.session_state.group_choices)} 个群组")
        except Exception as e:
            st.session_state.group_choices = []
            st.error(f"读取失败：{e}")

    for idx, item in enumerate(st.session_state.get("group_choices", [])):
        col1, col2 = st.columns([5, 1])
        with col1:
            st.write(f"**{item['name']}**")
            st.caption(f"ID: `{item['id']}` | 类型: {item['type']} | 账号: {', '.join(item['accounts'])}")
        with col2:
            if st.button("使用", key=f"use_group_{idx}", use_container_width=True):
                st.session_state.group_id_input = str(item["id"])
                persist_form_state(
                    api_id=api_id,
                    api_hash=api_hash,
                    group_id=str(item["id"]),
                    ai_key=ai_key,
                    ai_url=ai_url,
                    ai_model=ai_model,
                    characters=chars_input,
                    always_reply=always_reply,
                    delay_min=delay_min,
                    delay_max=delay_max,
                    cooldown_human=cooldown_human,
                    cooldown_ai=cooldown_ai,
                    topic_interval=topic_interval,
                    topic_start=topic_start,
                    topic_directions=topic_directions,
                    custom_list=custom_list,
                    use_proxy=use_proxy,
                    proxy_host=proxy_host,
                    proxy_port=proxy_port,
                )
                st.rerun()

# ── 保存 & 启动 ────────────────────────────────────────
st.divider()
col1, col2, col3 = st.columns(3)

with col1:
    if st.button("💾 保存配置", use_container_width=True):
        persist_form_state(
            api_id=api_id,
            api_hash=api_hash,
            group_id=group_id,
            ai_key=ai_key,
            ai_url=ai_url,
            ai_model=ai_model,
            characters=chars_input,
            always_reply=always_reply,
            delay_min=delay_min,
            delay_max=delay_max,
            cooldown_human=cooldown_human,
            cooldown_ai=cooldown_ai,
            topic_interval=topic_interval,
            topic_start=topic_start,
            topic_directions=topic_directions,
            custom_list=custom_list,
            use_proxy=use_proxy,
            proxy_host=proxy_host,
            proxy_port=proxy_port,
        )
        st.success("配置已保存！")

with col2:
    if st.button("▶ 启动机器人", use_container_width=True, type="primary"):
        if is_running():
            st.warning("机器人已在运行中")
        else:
            try:
                normalized_chars = persist_form_state(
                    api_id=api_id,
                    api_hash=api_hash,
                    group_id=group_id,
                    ai_key=ai_key,
                    ai_url=ai_url,
                    ai_model=ai_model,
                    characters=chars_input,
                    always_reply=always_reply,
                    delay_min=delay_min,
                    delay_max=delay_max,
                    cooldown_human=cooldown_human,
                    cooldown_ai=cooldown_ai,
                    topic_interval=topic_interval,
                    topic_start=topic_start,
                    topic_directions=topic_directions,
                    custom_list=custom_list,
                    use_proxy=use_proxy,
                    proxy_host=proxy_host,
                    proxy_port=proxy_port,
                )
                all_ready, missing = asyncio.run(
                    all_characters_logged_in(api_id, api_hash, proxy_host, proxy_port, normalized_chars)
                )
                if not all_ready:
                    st.error(f"以下角色尚未登录，先在页面里完成验证码登录：{', '.join(missing)}")
                else:
                    start_bot()
                    st.success("机器人已启动！")
            except Exception as e:
                st.error(f"启动前检查失败：{e}")

with col3:
    if st.button("⏹ 停止机器人", use_container_width=True):
        if is_running():
            stop_bot()
            st.success("已停止")
        else:
            st.warning("机器人未在运行")

# ── 状态 & 日志 ────────────────────────────────────────
st.divider()
status = "🟢 运行中" if is_running() else "🔴 未运行"
st.markdown(f"**机器人状态：{status}**")

if st.checkbox("查看运行日志"):
    log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chat.log")

    col1, col2, col3, col4 = st.columns([1, 1, 1, 3])
    with col1:
        st.button("刷新日志")
    with col2:
        auto_refresh = st.checkbox("自动刷新", value=False)
    with col3:
        if st.button("清空日志", use_container_width=True):
            open(log_path, "w", encoding="utf-8").close()
            st.success("日志已清空")
    with col4:
        refresh_interval = st.number_input("间隔（秒）", value=5, min_value=1, max_value=60, label_visibility="collapsed" if not auto_refresh else "visible")

    if os.path.exists(log_path):
        lines = open(log_path, encoding="utf-8", errors="replace").readlines()
        st.code("".join(lines[-50:]), language="text")
    else:
        st.info("暂无日志")

    if auto_refresh:
        time.sleep(refresh_interval)
        st.rerun()
