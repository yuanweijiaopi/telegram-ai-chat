"""
lottery_ui.py - 抽奖机器人 Streamlit 管理界面

运行方式：streamlit run lottery_ui.py --server.port 8502
"""

import asyncio
import concurrent.futures
import json
import os
import subprocess
import sys

import pandas as pd
import psutil
import socks
import streamlit as st
from dotenv import dotenv_values
from telethon import TelegramClient

from . import lottery_db as db
from shared.paths import ENV_FILE, LOTTERY_BOT_LOG, LOTTERY_PID_FILE, PROJECT_ROOT, ensure_runtime_dirs

# ── 初始化 ───────────────────────────────────────────────────────

ensure_runtime_dirs()
db.init_db()

RAFFLE_PID_FILE = str(LOTTERY_PID_FILE)
BASE_DIR = str(PROJECT_ROOT)

st.set_page_config(page_title="抽奖管理后台", layout="wide")
st.title("🎁 抽奖机器人管理")
st.caption("管理抽奖活动、配置积分规则、内定中奖人，并控制 Bot 运行状态。")


def load_env() -> dict:
    return dict(dotenv_values(ENV_FILE)) if os.path.exists(ENV_FILE) else {}


def save_env_key(key: str, value: str):
    env = load_env()
    env[key] = value
    with open(ENV_FILE, "w", encoding="utf-8") as f:
        for k, v in env.items():
            encoded = json.dumps("" if v is None else str(v), ensure_ascii=False)
            f.write(f"{k}={encoded}\n")


# ── Bot 进程管理 ─────────────────────────────────────────────────

def _read_pid(pid_path: str) -> int:
    with open(pid_path) as f:
        return int(f.read().strip())


def is_bot_running() -> bool:
    pid_path = RAFFLE_PID_FILE
    if not os.path.exists(pid_path):
        return False
    try:
        return psutil.pid_exists(_read_pid(pid_path))
    except Exception:
        return False


def start_lottery_bot():
    log_path = str(LOTTERY_BOT_LOG)
    pid_path = RAFFLE_PID_FILE
    log_fd = open(log_path, "a", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-m", "lottery_app.lottery_bot"],
        stdout=log_fd,
        stderr=subprocess.STDOUT,
        cwd=BASE_DIR,
        close_fds=True,
    )
    log_fd.close()  # 子进程已继承，父进程不需要持有
    with open(pid_path, "w") as f:
        f.write(str(proc.pid))


def stop_lottery_bot():
    pid_path = RAFFLE_PID_FILE
    if not os.path.exists(pid_path):
        return
    try:
        proc = psutil.Process(_read_pid(pid_path))
        for child in proc.children(recursive=True):
            child.kill()
        proc.kill()
    except Exception:
        pass
    if os.path.exists(pid_path):
        os.remove(pid_path)


def read_log_tail(path: str, lines: int = 40) -> str:
    if not os.path.exists(path):
        return "（暂无日志）"
    with open(path, encoding="utf-8", errors="replace") as f:
        all_lines = f.readlines()
    return "".join(all_lines[-lines:])


# ── Telethon 拉取群成员 ──────────────────────────────────────────

def build_proxy(proxy_host: str, proxy_port: str):
    if proxy_host and proxy_port:
        try:
            return (socks.SOCKS5, proxy_host, int(proxy_port))
        except ValueError:
            return None
    return None


def run_async(coro) -> object:
    """在独立线程中运行协程，兼容 Streamlit 内已有的事件循环"""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


async def fetch_members_async(api_id: str, api_hash: str, proxy_host: str,
                               proxy_port: str, session_file: str, group_id: int) -> list:
    proxy = build_proxy(proxy_host, proxy_port)
    client = TelegramClient(session_file, int(api_id), api_hash, proxy=proxy)
    try:
        await client.connect()
        me = await client.get_me()
        if me is None:
            raise RuntimeError("该 session 未登录，请先在主配置界面完成角色登录")
        members = []
        async for user in client.iter_participants(group_id, limit=500):
            name_parts = [getattr(user, "first_name", "") or "", getattr(user, "last_name", "") or ""]
            display_name = " ".join(p for p in name_parts if p).strip()
            if not display_name:
                display_name = getattr(user, "username", "") or str(user.id)
            members.append({
                "user_id": user.id,
                "username": getattr(user, "username", "") or "",
                "display_name": display_name,
                "is_bot": 1 if getattr(user, "bot", False) else 0,
            })
        return members
    finally:
        await client.disconnect()


