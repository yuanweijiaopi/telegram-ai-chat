import streamlit as st
import subprocess
import os
import signal
import time
import asyncio
import sys
import uuid
import json
import threading
from datetime import datetime, time as dt_time
import psutil
import socks
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from dotenv import dotenv_values

ENV_FILE = ".env"
PID_FILE = ".bot.pid"
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))

st.set_page_config(page_title="Telegram AI 群聊配置", layout="centered")
st.title("Telegram AI 群聊配置")
st.caption("按顺序完成 4 步即可启动机器人；每一步都可以随时回来重新修改。")

notice = st.session_state.pop("app_notice", None)
if notice:
    icon = "✅" if notice["level"] == "success" else ("⚠️" if notice["level"] == "warning" else "❌")
    st.toast(notice["message"], icon=icon)

if "pending_new_topic_direction" in st.session_state:
    st.session_state["new_topic_direction"] = st.session_state.pop("pending_new_topic_direction")

# 读取现有 .env
env = dotenv_values(ENV_FILE) if os.path.exists(ENV_FILE) else {}


def save_env(data: dict):
    with open(ENV_FILE, "w", encoding="utf-8") as f:
        for k, v in data.items():
            encoded = json.dumps("" if v is None else str(v), ensure_ascii=False)
            f.write(f"{k}={encoded}\n")


def load_current_env() -> dict:
    return dict(dotenv_values(ENV_FILE)) if os.path.exists(ENV_FILE) else {}


def set_app_notice(level: str, message: str) -> None:
    st.session_state.app_notice = {"level": level, "message": message}


def append_runtime_log(message: str) -> None:
    log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chat.log")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] {message}\n")


def add_custom_topic_direction() -> None:
    new_direction = (st.session_state.get("new_topic_direction") or "").strip()
    if not new_direction:
        return

    custom = list(st.session_state.get("custom_topic_directions", []))
    selected = list(st.session_state.get("topic_directions_selected", []))
    changed = False

    if new_direction not in custom:
        custom.append(new_direction)
        st.session_state.custom_topic_directions = custom
        changed = True

    if new_direction not in selected:
        selected.append(new_direction)
        st.session_state.topic_directions_selected = selected
        changed = True

    if changed:
        current_env = load_current_env()
        current_env["TOPIC_DIRECTIONS_CUSTOM"] = "||".join(custom)
        current_env["TOPIC_DIRECTIONS_ENABLED"] = "||".join(selected)
        save_env(current_env)
        set_app_notice("success", f"已添加话题：{new_direction}")

    # Streamlit 不允许在回调里直接改 widget key；用 pending 中转，下一轮渲染前清空输入框。
    st.session_state.pending_new_topic_direction = ""


def safe_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _read_pid_file() -> int | None:
    if not os.path.exists(PID_FILE):
        return None
    try:
        return int(open(PID_FILE).read().strip())
    except Exception:
        return None


def _write_pid_file(pid: int) -> None:
    with open(PID_FILE, "w") as f:
        f.write(str(pid))


def _remove_pid_file() -> None:
    if os.path.exists(PID_FILE):
        os.remove(PID_FILE)


def _is_project_bot_process(proc: psutil.Process) -> bool:
    try:
        if proc.pid == os.getpid():
            return False
        cmdline = proc.info.get("cmdline") if hasattr(proc, "info") else proc.cmdline()
        cwd = proc.info.get("cwd") if hasattr(proc, "info") else proc.cwd()
        cmdline = cmdline or []
        if not cmdline:
            return False
        if os.path.abspath(cwd or "") == PROJECT_DIR and any(part.endswith("main.py") or part == "main.py" for part in cmdline):
            return True
        main_path = os.path.join(PROJECT_DIR, "main.py")
        return any(os.path.abspath(part) == main_path for part in cmdline if part)
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return False


def _find_bot_processes() -> list[psutil.Process]:
    processes = []
    for proc in psutil.process_iter(["pid", "cmdline", "cwd"]):
        if _is_project_bot_process(proc):
            processes.append(proc)
    return processes


def is_running():
    pid = _read_pid_file()
    if pid is not None:
        try:
            proc = psutil.Process(pid)
            if _is_project_bot_process(proc):
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass

    bot_processes = _find_bot_processes()
    if bot_processes:
        _write_pid_file(bot_processes[0].pid)
        return True

    _remove_pid_file()
    return False


def start_bot():
    if is_running():
        return
    log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chat.log")
    proc = subprocess.Popen(
        [sys.executable, "-u", "main.py"],  # 使用当前解释器，避免 venv 漂移
        stdout=open(log_path, "a", encoding="utf-8"),
        stderr=subprocess.STDOUT,
        cwd=PROJECT_DIR,
    )
    _write_pid_file(proc.pid)


