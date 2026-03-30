import streamlit as st
import subprocess
import os
import signal
import time
import psutil
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
            f.write(f"{k}={v}\n")


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
        ["python", "-u", "main.py"],  # -u 关闭输出缓冲，日志实时写入
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


# ── Telegram 配置 ──────────────────────────────────────
st.header("1. Telegram 配置")
col1, col2 = st.columns(2)
with col1:
    api_id = st.text_input("API ID", value=env.get("TELEGRAM_API_ID", ""))
with col2:
    api_hash = st.text_input("API Hash", value=env.get("TELEGRAM_API_HASH", ""), type="password")

group_id = st.text_input("群组 ID（负数，如 -1002278401337）", value=env.get("TELEGRAM_GROUP_ID", ""))

# ── AI 配置 ────────────────────────────────────────────
st.header("2. AI 配置")
provider = st.selectbox("选择 AI 服务", ["Groq（免费）", "Gemini（免费）", "DeepSeek", "OpenAI", "Claude", "自定义"])

PROVIDER_MAP = {
    "Groq（免费）": ("https://api.groq.com/openai/v1", "llama-3.3-70b-versatile"),
    "Gemini（免费）": ("https://generativelanguage.googleapis.com/v1beta/openai/", "gemini-2.0-flash"),
    "DeepSeek": ("https://api.deepseek.com", "deepseek-chat"),
    "OpenAI": ("https://api.openai.com/v1", "gpt-4o-mini"),
    "Claude": ("https://api.anthropic.com/v1/", "claude-sonnet-4-6"),
    "自定义": ("", ""),
}

default_url, default_model = PROVIDER_MAP[provider]
ai_key = st.text_input("API Key", value=env.get("AI_API_KEY", ""), type="password")

if provider == "自定义":
    ai_url = st.text_input("Base URL", value=env.get("AI_BASE_URL", ""))
    ai_model = st.text_input("模型名", value=env.get("AI_MODEL", ""))
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
        {"name": "小明", "phone": env.get("CHARACTER_XIAOMING_PHONE", ""), "system": env.get("CHARACTER_XIAOMING_SYSTEM", "25岁打工人，嘴欠爱吐槽，说话简短口语化。")},
        {"name": "老王", "phone": env.get("CHARACTER_LAOWANG_PHONE", ""), "system": env.get("CHARACTER_LAOWANG_SYSTEM", "28岁老油条，冷静毒舌，一句话戳心窝。")},
    ]

if "characters" not in st.session_state:
    st.session_state.characters = _saved_chars

# 添加角色按钮
if st.button("+ 添加角色"):
    st.session_state.characters.append({"name": f"角色{len(st.session_state.characters)+1}", "phone": "", "system": ""})
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
        chars_input.append({"name": name, "phone": phone, "system": system})

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

# ── 保存 & 启动 ────────────────────────────────────────
st.divider()
col1, col2, col3 = st.columns(3)

with col1:
    if st.button("💾 保存配置", use_container_width=True):
        data = {
            "TELEGRAM_API_ID": api_id,
            "TELEGRAM_API_HASH": api_hash,
            "TELEGRAM_GROUP_ID": group_id,
            "AI_API_KEY": ai_key,
            "AI_BASE_URL": ai_url,
            "AI_MODEL": ai_model,
            "CHARACTERS_JSON": _json.dumps(chars_input, ensure_ascii=False),
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

        st.session_state.characters = chars_input
        save_env(data)
        st.success("配置已保存！")

with col2:
    if st.button("▶ 启动机器人", use_container_width=True, type="primary"):
        if is_running():
            st.warning("机器人已在运行中")
        else:
            start_bot()
            st.success("机器人已启动！")

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

    col1, col2, col3 = st.columns([1, 1, 3])
    with col1:
        st.button("刷新日志")
    with col2:
        auto_refresh = st.checkbox("自动刷新", value=False)
    with col3:
        refresh_interval = st.number_input("间隔（秒）", value=5, min_value=1, max_value=60, label_visibility="collapsed" if not auto_refresh else "visible")

    if os.path.exists(log_path):
        lines = open(log_path, encoding="utf-8", errors="replace").readlines()
        st.code("".join(lines[-50:]), language="text")
    else:
        st.info("暂无日志")

    if auto_refresh:
        time.sleep(refresh_interval)
        st.rerun()