def get_first_session() -> str:
    sessions_dir = os.path.join(BASE_DIR, "sessions")
    if not os.path.exists(sessions_dir):
        return None
    for f in os.listdir(sessions_dir):
        if f.endswith(".session"):
            return os.path.join(sessions_dir, f)
    return None


# ══════════════════════════════════════════════════════════════════
# Tab 布局
# ══════════════════════════════════════════════════════════════════

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "⚙️ Bot 控制",
    "➕ 创建/编辑活动",
    "👥 参与条件 & 成员",
    "🎯 内定 & 开奖",
    "💰 积分管理",
    "📜 历史记录",
])


# ── Tab 1: Bot 控制 ──────────────────────────────────────────────

with tab1:
    st.subheader("Bot 运行控制")
    env = load_env()
    token_val = env.get("LOTTERY_BOT_TOKEN", "")

    col_token, col_save = st.columns([4, 1])
    with col_token:
        new_token = st.text_input("Bot Token（从 @BotFather 获取）", value=token_val,
                                   type="password", help="需要将 Bot 加入目标群组并设置为管理员")
    with col_save:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("保存 Token", use_container_width=True):
            save_env_key("LOTTERY_BOT_TOKEN", new_token.strip())
            st.success("已保存")

    st.divider()
    running = is_bot_running()
    st.markdown(f"**Bot 状态：{'🟢 运行中' if running else '🔴 已停止'}**")

    col_start, col_stop, _ = st.columns([1, 1, 3])
    with col_start:
        if st.button("▶ 启动 Bot", use_container_width=True, type="primary", disabled=running):
            if not new_token.strip():
                st.error("请先填写并保存 Bot Token")
            else:
                save_env_key("LOTTERY_BOT_TOKEN", new_token.strip())
                start_lottery_bot()
                st.rerun()
    with col_stop:
        if st.button("⏹ 停止 Bot", use_container_width=True, disabled=not running):
            stop_lottery_bot()
            st.rerun()

    st.divider()
    st.subheader("运行日志（最近 40 行）")
    st.code(read_log_tail(str(LOTTERY_BOT_LOG)), language="text")
    if st.button("🔄 刷新日志"):
        st.rerun()


# ── Tab 2: 创建/编辑活动 ─────────────────────────────────────────