def stop_bot():
    seen_pids = set()
    targets: list[psutil.Process] = []

    pid = _read_pid_file()
    if pid is not None:
        try:
            proc = psutil.Process(pid)
            if _is_project_bot_process(proc):
                targets.append(proc)
                seen_pids.add(proc.pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass

    for proc in _find_bot_processes():
        if proc.pid not in seen_pids:
            targets.append(proc)
            seen_pids.add(proc.pid)

    for parent in targets:
        try:
            for child in parent.children(recursive=True):
                child.kill()
            parent.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass

    _remove_pid_file()


def parse_hhmm(value: str | None, default: str) -> dt_time:
    """解析 HH:MM 字符串；任何异常都退回到 default。"""
    for candidate in ((value or "").strip(), default):
        if not candidate:
            continue
        try:
            hour_str, minute_str = candidate.split(":", 1)
            return dt_time(hour=int(hour_str), minute=int(minute_str))
        except (ValueError, TypeError):
            continue
    return dt_time(hour=0, minute=0)


def normalize_time_value(value) -> str:
    if hasattr(value, "hour") and hasattr(value, "minute"):
        return f"{value.hour:02d}:{value.minute:02d}"
    return str(value or "").strip()


def _hhmm_to_minutes(value: dt_time) -> int:
    return value.hour * 60 + value.minute


def is_within_schedule_window(current_env: dict) -> bool:
    """根据 AUTO_SCHEDULE_* 配置判断当前时间是否落在开启窗口内。"""
    now = datetime.now()
    if current_env.get("AUTO_SCHEDULE_WEEKDAYS_ONLY", "false") == "true" and now.weekday() >= 5:
        return False

    start_minutes = _hhmm_to_minutes(parse_hhmm(current_env.get("AUTO_SCHEDULE_START"), "09:00"))
    stop_minutes = _hhmm_to_minutes(parse_hhmm(current_env.get("AUTO_SCHEDULE_STOP"), "23:00"))
    if start_minutes == stop_minutes:
        return False

    now_minutes = now.hour * 60 + now.minute
    if start_minutes < stop_minutes:
        return start_minutes <= now_minutes < stop_minutes
    # 跨午夜窗口，例如 22:00 → 06:00
    return now_minutes >= start_minutes or now_minutes < stop_minutes


def scheduler_loop() -> None:
    last_error = None
    while True:
        try:
            current_env = load_current_env()
            if current_env.get("AUTO_SCHEDULE_ENABLED", "false") == "true":
                should_run = is_within_schedule_window(current_env)
                running = is_running()
                if should_run and not running:
                    start_bot()
                    append_runtime_log("[定时任务] 到达开启时间，已自动启动机器人")
                elif not should_run and running:
                    stop_bot()
                    append_runtime_log("[定时任务] 到达关闭时间，已自动停止机器人")
            last_error = None
        except Exception as exc:
            error_signature = repr(exc)
            if last_error != error_signature:
                append_runtime_log(f"[定时任务] 调度器异常：{exc}")
                last_error = error_signature
        time.sleep(20)


@st.cache_resource
def ensure_scheduler_started():
    thread = threading.Thread(target=scheduler_loop, daemon=True, name="bot-scheduler")
    thread.start()
    return True


ensure_scheduler_started()


def session_file_for_character(name: str) -> str:
    safe_name = (name or "角色").replace("/", "_").replace("\\", "_").strip()
    sessions_dir = "sessions"
    os.makedirs(sessions_dir, exist_ok=True)
    return os.path.join(sessions_dir, f"{safe_name}.session")


def preferred_character_id(name: str, index: int) -> str:
    return (name or f"角色{index+1}").strip() or f"角色{index+1}"


def migrate_session_file(old_id: str, new_id: str) -> None:
    if not old_id or old_id == new_id:
        return
    old_path = session_file_for_character(old_id)
    new_path = session_file_for_character(new_id)
    if os.path.exists(old_path) and not os.path.exists(new_path):
        os.makedirs(os.path.dirname(new_path), exist_ok=True)
        os.rename(old_path, new_path)

    old_journal = f"{old_path}-journal"
    new_journal = f"{new_path}-journal"
    if os.path.exists(old_journal) and not os.path.exists(new_journal):
        os.rename(old_journal, new_journal)


def ensure_character_ids(characters: list[dict]) -> list[dict]:
    normalized = []
    used_ids = set()
    for i, char in enumerate(characters):
        item = dict(char)
        old_id = (item.get("id") or "").strip()
        base_id = preferred_character_id(item.get("name"), i)
        candidate_id = base_id
        suffix = 2
        while candidate_id in used_ids:
            candidate_id = f"{base_id}_{suffix}"
            suffix += 1
        migrate_session_file(old_id, candidate_id)
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


def format_phone_suffix(phone: str | None) -> str:
    value = (phone or "").strip()
    if len(value) >= 4:
        return value[-4:]
    return value or "未知"


def normalize_base_url(url: str) -> str:
    return (url or "").rstrip("/")


def summarize_basic_config(api_id: str, api_hash: str, ai_key: str, characters: list[dict]) -> str:
    if not api_id or not api_hash or not ai_key:
        return "待完善"
    if not characters:
        return "待完善"
    missing_character_fields = [
        char.get("name", f"角色{i+1}")
        for i, char in enumerate(characters)
        if not (char.get("name") or "").strip() or not (char.get("phone") or "").strip()
    ]
    if missing_character_fields:
        return f"待完善（缺少角色信息：{', '.join(missing_character_fields[:2])}）"
    return f"已完成（{len(characters)} 个角色）"


def summarize_login_step(characters: list[dict]) -> str:
    if not characters:
        return "待配置角色"
    confirmed = 0
    session_only = 0
    for char in characters:
        char_id = char.get("id", "")
        login_meta = st.session_state.get(f"login_meta_{char_id}")
        if login_meta and login_meta.get("ok"):
            confirmed += 1
            continue
        if os.path.exists(session_file_for_character(char_id)):
            session_only += 1
    if confirmed == len(characters):
        return f"已完成（{confirmed}/{len(characters)} 已确认登录）"
    if confirmed > 0 or session_only > 0:
        return f"进行中（已确认 {confirmed}/{len(characters)}，另有 {session_only} 个待检查）"
    return "未开始"


def summarize_group_step(group_id: str) -> str:
    if (group_id or "").strip():
        return f"已选择（{group_id.strip()}）"
    return "未选择"


def summarize_runtime_step() -> str:
    return "运行中" if is_running() else "待启动"


REPLY_STRATEGY_OPTIONS = {
    "random": "当前策略：随机分配",
    "round_robin": "轮流回复",
    "least_recent": "优先最近最久没发言",
}

INTERACTION_MODE_OPTIONS = {
    "mixed": "正常模式：会理真人，也会角色互聊",
    "character_only": "只让角色互聊，不理会真人",
}

REPLY_DELAY_MODE_OPTIONS = {
    "batch_pause": "整段回复前统一等待",
    "per_message": "每条发出前单独等待",
}


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
    reply_assignment_strategy: str,
    interaction_mode: str,
    reply_delay_mode: str | None = None,
    delay_min: int,
    delay_max: int,
    auto_schedule_enabled: bool | None = None,
    auto_schedule_start: str | None = None,
    auto_schedule_stop: str | None = None,
    auto_schedule_weekdays_only: bool | None = None,
    message_expiry_seconds: int,
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

    def _resolve_bool(flag: bool | None, env_key: str) -> str:
        """显式 True/False 优先；None 时退回 .env 中的旧值。"""
        if flag is None:
            return current_env.get(env_key, "false")
        return "true" if flag else "false"

    resolved_reply_delay_mode = reply_delay_mode or current_env.get("REPLY_DELAY_MODE", "batch_pause")
    resolved_auto_schedule_enabled = _resolve_bool(auto_schedule_enabled, "AUTO_SCHEDULE_ENABLED")
    resolved_auto_schedule_start = auto_schedule_start or current_env.get("AUTO_SCHEDULE_START", "09:00")
    resolved_auto_schedule_stop = auto_schedule_stop or current_env.get("AUTO_SCHEDULE_STOP", "23:00")
    resolved_auto_schedule_weekdays_only = _resolve_bool(
        auto_schedule_weekdays_only, "AUTO_SCHEDULE_WEEKDAYS_ONLY"
    )
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
        "REPLY_ASSIGNMENT_STRATEGY": reply_assignment_strategy,
        "INTERACTION_MODE": interaction_mode,
        "REPLY_DELAY_MODE": resolved_reply_delay_mode,
        "REPLY_DELAY_MIN": str(delay_min),
        "REPLY_DELAY_MAX": str(delay_max),
        "AUTO_SCHEDULE_ENABLED": resolved_auto_schedule_enabled,
        "AUTO_SCHEDULE_START": resolved_auto_schedule_start,
        "AUTO_SCHEDULE_STOP": resolved_auto_schedule_stop,
        "AUTO_SCHEDULE_WEEKDAYS_ONLY": resolved_auto_schedule_weekdays_only,
        "MESSAGE_EXPIRY_SECONDS": str(message_expiry_seconds),
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
    reply_assignment_strategy: str,
    interaction_mode: str,
    reply_delay_mode: str | None = None,
    delay_min: int,
    delay_max: int,
    auto_schedule_enabled: bool | None = None,
    auto_schedule_start: str | None = None,
    auto_schedule_stop: str | None = None,
    auto_schedule_weekdays_only: bool | None = None,
    message_expiry_seconds: int,
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
        reply_assignment_strategy=reply_assignment_strategy,
        interaction_mode=interaction_mode,
        reply_delay_mode=reply_delay_mode,
        delay_min=delay_min,
        delay_max=delay_max,
        auto_schedule_enabled=auto_schedule_enabled,
        auto_schedule_start=auto_schedule_start,
        auto_schedule_stop=auto_schedule_stop,
        auto_schedule_weekdays_only=auto_schedule_weekdays_only,
        message_expiry_seconds=message_expiry_seconds,
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
            return {"ok": False, "label": "未登录", "account": None, "phone": None, "match": False}
        me_phone = getattr(me, "phone", None)
        expected_phone = (character.get("phone") or "").replace("+", "").strip()
        actual_phone = (me_phone or "").replace("+", "").strip()
        is_match = bool(expected_phone) and bool(actual_phone) and expected_phone == actual_phone
        return {
            "ok": True,
            "label": f"已登录：{format_account_name(me, character['name'])}",
            "account": format_account_name(me, character["name"]),
            "phone": me_phone,
            "match": is_match,
        }
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


def clear_character_session(character_id: str) -> None:
    session_path = session_file_for_character(character_id)
    journal_path = f"{session_path}-journal"
    if os.path.exists(session_path):
        os.remove(session_path)
    if os.path.exists(journal_path):
        os.remove(journal_path)


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
        candidates = list(merged_groups.values())
        deduped = []
        for item in sorted(candidates, key=lambda current: (current["name"] or "", str(current["id"]))):
            same_name = next(
                (
                    existing for existing in deduped
                    if (existing["name"] or "").strip().lower() == (item["name"] or "").strip().lower()
                ),
                None,
            )
            if same_name is None:
                deduped.append(item)
                continue

            existing_accounts = set(same_name["accounts"])
            current_accounts = set(item["accounts"])
            if current_accounts <= existing_accounts:
                continue
            if existing_accounts < current_accounts:
                deduped[deduped.index(same_name)] = item
                continue
            deduped.append(item)
        return deduped

    detail = "；".join(errors) if errors else "没有找到可用的已登录会话"
    raise RuntimeError(detail)


# ── 基础配置 ───────────────────────────────────────────
st.header("1. 基础配置")
st.caption("先填写 Telegram、AI 和角色信息。这部分是后续登录和启动的前提。")
col1, col2 = st.columns(2)
with col1:
    api_id = st.text_input("API ID", value=env.get("TELEGRAM_API_ID", ""))
with col2:
    api_hash = st.text_input("API Hash", value=env.get("TELEGRAM_API_HASH", ""), type="password")

if "pending_group_id_input" in st.session_state:
    st.session_state.group_id_input = st.session_state.pop("pending_group_id_input")
elif "group_id_input" not in st.session_state:
    st.session_state.group_id_input = env.get("TELEGRAM_GROUP_ID", "")
group_id = st.session_state.group_id_input

st.subheader("Telegram")
st.caption("登录账号和读取群组都会用到这里的凭据。")

# ── AI 配置 ────────────────────────────────────────────
st.subheader("AI 配置")
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

# ── 网络高级配置 ───────────────────────────────────────
with st.expander("网络与代理（高级）", expanded=False):
    st.caption("只有在当前网络环境无法直连 Telegram 或 AI 服务时才需要配置")
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
st.subheader("角色配置")
st.caption("这里只填角色资料；真正的 Telegram 登录放到下一步完成。")

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
    char_id = char.get("id") or f"角色{i+1}"
    with st.expander(f"角色 {i+1}：{char.get('name', '')}", expanded=True):
        col1, col2, col3 = st.columns([2, 3, 1])
        with col1:
            name = st.text_input("角色名", value=char.get("name", ""), key=f"name_{char_id}")
        with col2:
            phone = st.text_input("手机号", value=char.get("phone", ""), key=f"phone_{char_id}", placeholder="+8613800000001")
        with col3:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("删除", key=f"del_{char_id}", disabled=len(st.session_state.characters) <= 1):
                st.session_state.characters.pop(i)
                st.rerun()
        system = st.text_area("性格描述", value=char.get("system", ""), key=f"system_{char_id}", height=100)
        chars_input.append({"id": char_id, "name": name, "phone": phone, "system": system})

# 实时检测重复手机号
_phone_seen: dict[str, str] = {}
for _char in chars_input:
    _phone = (_char.get("phone") or "").strip()
    if not _phone:
        continue
    if _phone in _phone_seen:
        st.error(f"⚠️ 手机号 {_phone} 同时被「{_phone_seen[_phone]}」和「{_char['name']}」使用，请修改后再保存")
        break
    _phone_seen[_phone] = _char["name"]

st.divider()
overview1, overview2, overview3, overview4 = st.columns(4)
overview1.caption("步骤 1")
overview1.write(f"**基础配置**")
overview1.caption(summarize_basic_config(api_id, api_hash, ai_key, chars_input))
overview2.caption("步骤 2")
overview2.write("**登录账号**")
overview2.caption(summarize_login_step(ensure_character_ids(chars_input)))
overview3.caption("步骤 3")
overview3.write("**选择群组**")
overview3.caption(summarize_group_step(group_id))
overview4.caption("步骤 4")
overview4.write("**启动运行**")
overview4.caption(summarize_runtime_step())

login_section = st.container()
group_section = st.container()
start_section = st.container()
advanced_section = st.container()

# ── 回复行为配置 ───────────────────────────────────────
with advanced_section:
    with st.expander("高级设置", expanded=False):
        st.caption("这些参数不是首次使用必填项。第一次使用时可以先跳过，等账号登录并跑起来后再回来微调。")

        st.subheader("回复行为")

        always_reply = st.toggle(
            "每条消息都回复",
            value=env.get("ALWAYS_REPLY", "true") == "true",
            help="开启后两个角色会回复每一条消息；关闭后按概率随机决定是否回复"
        )

        saved_reply_strategy = env.get("REPLY_ASSIGNMENT_STRATEGY", "random")
        if saved_reply_strategy not in REPLY_STRATEGY_OPTIONS:
            saved_reply_strategy = "random"
        reply_assignment_strategy = st.selectbox(
            "回复角色分配策略",
            options=list(REPLY_STRATEGY_OPTIONS.keys()),
            index=list(REPLY_STRATEGY_OPTIONS.keys()).index(saved_reply_strategy),
            format_func=lambda key: REPLY_STRATEGY_OPTIONS[key],
            help="随机分配是当前策略；轮流回复更平均；最近最久没发言更能避免某个角色长期沉默。"
        )

        saved_interaction_mode = env.get("INTERACTION_MODE", "mixed")
        if saved_interaction_mode not in INTERACTION_MODE_OPTIONS:
            saved_interaction_mode = "mixed"
        interaction_mode = st.selectbox(
            "对话模式",
            options=list(INTERACTION_MODE_OPTIONS.keys()),
            index=list(INTERACTION_MODE_OPTIONS.keys()).index(saved_interaction_mode),
            format_func=lambda key: INTERACTION_MODE_OPTIONS[key],
            help="正常模式会响应真人消息；只让角色互聊模式会忽略真人消息，只保留角色之间的接话和自动话题。"
        )

        saved_reply_delay_mode = env.get("REPLY_DELAY_MODE", "batch_pause")
        if saved_reply_delay_mode not in REPLY_DELAY_MODE_OPTIONS:
            saved_reply_delay_mode = "batch_pause"
        reply_delay_mode = st.selectbox(
            "回复延迟模式",
            options=list(REPLY_DELAY_MODE_OPTIONS.keys()),
            index=list(REPLY_DELAY_MODE_OPTIONS.keys()).index(saved_reply_delay_mode),
            format_func=lambda key: REPLY_DELAY_MODE_OPTIONS[key],
            help="整段回复前统一等待：一条消息触发后先等一次，后面几个角色可能会连续发。每条发出前单独等待：每个角色真正发送前都会各自再等一遍，更像聊一段歇一会。"
        )

        col1, col2 = st.columns(2)
        with col1:
            delay_min = st.number_input("回复最短延迟（秒）", value=safe_int(env.get("REPLY_DELAY_MIN"), 5), min_value=0,
                                         help="收到消息后最少等多久再回，模拟真人思考")
        with col2:
            delay_max = st.number_input("回复最长延迟（秒）", value=safe_int(env.get("REPLY_DELAY_MAX"), 15), min_value=0,
                                         help="收到消息后最多等多久再回")

        with st.expander("高级回复设置", expanded=False):
            col1, col2, col3 = st.columns(3)
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
            with col3:
                message_expiry_seconds = st.number_input(
                    "消息过期时间（秒，0=永不过期）",
                    value=safe_int(env.get("MESSAGE_EXPIRY_SECONDS"), 0),
                    min_value=0,
                    help="仅在正常模式下生效；排队中的消息超过这个时间就跳过。填 0 表示永不过期"
                )

        st.subheader("定时开关机")
        auto_schedule_enabled = st.toggle(
            "启用定时开关机",
            value=env.get("AUTO_SCHEDULE_ENABLED", "false") == "true",
            help="按下面设置的时间自动启动或停止机器人。使用服务器当前本地时间。"
        )
        col1, col2 = st.columns(2)
        with col1:
            auto_schedule_start = st.time_input(
                "每天自动开启时间",
                value=parse_hhmm(env.get("AUTO_SCHEDULE_START"), "09:00"),
                help="到这个时间会自动执行启动机器人。"
            )
        with col2:
            auto_schedule_stop = st.time_input(
                "每天自动关闭时间",
                value=parse_hhmm(env.get("AUTO_SCHEDULE_STOP"), "23:00"),
                help="到这个时间会自动执行停止机器人。"
            )
        auto_schedule_weekdays_only = st.checkbox(
            "仅工作日生效",
            value=env.get("AUTO_SCHEDULE_WEEKDAYS_ONLY", "false") == "true",
            help="勾选后只在周一到周五生效，周末不自动启动。"
        )
        st.caption(
            "整段回复前统一等待：一条消息触发后先等一次，后面几个角色可能连续发。"
            "每条发出前单独等待：每个角色真正发送前都会各自再等一遍，更像聊一段歇一会。"
        )

        st.subheader("自动发话题")
        topic_interval = st.number_input(
            "发话题间隔（秒）",
            value=safe_int(env.get("TOPIC_INTERVAL"), 1800),
            min_value=60,
            help="无人说话时多久自动发起一个新话题，1800=30分钟"
        )

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
        default_custom_list = [d for d in saved_custom.split("||") if d.strip()] if saved_custom else []
        if "custom_topic_directions" not in st.session_state:
            st.session_state.custom_topic_directions = default_custom_list
        custom_list = list(st.session_state.custom_topic_directions)

        # 合并预设 + 自定义，构成完整选项列表
        all_options = ALL_DIRECTIONS + custom_list
        if "topic_directions_selected" not in st.session_state:
            st.session_state.topic_directions_selected = [d for d in saved_list if d in all_options]
        else:
            st.session_state.topic_directions_selected = [
                d for d in st.session_state.topic_directions_selected if d in all_options
            ]

        with st.expander("高级话题设置", expanded=False):
            topic_start = st.number_input(
                "启动后多久发第一个话题（秒）",
                value=safe_int(env.get("TOPIC_START_DELAY"), 30),
                min_value=5
            )

            col1, col2 = st.columns([4, 1])
            with col1:
                new_direction = st.text_input(
                    "添加自定义话题方向",
                    key="new_topic_direction",
                    placeholder="如：健身、减肥、运动",
                    label_visibility="visible",
                )
            with col2:
                st.markdown("<br>", unsafe_allow_html=True)
                st.button("添加", use_container_width=True, on_click=add_custom_topic_direction)

            topic_directions = st.multiselect(
                "话题方向（勾选后 AI 只在这些范围内轮换）",
                options=all_options,
                key="topic_directions_selected",
                help="至少选一个，不选则使用全部"
            )

with login_section:
    st.header("2. 登录账号")
    st.caption("按角色逐个完成登录。已登录的账号会保留 session，之后回来一般不需要重登。")
    for char in ensure_character_ids(chars_input):
        char_id = char["id"]
        login_state_key = f"login_status_{char_id}"
        login_meta_key = f"login_meta_{char_id}"
        code_hash_key = f"code_hash_{char_id}"
        code_input_key = f"code_input_{char_id}"
        password_input_key = f"password_input_{char_id}"

        has_pending_code = bool(st.session_state.get(code_hash_key))
        login_meta = st.session_state.get(login_meta_key)
        if login_meta and login_meta.get("ok"):
            status_text = f"已登录：{login_meta['account']}"
        elif has_pending_code:
            status_text = "等待输入验证码"
        elif os.path.exists(session_file_for_character(char_id)):
            status_text = "检测到本地 session，建议点检查登录状态确认"
        else:
            status_text = "未登录"

        with st.expander(f"{char['name']} | {status_text}", expanded=has_pending_code):
            st.caption(f"Session: `{session_file_for_character(char_id)}`")
            st.caption(f"角色配置手机号尾号：`{format_phone_suffix(char.get('phone'))}`")
            st.info("推荐顺序：先发送验证码，再输入验证码完成登录；只有换号或登录错账号时才需要重置 Session。")
            col1, col2, col3 = st.columns(3)
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
                            reply_assignment_strategy=reply_assignment_strategy,
                            interaction_mode=interaction_mode,
                            reply_delay_mode=reply_delay_mode,
                            auto_schedule_enabled=auto_schedule_enabled,
                            auto_schedule_start=normalize_time_value(auto_schedule_start),
                            auto_schedule_stop=normalize_time_value(auto_schedule_stop),
                            auto_schedule_weekdays_only=auto_schedule_weekdays_only,
                            delay_min=delay_min,
                            delay_max=delay_max,
                            message_expiry_seconds=message_expiry_seconds,
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
                        status = asyncio.run(
                            get_login_status(api_id, api_hash, proxy_host, proxy_port, current_character)
                        )
                        st.session_state[login_state_key] = status["label"]
                        st.session_state[login_meta_key] = status
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
                            reply_assignment_strategy=reply_assignment_strategy,
                            interaction_mode=interaction_mode,
                            reply_delay_mode=reply_delay_mode,
                            auto_schedule_enabled=auto_schedule_enabled,
                            auto_schedule_start=normalize_time_value(auto_schedule_start),
                            auto_schedule_stop=normalize_time_value(auto_schedule_stop),
                            auto_schedule_weekdays_only=auto_schedule_weekdays_only,
                            delay_min=delay_min,
                            delay_max=delay_max,
                            message_expiry_seconds=message_expiry_seconds,
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
                            st.session_state[login_meta_key] = {
                                "ok": True,
                                "account": result["account"],
                                "phone": None,
                                "match": True,
                            }
                            st.session_state.pop(code_hash_key, None)
                        else:
                            st.session_state[code_hash_key] = result["phone_code_hash"]
                            st.session_state[login_state_key] = "验证码已发送"
                    except Exception as e:
                        st.session_state[login_state_key] = f"发送失败：{e}"
            with col3:
                if st.button("重置 Session", key=f"reset_session_{char_id}", use_container_width=True):
                    clear_character_session(char_id)
                    st.session_state.pop(login_state_key, None)
                    st.session_state.pop(login_meta_key, None)
                    st.session_state.pop(code_hash_key, None)
                    st.session_state.pop(code_input_key, None)
                    st.session_state.pop(password_input_key, None)
                    set_app_notice("success", "当前角色 session 已清除")
                    st.rerun()

            login_state = st.session_state.get(login_state_key)
            login_meta = st.session_state.get(login_meta_key)
            if login_meta and login_meta.get('ok'):
                actual_phone_suffix = format_phone_suffix(login_meta.get('phone'))
                if login_meta.get('match'):
                    st.success(f"✅ 已登录：{login_meta['account']}（尾号 {actual_phone_suffix}）")
                else:
                    st.error(f"⚠️ 已登录：{login_meta['account']}（尾号 {actual_phone_suffix}）— 手机号与角色配置不一致，建议重置 Session 后重新登录")
            elif login_state:
                if "失败" in login_state or "错误" in login_state:
                    st.error(f"❌ {login_state}")
                elif "未登录" in login_state:
                    st.warning(f"⚠️ {login_state}")
                else:
                    st.info(f"ℹ️ {login_state}")
            else:
                st.caption("未检查登录状态")

            if st.session_state.get(code_hash_key):
                st.text_input("验证码", key=code_input_key, placeholder="输入 Telegram 发来的验证码")
                st.text_input("二步验证密码", key=password_input_key, type="password", placeholder="若未开启可留空")
                if st.button(
                    "完成登录",
                    key=f"finish_login_{char_id}",
                    use_container_width=True,
                    disabled=not st.session_state.get(code_input_key, "").strip(),
                ):
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
                            reply_assignment_strategy=reply_assignment_strategy,
                            interaction_mode=interaction_mode,
                            reply_delay_mode=reply_delay_mode,
                            auto_schedule_enabled=auto_schedule_enabled,
                            auto_schedule_start=normalize_time_value(auto_schedule_start),
                            auto_schedule_stop=normalize_time_value(auto_schedule_stop),
                            auto_schedule_weekdays_only=auto_schedule_weekdays_only,
                            delay_min=delay_min,
                            delay_max=delay_max,
                            message_expiry_seconds=message_expiry_seconds,
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
                            st.rerun()
                        else:
                            st.session_state.pop(code_hash_key, None)
                            # 登录成功后自动检查登录状态，获取真实手机号匹配结果
                            for _attempt in range(2):
                                try:
                                    status = asyncio.run(
                                        get_login_status(api_id, api_hash, proxy_host, proxy_port, current_character)
                                    )
                                    st.session_state[login_state_key] = status["label"]
                                    st.session_state[login_meta_key] = status
                                    set_app_notice("success", f"{char['name']} 登录成功：{status['label']}")
                                    st.rerun()
                                    break
                                except Exception as check_err:
                                    if _attempt == 1:
                                        st.session_state[login_state_key] = f"状态未知：{check_err}"
                                        st.session_state.pop(login_meta_key, None)
                                        set_app_notice("warning", f"无法确认登录结果，请手动点击检查登录状态：{check_err}")
                                        st.rerun()
                    except Exception as e:
                        st.session_state[login_state_key] = f"登录失败：{e}"
                        st.rerun()
with group_section:
    st.header("3. 选择群组")
    st.caption("从已登录账号可见的群组里选择一个，系统会自动填入群组 ID。之后你也可以手动改。")
    group_id = st.text_input("当前群组 ID（负数，如 -1002278401337）", key="group_id_input")

    with st.expander("读取并选择群组", expanded=not bool((group_id or "").strip())):
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
                    reply_assignment_strategy=reply_assignment_strategy,
                    interaction_mode=interaction_mode,
                    reply_delay_mode=reply_delay_mode,
                    auto_schedule_enabled=auto_schedule_enabled,
                    auto_schedule_start=normalize_time_value(auto_schedule_start),
                    auto_schedule_stop=normalize_time_value(auto_schedule_stop),
                    auto_schedule_weekdays_only=auto_schedule_weekdays_only,
                    delay_min=delay_min,
                    delay_max=delay_max,
                    message_expiry_seconds=message_expiry_seconds,
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
                set_app_notice("success", f"已读取到 {len(st.session_state.group_choices)} 个群组")
            except Exception as e:
                st.session_state.group_choices = []
                set_app_notice("error", f"读取失败：{e}")

        group_choices = st.session_state.get("group_choices", [])
        if group_choices:
            group_filter = st.text_input("搜索群组名", placeholder="输入关键词过滤", key="group_filter")
            filtered = [g for g in group_choices if group_filter.lower() in (g.get("name") or "").lower()] if group_filter else group_choices
            st.caption(f"共 {len(group_choices)} 个群组，显示 {len(filtered)} 个")
        else:
            filtered = []

        for idx, item in enumerate(filtered):
            col1, col2 = st.columns([5, 1])
            with col1:
                st.write(f"**{item['name']}**")
                st.caption(f"ID: `{item['id']}` | 类型: {item['type']} | 账号: {', '.join(item['accounts'])}")
            with col2:
                if st.button("使用", key=f"use_group_{idx}", use_container_width=True):
                    st.session_state.pending_group_id_input = str(item["id"])
                    persist_form_state(
                        api_id=api_id,
                        api_hash=api_hash,
                        group_id=str(item["id"]),
                        ai_key=ai_key,
                        ai_url=ai_url,
                        ai_model=ai_model,
                        characters=chars_input,
                        always_reply=always_reply,
                        reply_assignment_strategy=reply_assignment_strategy,
                        interaction_mode=interaction_mode,
                        reply_delay_mode=reply_delay_mode,
                        auto_schedule_enabled=auto_schedule_enabled,
                        auto_schedule_start=normalize_time_value(auto_schedule_start),
                        auto_schedule_stop=normalize_time_value(auto_schedule_stop),
                        auto_schedule_weekdays_only=auto_schedule_weekdays_only,
                        delay_min=delay_min,
                        delay_max=delay_max,
                        message_expiry_seconds=message_expiry_seconds,
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
with start_section:
    st.header("4. 启动运行")
    st.caption("前 3 步完成后，在这里保存配置、启动机器人，并查看运行日志。")
    st.divider()
    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("💾 保存配置", use_container_width=True):
            # 检查重复手机号
            seen_phones: dict[str, str] = {}
            phone_conflict = None
            for char in chars_input:
                phone = (char.get("phone") or "").strip()
                if not phone:
                    continue
                if phone in seen_phones:
                    phone_conflict = f"手机号 {phone} 同时被「{seen_phones[phone]}」和「{char['name']}」使用，每个角色必须使用独立的手机号"
                    break
                seen_phones[phone] = char["name"]

            if phone_conflict:
                set_app_notice("error", phone_conflict)
            else:
                persist_form_state(
                    api_id=api_id,
                    api_hash=api_hash,
                    group_id=group_id,
                    ai_key=ai_key,
                    ai_url=ai_url,
                    ai_model=ai_model,
                    characters=chars_input,
                    always_reply=always_reply,
                    reply_assignment_strategy=reply_assignment_strategy,
                    interaction_mode=interaction_mode,
                    reply_delay_mode=reply_delay_mode,
                    auto_schedule_enabled=auto_schedule_enabled,
                    auto_schedule_start=normalize_time_value(auto_schedule_start),
                    auto_schedule_stop=normalize_time_value(auto_schedule_stop),
                    auto_schedule_weekdays_only=auto_schedule_weekdays_only,
                    delay_min=delay_min,
                    delay_max=delay_max,
                    message_expiry_seconds=message_expiry_seconds,
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
                set_app_notice("success", "配置已保存！")

    with col2:
        if st.button("▶ 启动机器人", use_container_width=True, type="primary"):
            if is_running():
                set_app_notice("warning", "机器人已在运行中")
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
                        reply_assignment_strategy=reply_assignment_strategy,
                        interaction_mode=interaction_mode,
                        reply_delay_mode=reply_delay_mode,
                        auto_schedule_enabled=auto_schedule_enabled,
                        auto_schedule_start=normalize_time_value(auto_schedule_start),
                        auto_schedule_stop=normalize_time_value(auto_schedule_stop),
                        auto_schedule_weekdays_only=auto_schedule_weekdays_only,
                        delay_min=delay_min,
                        delay_max=delay_max,
                        message_expiry_seconds=message_expiry_seconds,
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
                        set_app_notice("error", f"以下角色尚未登录，先在页面里完成验证码登录：{', '.join(missing)}")
                    else:
                        start_bot()
                        set_app_notice("success", "机器人已启动！")
                except Exception as e:
                    set_app_notice("error", f"启动前检查失败：{e}")

    with col3:
        if st.button("⏹ 停止机器人", use_container_width=True):
            if is_running():
                stop_bot()
                set_app_notice("success", "已停止")
            else:
                set_app_notice("warning", "机器人未在运行")

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
                set_app_notice("success", "日志已清空")
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
