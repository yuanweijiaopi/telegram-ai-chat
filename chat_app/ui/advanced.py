import streamlit as st

from .form_state import (
    INTERACTION_MODE_OPTIONS,
    REPLY_DELAY_MODE_OPTIONS,
    REPLY_STRATEGY_OPTIONS,
)
from .presets import DEFAULT_TOPIC_DIRECTIONS
from .runtime import parse_hhmm, safe_int


def render_advanced_section(env: dict, add_custom_topic_direction):
    with st.expander("高级设置", expanded=False):
        st.caption("这些参数不是首次使用必填项。第一次使用时可以先跳过，等账号登录并跑起来后再回来微调。")

        st.subheader("回复行为")

        always_reply = st.toggle(
            "每条消息都回复",
            value=env.get("ALWAYS_REPLY", "true") == "true",
            help="开启后两个角色会回复每一条消息；关闭后按概率随机决定是否回复",
        )

        saved_reply_strategy = env.get("REPLY_ASSIGNMENT_STRATEGY", "random")
        if saved_reply_strategy not in REPLY_STRATEGY_OPTIONS:
            saved_reply_strategy = "random"
        reply_assignment_strategy = st.selectbox(
            "回复角色分配策略",
            options=list(REPLY_STRATEGY_OPTIONS.keys()),
            index=list(REPLY_STRATEGY_OPTIONS.keys()).index(saved_reply_strategy),
            format_func=lambda key: REPLY_STRATEGY_OPTIONS[key],
            help="随机分配是当前策略；轮流回复更平均；最近最久没发言更能避免某个角色长期沉默。",
        )

        saved_interaction_mode = env.get("INTERACTION_MODE", "mixed")
        if saved_interaction_mode not in INTERACTION_MODE_OPTIONS:
            saved_interaction_mode = "mixed"
        interaction_mode = st.selectbox(
            "对话模式",
            options=list(INTERACTION_MODE_OPTIONS.keys()),
            index=list(INTERACTION_MODE_OPTIONS.keys()).index(saved_interaction_mode),
            format_func=lambda key: INTERACTION_MODE_OPTIONS[key],
            help="正常模式会响应真人消息；只让角色互聊模式会忽略真人消息，只保留角色之间的接话和自动话题。",
        )

        saved_reply_delay_mode = env.get("REPLY_DELAY_MODE", "batch_pause")
        if saved_reply_delay_mode not in REPLY_DELAY_MODE_OPTIONS:
            saved_reply_delay_mode = "batch_pause"
        reply_delay_mode = st.selectbox(
            "回复延迟模式",
            options=list(REPLY_DELAY_MODE_OPTIONS.keys()),
            index=list(REPLY_DELAY_MODE_OPTIONS.keys()).index(saved_reply_delay_mode),
            format_func=lambda key: REPLY_DELAY_MODE_OPTIONS[key],
            help="整段回复前统一等待：一条消息触发后先等一次，后面几个角色可能会连续发。每条发出前单独等待：每个角色真正发送前都会各自再等一遍，更像聊一段歇一会。",
        )

        col1, col2 = st.columns(2)
        with col1:
            delay_min = st.number_input(
                "回复最短延迟（秒）",
                value=safe_int(env.get("REPLY_DELAY_MIN"), 5),
                min_value=0,
                help="收到消息后最少等多久再回，模拟真人思考",
            )
        with col2:
            delay_max = st.number_input(
                "回复最长延迟（秒）",
                value=safe_int(env.get("REPLY_DELAY_MAX"), 15),
                min_value=0,
                help="收到消息后最多等多久再回",
            )

        with st.expander("高级回复设置", expanded=False):
            col1, col2, col3 = st.columns(3)
            with col1:
                cooldown_human = st.number_input(
                    "回复真人的冷却时间（秒）",
                    value=safe_int(env.get("MIN_SECONDS_BETWEEN_REPLIES_HUMAN"), 30),
                    min_value=0,
                    help="同一角色两次回复真人之间的最短间隔",
                )
            with col2:
                cooldown_ai = st.number_input(
                    "角色互聊的冷却时间（秒）",
                    value=safe_int(env.get("MIN_SECONDS_BETWEEN_REPLIES_CHARACTER"), 5),
                    min_value=0,
                    help="两个AI角色互相回复之间的最短间隔，越小对话越连贯",
                )
            with col3:
                message_expiry_seconds = st.number_input(
                    "消息过期时间（秒，0=永不过期）",
                    value=safe_int(env.get("MESSAGE_EXPIRY_SECONDS"), 0),
                    min_value=0,
                    help="仅在正常模式下生效；排队中的消息超过这个时间就跳过。填 0 表示永不过期",
                )

        st.subheader("定时开关机")
        auto_schedule_enabled = st.toggle(
            "启用定时开关机",
            value=env.get("AUTO_SCHEDULE_ENABLED", "false") == "true",
            help="按下面设置的时间自动启动或停止机器人。使用服务器当前本地时间。",
        )
        col1, col2 = st.columns(2)
        with col1:
            auto_schedule_start = st.time_input(
                "每天自动开启时间",
                value=parse_hhmm(env.get("AUTO_SCHEDULE_START"), "09:00"),
                help="到这个时间会自动执行启动机器人。",
            )
        with col2:
            auto_schedule_stop = st.time_input(
                "每天自动关闭时间",
                value=parse_hhmm(env.get("AUTO_SCHEDULE_STOP"), "23:00"),
                help="到这个时间会自动执行停止机器人。",
            )
        auto_schedule_weekdays_only = st.checkbox(
            "仅工作日生效",
            value=env.get("AUTO_SCHEDULE_WEEKDAYS_ONLY", "false") == "true",
            help="勾选后只在周一到周五生效，周末不自动启动。",
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
            help="无人说话时多久自动发起一个新话题，1800=30分钟",
        )

        saved_enabled = env.get("TOPIC_DIRECTIONS_ENABLED", "")
        saved_list = saved_enabled.split("||") if saved_enabled else DEFAULT_TOPIC_DIRECTIONS

        saved_custom = env.get("TOPIC_DIRECTIONS_CUSTOM", "")
        default_custom_list = [item for item in saved_custom.split("||") if item.strip()] if saved_custom else []
        if "custom_topic_directions" not in st.session_state:
            st.session_state.custom_topic_directions = default_custom_list
        custom_list = list(st.session_state.custom_topic_directions)

        all_options = DEFAULT_TOPIC_DIRECTIONS + custom_list
        if "topic_directions_selected" not in st.session_state:
            st.session_state.topic_directions_selected = [item for item in saved_list if item in all_options]
        else:
            st.session_state.topic_directions_selected = [
                item for item in st.session_state.topic_directions_selected if item in all_options
            ]

        with st.expander("高级话题设置", expanded=False):
            topic_start = st.number_input(
                "启动后多久发第一个话题（秒）",
                value=safe_int(env.get("TOPIC_START_DELAY"), 30),
                min_value=5,
            )

            col1, col2 = st.columns([4, 1])
            with col1:
                st.text_input(
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
                help="至少选一个，不选则使用全部",
            )

    return {
        "always_reply": always_reply,
        "reply_assignment_strategy": reply_assignment_strategy,
        "interaction_mode": interaction_mode,
        "reply_delay_mode": reply_delay_mode,
        "delay_min": delay_min,
        "delay_max": delay_max,
        "cooldown_human": cooldown_human,
        "cooldown_ai": cooldown_ai,
        "message_expiry_seconds": message_expiry_seconds,
        "auto_schedule_enabled": auto_schedule_enabled,
        "auto_schedule_start": auto_schedule_start,
        "auto_schedule_stop": auto_schedule_stop,
        "auto_schedule_weekdays_only": auto_schedule_weekdays_only,
        "topic_interval": topic_interval,
        "topic_start": topic_start,
        "topic_directions": topic_directions,
        "custom_list": custom_list,
    }