with tab2:
    st.subheader("创建新抽奖活动")
    env = load_env()
    default_group = env.get("TELEGRAM_GROUP_ID", "")

    with st.form("create_lottery_form"):
        col_l, col_r = st.columns(2)
        with col_l:
            title = st.text_input("活动标题 *", placeholder="本周活动大抽奖")
            group_id_input = st.text_input("目标群组 ID *", value=default_group)
            result_template = st.text_input("获奖公告模板",
                                             value="🏆 恭喜 {winner} 获奖！感谢大家参与！",
                                             help="{winner} 会被替换为中奖者名字")
        with col_r:
            description = st.text_area("活动描述（公告正文）", height=122,
                                        placeholder="描述活动详情、奖品内容等")

        st.markdown("**参与条件**（不填或填 0 表示无此条件）")
        cond_cols = st.columns(4)
        with cond_cols[0]:
            min_points = st.number_input("最低积分", min_value=0, value=0, step=10,
                                          help="用户需持有至少此积分才能参与")
        with cond_cols[1]:
            min_messages = st.number_input("最低发言数", min_value=0, value=0, step=5,
                                            help="用户需在群内发言至少此条数")
        with cond_cols[2]:
            min_days = st.number_input("最低入群天数", min_value=0, value=0,
                                        help="用户需加入群满此天数")
        with cond_cols[3]:
            points_cost = st.number_input("消耗积分", min_value=0, value=0, step=5,
                                           help="参与此次抽奖需消耗的积分")

        submitted = st.form_submit_button("创建活动", type="primary")

    if submitted:
        if not title.strip():
            st.error("请填写活动标题")
        elif not group_id_input.strip():
            st.error("请填写目标群组 ID")
        else:
            try:
                new_id = db.create_lottery(
                    title=title.strip(),
                    description=description.strip(),
                    group_id=int(group_id_input.strip()),
                    created_by=0,
                    result_template=result_template.strip(),
                    min_points=int(min_points),
                    min_messages=int(min_messages),
                    min_days=int(min_days),
                    points_cost=int(points_cost),
                )
                st.success(f"✅ 活动已创建！ID：**{new_id}**\n\n在群里发送 `/start_lottery {new_id}` 即可发布公告。")
            except ValueError:
                st.error("群组 ID 必须是数字")
            except Exception as e:
                st.error(f"创建失败：{e}")

    st.divider()
    st.subheader("已有活动列表")
    all_lotteries = db.list_lotteries()
    status_label = {"draft": "草稿", "active": "进行中", "finished": "已结束", "cancelled": "已取消"}

    if not all_lotteries:
        st.info("暂无活动，使用上方表单创建第一个。")
    else:
        for lot in all_lotteries:
            count = db.count_participants(lot["id"])
            with st.expander(
                f"#{lot['id']} {lot['title']}  ·  {status_label.get(lot['status'], lot['status'])}  ·  {count} 人参与",
                expanded=False,
            ):
                ea, eb, ec = st.columns([2, 2, 1])
                with ea:
                    nt = st.text_input("标题", value=lot["title"], key=f"t_{lot['id']}")
                    nd = st.text_area("描述", value=lot["description"], key=f"d_{lot['id']}", height=68)
                with eb:
                    ntpl = st.text_input("获奖模板", value=lot["result_template"], key=f"tpl_{lot['id']}")
                    ngid = st.text_input("群组 ID", value=str(lot["group_id"]), key=f"g_{lot['id']}")

                st.markdown("**参与条件**")
                cc = st.columns(4)
                with cc[0]:
                    nmp = st.number_input("最低积分", min_value=0, value=lot.get("min_points") or 0,
                                          key=f"mp_{lot['id']}", step=10)
                with cc[1]:
                    nmsg = st.number_input("最低发言数", min_value=0, value=lot.get("min_messages") or 0,
                                           key=f"mm_{lot['id']}", step=5)
                with cc[2]:
                    nmd = st.number_input("最低入群天数", min_value=0, value=lot.get("min_days") or 0,
                                          key=f"md_{lot['id']}")
                with cc[3]:
                    npc = st.number_input("消耗积分", min_value=0, value=lot.get("points_cost") or 0,
                                          key=f"pc_{lot['id']}", step=5)

                with ec:
                    st.markdown("<br><br>", unsafe_allow_html=True)
                    if st.button("💾 保存", key=f"s_{lot['id']}", use_container_width=True):
                        try:
                            db.update_lottery(lot["id"], {
                                "title": nt.strip(), "description": nd.strip(),
                                "result_template": ntpl.strip(), "group_id": int(ngid.strip()),
                                "min_points": int(nmp), "min_messages": int(nmsg),
                                "min_days": int(nmd), "points_cost": int(npc),
                            })
                            st.success("已保存")
                            st.rerun()
                        except Exception as e:
                            st.error(f"保存失败：{e}")
                    if lot["status"] == "draft":
                        if st.button("🗑️ 删除", key=f"del_{lot['id']}", use_container_width=True):
                            db.delete_lottery(lot["id"])
                            st.rerun()

                if lot["status"] == "draft":
                    st.info(f"群内发送：`/start_lottery {lot['id']}` 发布公告")
                elif lot["status"] == "active":
                    st.info(f"群内发送：`/draw {lot['id']}` 开奖，或在「内定 & 开奖」Tab 远程触发")
                elif lot["status"] == "finished":
                    st.success(f"中奖者：{lot.get('winner_name') or '无'}")


# ── Tab 3: 参与条件 & 成员 ───────────────────────────────────────

