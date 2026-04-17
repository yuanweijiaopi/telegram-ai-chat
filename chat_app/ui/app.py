import streamlit as st
import uuid
from .advanced import render_advanced_section
from .presets import (
    PROVIDER_MAP,
    load_saved_characters,
    resolve_initial_provider,
)
from .runtime import (
    load_current_env,
    normalize_time_value,
    save_env,
    scheduler_loop,
)
from .form_state import (
    summarize_basic_config,
    summarize_group_step,
    summarize_login_step,
    summarize_runtime_step,
)
from .sections import (
    render_group_section,
    render_login_section,
    render_start_section,
)
from .telegram import ensure_character_ids

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
env = load_current_env()


def set_app_notice(level: str, message: str) -> None:
    st.session_state.app_notice = {"level": level, "message": message}


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


@st.cache_resource
def ensure_scheduler_started():
    import threading

    thread = threading.Thread(target=scheduler_loop, daemon=True, name="bot-scheduler")
    thread.start()
    return True


ensure_scheduler_started()


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
saved_ai_url = env.get("AI_BASE_URL", "")
saved_ai_model = env.get("AI_MODEL", "")
provider_options = list(PROVIDER_MAP.keys())
initial_provider = resolve_initial_provider(saved_ai_url, saved_ai_model)

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

_saved_chars = load_saved_characters(env)

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

advanced_section = st.container()

# ── 回复行为配置 ───────────────────────────────────────
with advanced_section:
    advanced_values = render_advanced_section(env, add_custom_topic_direction)

always_reply = advanced_values["always_reply"]
reply_assignment_strategy = advanced_values["reply_assignment_strategy"]
interaction_mode = advanced_values["interaction_mode"]
reply_delay_mode = advanced_values["reply_delay_mode"]
delay_min = advanced_values["delay_min"]
delay_max = advanced_values["delay_max"]
cooldown_human = advanced_values["cooldown_human"]
cooldown_ai = advanced_values["cooldown_ai"]
message_expiry_seconds = advanced_values["message_expiry_seconds"]
auto_schedule_enabled = advanced_values["auto_schedule_enabled"]
auto_schedule_start = advanced_values["auto_schedule_start"]
auto_schedule_stop = advanced_values["auto_schedule_stop"]
auto_schedule_weekdays_only = advanced_values["auto_schedule_weekdays_only"]
topic_interval = advanced_values["topic_interval"]
topic_start = advanced_values["topic_start"]
topic_directions = advanced_values["topic_directions"]
custom_list = advanced_values["custom_list"]
form_values = {
    "api_id": api_id,
    "api_hash": api_hash,
    "group_id": group_id,
    "ai_key": ai_key,
    "ai_url": ai_url,
    "ai_model": ai_model,
    "characters": chars_input,
    "always_reply": always_reply,
    "reply_assignment_strategy": reply_assignment_strategy,
    "interaction_mode": interaction_mode,
    "reply_delay_mode": reply_delay_mode,
    "auto_schedule_enabled": auto_schedule_enabled,
    "auto_schedule_start": normalize_time_value(auto_schedule_start),
    "auto_schedule_stop": normalize_time_value(auto_schedule_stop),
    "auto_schedule_weekdays_only": auto_schedule_weekdays_only,
    "delay_min": delay_min,
    "delay_max": delay_max,
    "message_expiry_seconds": message_expiry_seconds,
    "cooldown_human": cooldown_human,
    "cooldown_ai": cooldown_ai,
    "topic_interval": topic_interval,
    "topic_start": topic_start,
    "topic_directions": topic_directions,
    "custom_list": custom_list,
    "use_proxy": use_proxy,
    "proxy_host": proxy_host,
    "proxy_port": proxy_port,
}

render_login_section(
    chars_input=chars_input,
    form_values=form_values,
    api_id=api_id,
    api_hash=api_hash,
    proxy_host=proxy_host,
    proxy_port=proxy_port,
    set_app_notice=set_app_notice,
)

group_id = render_group_section(
    chars_input=chars_input,
    form_values=form_values,
    group_id=group_id,
    api_id=api_id,
    api_hash=api_hash,
    proxy_host=proxy_host,
    proxy_port=proxy_port,
    set_app_notice=set_app_notice,
)

form_values["group_id"] = group_id

render_start_section(
    chars_input=chars_input,
    form_values=form_values,
    api_id=api_id,
    api_hash=api_hash,
    proxy_host=proxy_host,
    proxy_port=proxy_port,
    set_app_notice=set_app_notice,
)
