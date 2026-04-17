import json
import os

import streamlit as st

from .runtime import is_running, load_current_env, save_env
from .telegram import ensure_character_ids, session_file_for_character

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
    message_expiry_seconds: int = 0,
    cooldown_human: int = 0,
    cooldown_ai: int = 0,
    topic_interval: int = 1800,
    topic_start: int = 30,
    topic_directions: list[str] | None = None,
    custom_list: list[str] | None = None,
    use_proxy: bool = False,
    proxy_host: str = "",
    proxy_port: str = "",
) -> tuple[dict, list[dict]]:
    normalized_characters = ensure_character_ids(characters)
    current_env = load_current_env()
    topic_directions = topic_directions or []
    custom_list = custom_list or []

    def _resolve_bool(flag: bool | None, env_key: str) -> str:
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
        "CHARACTERS_JSON": json.dumps(normalized_characters, ensure_ascii=False),
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


def persist_form_state(**kwargs) -> list[dict]:
    data, normalized_characters = build_form_data(**kwargs)
    st.session_state.characters = normalized_characters
    save_env(data)
    return normalized_characters