with tab3:
    st.subheader("参与口令设置")
    editable = db.list_lotteries(status="active") + db.list_lotteries(status="draft")
    if not editable:
        st.info("暂无可编辑的活动。")
    else:
        lot_opts3 = {f"#{l['id']} {l['title']}": l for l in editable}
        sel3 = st.selectbox("选择活动", list(lot_opts3.keys()), key="tab3_lot")
        sel_lot3 = lot_opts3[sel3]
        with st.form("keyword_form"):
            kw = st.text_input("参与口令", value=sel_lot3.get("keyword", ""),
                                placeholder="留空表示无需口令，直接点按钮参与")
            if st.form_submit_button("保存口令"):
                db.update_lottery(sel_lot3["id"], {"keyword": kw.strip()})
                st.success("已保存")

    st.divider()
    st.subheader("群成员搜索")
    env = load_env()
    gid_default = env.get("TELEGRAM_GROUP_ID", "")
    col_g, col_fetch = st.columns([3, 1])
    with col_g:
        fetch_gid = st.text_input("群组 ID", value=gid_default, key="fetch_gid")
    with col_fetch:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("🔄 拉取成员", use_container_width=True):
            api_id = env.get("TELEGRAM_API_ID", "")
            api_hash = env.get("TELEGRAM_API_HASH", "")
            session_file = get_first_session()
            if not api_id or not api_hash:
                st.error("请先在主配置界面填写 API ID 和 API Hash")
            elif not session_file:
                st.error("没有找到已登录的 session 文件")
            elif not fetch_gid.strip():
                st.error("请填写群组 ID")
            else:
                with st.spinner("正在拉取成员列表..."):
                    try:
                        members = run_async(fetch_members_async(
                            api_id, api_hash,
                            env.get("PROXY_HOST", ""), env.get("PROXY_PORT", ""),
                            session_file, int(fetch_gid.strip())
                        ))
                        db.upsert_members_cache(int(fetch_gid.strip()), members)
                        st.success(f"拉取成功，共 {len(members)} 名成员")
                    except Exception as e:
                        st.error(f"拉取失败：{e}")

    search_q = st.text_input("🔍 搜索成员", placeholder="输入名字或用户名关键词")
    gid_int = int(fetch_gid.strip()) if fetch_gid.strip().lstrip("-").isdigit() else 0
    if gid_int:
        results = db.search_members(gid_int, search_q, limit=100)
        if results:
            df = pd.DataFrame(results)[["user_id", "display_name", "username", "cached_at"]]
            df.columns = ["用户 ID", "名字", "用户名", "缓存时间"]
            st.dataframe(df, use_container_width=True, hide_index=True)
            st.caption(f"共 {len(results)} 条（最多显示 100 条）")
        else:
            st.info("请先拉取成员列表，或输入关键词搜索")


# ── Tab 4: 内定 & 开奖 ───────────────────────────────────────────

with tab4:
    st.subheader("内定中奖人 & 触发开奖")
    active_list = db.list_lotteries(status="active")
    if not active_list:
        st.info("当前没有进行中的活动。在群里发 `/start_lottery <id>` 发布公告后此处会显示。")
    else:
        lot_opts4 = {f"#{l['id']} {l['title']}": l for l in active_list}
        sel4 = st.selectbox("选择进行中的活动", list(lot_opts4.keys()), key="tab4_lot")
        sel_lot4 = lot_opts4[sel4]
        lot_id4 = sel_lot4["id"]

        participants = db.get_participants(lot_id4)
        st.markdown(f"**当前参与人数：{len(participants)}**")
        if participants:
            p_df = pd.DataFrame(participants)[["display_name", "username", "user_id", "joined_at"]]
            p_df.columns = ["名字", "用户名", "用户 ID", "参与时间"]
            st.dataframe(p_df, use_container_width=True, hide_index=True)
        else:
            st.info("暂无参与者。")

        st.divider()
        st.subheader("内定中奖人")
        preset_id = sel_lot4.get("preset_winner_id")
        preset_mode = st.radio("开奖模式", ["🎲 随机抽取", "🎯 内定中奖人"],
                                index=1 if preset_id else 0)

        if preset_mode == "🎯 内定中奖人":
            env = load_env()
            gid_preset = int(env.get("TELEGRAM_GROUP_ID", "0") or "0")
            sq = st.text_input("搜索成员", key="preset_search", placeholder="输入名字或用户名")
            preset_members = db.search_members(gid_preset, sq, limit=50) if gid_preset else []

            if preset_members:
                opts = {
                    f"{m['display_name']}" +
                    (f"  (@{m['username']})" if m.get("username") else "") +
                    f"  [ID: {m['user_id']}]": m
                    for m in preset_members
                }
                cur_label = None
                if preset_id:
                    for label, m in opts.items():
                        if m["user_id"] == preset_id:
                            cur_label = label
                            break
                default_idx = list(opts.keys()).index(cur_label) if cur_label else 0
                sel_preset_label = st.selectbox("选择内定中奖人", list(opts.keys()), index=default_idx)
                sel_preset = opts[sel_preset_label]
                uid_input = st.text_input("或直接输入用户 ID", value=str(sel_preset["user_id"]))
                name_input = st.text_input("显示名（备注）", value=sel_preset.get("display_name", ""))
            else:
                st.info("请先在「参与条件 & 成员」Tab 拉取群成员，或直接手动输入。")
                uid_input = st.text_input("用户 ID", value=str(preset_id) if preset_id else "")
                name_input = st.text_input("显示名", value=sel_lot4.get("preset_winner_name", ""))

            if st.button("💾 保存内定设置", type="primary"):
                try:
                    pid_val = int(uid_input.strip()) if uid_input.strip() else None
                    db.update_lottery(lot_id4, {
                        "preset_winner_id": pid_val,
                        "preset_winner_name": name_input.strip(),
                    })
                    st.success(f"已内定：{name_input.strip()} (ID: {pid_val})")
                    st.rerun()
                except ValueError:
                    st.error("用户 ID 必须是数字")
        else:
            if preset_id:
                if st.button("清除内定，切换为随机"):
                    db.update_lottery(lot_id4, {"preset_winner_id": None, "preset_winner_name": ""})
                    st.success("已切换为随机模式")
                    st.rerun()
            else:
                st.success("当前为随机抽取模式")

        refreshed = db.get_lottery(lot_id4)
        if refreshed and refreshed.get("preset_winner_id"):
            st.info(f"🎯 当前内定：**{refreshed.get('preset_winner_name') or refreshed.get('preset_winner_id')}**")
        else:
            st.info("🎲 当前为随机抽取模式")

        st.divider()
        st.subheader("远程触发开奖")
        if not is_bot_running():
            st.warning("Bot 未运行，请先在「Bot 控制」Tab 启动 Bot")
        else:
            env = load_env()
            try:
                trigger_gid = int(str(env.get("TELEGRAM_GROUP_ID", sel_lot4.get("group_id", 0))).strip())
            except (ValueError, TypeError):
                trigger_gid = sel_lot4.get("group_id", 0)

            if not participants:
                st.warning("暂无参与者，无法开奖")
            else:
                confirm = st.checkbox(f"确认开奖「{sel_lot4['title']}」（{len(participants)} 人参与）")
                if confirm:
                    if st.button("🎉 立即开奖", type="primary", use_container_width=True):
                        db.push_draw_signal(lot_id4, trigger_gid)
                        st.success("开奖信号已发送！Bot 将在 5 秒内在群内公布结果。")


