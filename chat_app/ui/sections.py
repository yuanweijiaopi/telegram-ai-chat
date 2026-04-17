import asyncio
import os
import time

import streamlit as st
from shared.paths import CHAT_LOG

from .form_state import persist_form_state
from .runtime import is_running, start_bot, stop_bot
from .telegram import (
    all_characters_logged_in,
    clear_character_session,
    complete_login,
    ensure_character_ids,
    fetch_group_choices,
    format_phone_suffix,
    get_login_status,
    send_login_code,
    session_file_for_character,
)


def _persist_current_form(form_values: dict) -> list[dict]:
    return persist_form_state(**dict(form_values))


def _find_phone_conflict(characters: list[dict]) -> str | None:
    seen_phones: dict[str, str] = {}
    for char in characters:
        phone = (char.get("phone") or "").strip()
        if not phone:
            continue
        if phone in seen_phones:
            return (
                f"手机号 {phone} 同时被「{seen_phones[phone]}」和「{char['name']}」使用，"
                "每个角色必须使用独立的手机号"
            )
        seen_phones[phone] = char["name"]
    return None


def render_login_section(
    *,
    chars_input: list[dict],
    form_values: dict,
    api_id: str,
    api_hash: str,
    proxy_host: str,
    proxy_port: str,
    set_app_notice,
) -> None:
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
                        normalized_chars = _persist_current_form(form_values)
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
                        normalized_chars = _persist_current_form(form_values)
                        current_character = next(item for item in normalized_chars if item["id"] == char_id)
                        result = asyncio.run(
                            send_login_code(api_id, api_hash, proxy_host, proxy_port, current_character)
                        )
                        if result["status"] == "already":
                            status = asyncio.run(
                                get_login_status(api_id, api_hash, proxy_host, proxy_port, current_character)
                            )
                            st.session_state[login_state_key] = status["label"]
                            st.session_state[login_meta_key] = status
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
            if login_meta and login_meta.get("ok"):
                actual_phone_suffix = format_phone_suffix(login_meta.get("phone"))
                if login_meta.get("match"):
                    st.success(f"✅ 已登录：{login_meta['account']}（尾号 {actual_phone_suffix}）")
                else:
                    st.error(
                        f"⚠️ 已登录：{login_meta['account']}（尾号 {actual_phone_suffix}）— "
                        "手机号与角色配置不一致，建议重置 Session 后重新登录"
                    )
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
                        normalized_chars = _persist_current_form(form_values)
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
                            for attempt in range(2):
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
                                    if attempt == 1:
                                        st.session_state[login_state_key] = f"状态未知：{check_err}"
                                        st.session_state.pop(login_meta_key, None)
                                        set_app_notice(
                                            "warning",
                                            f"无法确认登录结果，请手动点击检查登录状态：{check_err}",
                                        )
                                        st.rerun()
                    except Exception as e:
                        st.session_state[login_state_key] = f"登录失败：{e}"
                        st.rerun()


def render_group_section(
    *,
    chars_input: list[dict],
    form_values: dict,
    group_id: str,
    api_id: str,
    api_hash: str,
    proxy_host: str,
    proxy_port: str,
    set_app_notice,
) -> str:
    st.header("3. 选择群组")
    st.caption("从已登录账号可见的群组里选择一个，系统会自动填入群组 ID。之后你也可以手动改。")
    group_id = st.text_input("当前群组 ID（负数，如 -1002278401337）", key="group_id_input")

    with st.expander("读取并选择群组", expanded=not bool((group_id or "").strip())):
        st.caption("读取当前已登录 Telegram 账号可见的群组，并可一键填入上面的群组 ID")
        if st.button("读取群组列表", use_container_width=True):
            try:
                normalized_chars = _persist_current_form({**form_values, "group_id": group_id})
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
            filtered = [
                item for item in group_choices
                if group_filter.lower() in (item.get("name") or "").lower()
            ] if group_filter else group_choices
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
                    persist_form_state(**{**form_values, "group_id": str(item["id"])})
                    st.rerun()

    return group_id


def render_start_section(
    *,
    chars_input: list[dict],
    form_values: dict,
    api_id: str,
    api_hash: str,
    proxy_host: str,
    proxy_port: str,
    set_app_notice,
) -> None:
    st.header("4. 启动运行")
    st.caption("前 3 步完成后，在这里保存配置、启动机器人，并查看运行日志。")
    st.divider()

    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("💾 保存配置", use_container_width=True):
            phone_conflict = _find_phone_conflict(chars_input)
            if phone_conflict:
                set_app_notice("error", phone_conflict)
            else:
                _persist_current_form(form_values)
                set_app_notice("success", "配置已保存！")

    with col2:
        if st.button("▶ 启动机器人", use_container_width=True, type="primary"):
            if is_running():
                set_app_notice("warning", "机器人已在运行中")
            else:
                try:
                    normalized_chars = _persist_current_form(form_values)
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
        log_path = str(CHAT_LOG)

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
            refresh_interval = st.number_input(
                "间隔（秒）",
                value=5,
                min_value=1,
                max_value=60,
                label_visibility="collapsed" if not auto_refresh else "visible",
            )

        if os.path.exists(log_path):
            lines = open(log_path, encoding="utf-8", errors="replace").readlines()
            st.code("".join(lines[-50:]), language="text")
        else:
            st.info("暂无日志")

        if auto_refresh:
            time.sleep(refresh_interval)
            st.rerun()