# ── Tab 5: 积分管理 ──────────────────────────────────────────────

with tab5:
    env = load_env()
    gid_points = int(env.get("TELEGRAM_GROUP_ID", "0") or "0")

    st.subheader("积分规则配置")
    st.caption("勾选启用后，Bot 会自动在对应事件时给用户发放积分。修改后重启 Bot 立即生效。")

    if not gid_points:
        st.warning("请先在主配置界面设置群组 ID（TELEGRAM_GROUP_ID）")
    else:
        rules = db.get_point_rules(gid_points)

        rule_configs = {}
        rule_meta = {
            "per_message":  ("每条消息获得积分", "用户在群内每发一条消息就获得积分"),
            "daily_first":  ("每日首次发言奖励", "每天第一条消息额外获得积分，Bot 会在群内发通知"),
            "join":         ("加入群组奖励",     "新成员加入群组时获得积分，Bot 会在群内欢迎"),
        }

        for rt, (label, help_text) in rule_meta.items():
            rule = rules.get(rt, {"enabled": 0, "points": 1})
            with st.container(border=True):
                c1, c2 = st.columns([3, 1])
                with c1:
                    enabled = st.checkbox(f"**{label}**", value=bool(rule.get("enabled")),
                                          key=f"rule_en_{rt}", help=help_text)
                with c2:
                    pts = st.number_input("积分数", min_value=1, max_value=9999,
                                          value=int(rule.get("points", 1)),
                                          key=f"rule_pts_{rt}")
            rule_configs[rt] = {"enabled": enabled, "points": pts}

        if st.button("💾 保存积分规则", type="primary"):
            db.save_point_rules(gid_points, rule_configs)
            st.success("积分规则已保存！")

    st.divider()
    st.subheader("用户积分查询与调整")

    if gid_points:
        # 搜索用户
        search_user = st.text_input("搜索用户（名字或用户名）", key="points_search")
        if search_user:
            members_found = db.search_members(gid_points, search_user, limit=20)
        else:
            members_found = []

        # 手动加减分
        with st.form("manual_points_form"):
            st.markdown("**手动加减分**")
            col_uid, col_amt, col_reason = st.columns([2, 1, 2])
            with col_uid:
                if members_found:
                    uid_opts = {
                        f"{m['display_name']}" + (f" (@{m['username']})" if m.get("username") else "") +
                        f" [{m['user_id']}]": m["user_id"]
                        for m in members_found
                    }
                    sel_uid_label = st.selectbox("选择用户", list(uid_opts.keys()))
                    manual_uid = uid_opts[sel_uid_label]
                else:
                    manual_uid = st.number_input("用户 ID", min_value=1, value=1, step=1)
            with col_amt:
                manual_amount = st.number_input("积分数量（负数为扣分）",
                                                 min_value=-99999, max_value=99999, value=10)
            with col_reason:
                manual_reason = st.text_input("备注", value="管理员手动调整")

            if st.form_submit_button("执行"):
                uid_val = int(manual_uid) if not isinstance(manual_uid, int) else manual_uid
                new_bal = db.add_points(gid_points, uid_val, manual_amount, manual_reason)
                if new_bal == -1:
                    st.error("操作失败：余额不足")
                else:
                    action = "添加" if manual_amount > 0 else "扣除"
                    st.success(f"✅ 已{action} {abs(manual_amount)} 积分，用户 {uid_val} 当前余额：{new_bal} 分")

        st.divider()
        st.subheader("积分排行榜")
        top_n = st.slider("显示前 N 名", min_value=5, max_value=50, value=10)
        leaderboard = db.get_leaderboard(gid_points, limit=top_n)

        if leaderboard:
            lb_df = pd.DataFrame(leaderboard)
            lb_df.index = range(1, len(lb_df) + 1)
            rename_map = {
                "display_name": "名字", "username": "用户名",
                "balance": "当前积分", "total_earned": "累计获得", "message_count": "发言数"
            }
            show_cols = [c for c in rename_map if c in lb_df.columns]
            lb_df = lb_df[show_cols].rename(columns=rename_map)
            st.dataframe(lb_df, use_container_width=True)
        else:
            st.info("暂无积分数据。启用积分规则后，用户发言即开始积累。")

        st.divider()
        st.subheader("全部用户积分")
        all_points = db.get_all_user_points(gid_points)
        if all_points:
            all_df = pd.DataFrame(all_points)
            rename_all = {
                "user_id": "用户 ID", "display_name": "名字", "username": "用户名",
                "balance": "余额", "total_earned": "累计获得", "total_spent": "累计消耗",
                "message_count": "发言数", "first_seen_at": "首次记录"
            }
            show_all = [c for c in rename_all if c in all_df.columns]
            all_df = all_df[show_all].rename(columns=rename_all)
            st.dataframe(all_df, use_container_width=True, hide_index=True)

            csv = all_df.to_csv(index=False, encoding="utf-8-sig")
            st.download_button("⬇️ 导出积分数据 CSV", data=csv.encode("utf-8-sig"),
                               file_name="user_points.csv", mime="text/csv")
        else:
            st.info("暂无用户积分数据。")


# ── Tab 6: 历史记录 ──────────────────────────────────────────────

with tab6:
    st.subheader("历史记录")
    history = db.get_history(limit=50)
    if not history:
        st.info("暂无历史记录。")
    else:
        df_hist = pd.DataFrame(history)
        display_cols = {
            "id": "记录 ID", "title": "活动名称", "winner_name": "中奖者",
            "total_participants": "参与人数", "preset_used": "是否内定", "finished_at": "结束时间",
        }
        df_show = df_hist[[c for c in display_cols if c in df_hist.columns]].copy()
        df_show.rename(columns=display_cols, inplace=True)
        if "是否内定" in df_show.columns:
            df_show["是否内定"] = df_show["是否内定"].map({0: "否", 1: "是"})
        st.dataframe(df_show, use_container_width=True, hide_index=True)

        csv = df_show.to_csv(index=False, encoding="utf-8-sig")
        st.download_button("⬇️ 导出 CSV", data=csv.encode("utf-8-sig"),
                           file_name="lottery_history.csv", mime="text/csv")

        st.divider()
        st.subheader("查看参与者详情")
        hist_opts = {f"#{h['id']} {h['title']} — {h['finished_at'][:10]}": h for h in history}
        sel_hist = st.selectbox("选择记录", list(hist_opts.keys()))
        if sel_hist:
            record = hist_opts[sel_hist]
            try:
                snapshot = json.loads(record.get("snapshot_json", "{}"))
                ps = snapshot.get("participants", [])
                if ps:
                    p_df = pd.DataFrame(ps)
                    show = [c for c in ["display_name", "username", "user_id", "joined_at"] if c in p_df.columns]
                    st.markdown(f"**参与者名单（共 {len(ps)} 人）**")
                    st.dataframe(p_df[show], use_container_width=True, hide_index=True)
                else:
                    st.info("无参与者数据")
            except Exception:
                st.info("无法解析详情")
