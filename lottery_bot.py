"""
lottery_bot.py - Telegram 抽奖机器人（aiogram 3.x）

功能：
- /start_lottery <id>      : 管理员发布抽奖公告
- /draw <id>               : 管理员开奖，公布结果
- /cancel_lottery <id>     : 管理员取消活动
- /lottery_status          : 查看当前活跃抽奖
- /score                   : 查询自己的积分
- /leaderboard             : 积分排行榜
- /addpoints <用户ID> <分数>  : 管理员手动加分
- /removepoints <用户ID> <分数>: 管理员手动减分
- 参与按钮回调              : 用户参与抽奖（含条件检查 + 积分扣除）
- 消息监听                  : 自动根据规则发放积分
- 新成员加入                : 自动发放入群积分
"""

import asyncio
import logging
import os
import random
import sys

from dotenv import load_dotenv
load_dotenv()

import lottery_db as db
from lottery_db import ConditionError, STATUS_LABELS, DEFAULT_RESULT_TEMPLATE

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logging.getLogger("aiogram").setLevel(logging.WARNING)  # 抑制 aiogram 内部心跳等 INFO 日志
logger = logging.getLogger("lottery_bot")

BOT_TOKEN = os.getenv("LOTTERY_BOT_TOKEN", "")
POLL_INTERVAL = 5

if not BOT_TOKEN:
    logger.error("缺少 LOTTERY_BOT_TOKEN，请在 .env 中配置")
    sys.exit(1)

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    ChatMemberUpdated,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from aiogram.exceptions import TelegramBadRequest

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


# ── 权限检查 ─────────────────────────────────────────────────────

async def is_admin(chat_id: int, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in ("creator", "administrator")
    except Exception:
        return False


# ── 公告文本构建 ─────────────────────────────────────────────────

def build_announce_text(lottery: dict, participant_count: int) -> str:
    title = lottery.get("title") or "抽奖活动"
    desc = lottery.get("description") or ""
    keyword = lottery.get("keyword") or ""
    min_points = lottery.get("min_points") or 0
    min_messages = lottery.get("min_messages") or 0
    min_days = lottery.get("min_days") or 0
    points_cost = lottery.get("points_cost") or 0

    lines = [f"🎁 *{title}*"]
    if desc:
        lines.append(f"\n{desc}")

    conditions = []
    if min_points > 0:
        conditions.append(f"持有积分 ≥ {min_points}")
    if min_messages > 0:
        conditions.append(f"群内发言 ≥ {min_messages} 条")
    if min_days > 0:
        conditions.append(f"入群满 {min_days} 天")
    if points_cost > 0:
        conditions.append(f"消耗 {points_cost} 积分")
    if keyword:
        conditions.append(f"发送口令「{keyword}」")

    if conditions:
        lines.append("\n📋 *参与条件：*")
        for c in conditions:
            lines.append(f"  • {c}")

    lines.append(f"\n👥 当前参与人数：{participant_count}")
    lines.append("\n点击下方按钮参与 👇")
    return "\n".join(lines)


def build_join_keyboard(lottery_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="参与抽奖 🎁", callback_data=f"join:{lottery_id}")
    ]])


async def refresh_announce_message(lottery: dict):
    msg_id = lottery.get("announce_msg_id")
    if not msg_id or lottery.get("status") != "active":
        return
    count = db.count_participants(lottery["id"])
    text = build_announce_text(lottery, count)
    try:
        await bot.edit_message_text(
            chat_id=lottery["group_id"],
            message_id=msg_id,
            text=text,
            reply_markup=build_join_keyboard(lottery["id"]),
            parse_mode="Markdown",
        )
    except TelegramBadRequest:
        pass


# ── 积分：处理消息事件 ────────────────────────────────────────────

async def award_message_points(group_id: int, user_id: int,
                                username: str, display_name: str):
    """根据规则给发言用户发放积分"""
    rules = db.get_point_rules(group_id)

    # 消息计数（始终记录，不论是否启用积分）
    db.increment_message_count(group_id, user_id, username, display_name)

    # per_message 规则
    rule = rules.get("per_message", {})
    if rule.get("enabled") and rule.get("points", 0) > 0:
        pts = int(rule["points"])
        db.add_points(group_id, user_id, pts, "发送消息", username, display_name)

    # daily_first 规则
    rule = rules.get("daily_first", {})
    if rule.get("enabled") and rule.get("points", 0) > 0:
        if db.check_and_mark_daily_first(group_id, user_id):
            pts = int(rule["points"])
            db.add_points(group_id, user_id, pts, "每日首次发言", username, display_name)
            try:
                await bot.send_message(
                    chat_id=group_id,
                    text=f"🌟 {display_name} 今日首次发言，获得 {pts} 积分！",
                )
            except Exception:
                pass


# ── 命令：/start_lottery <id> ────────────────────────────────────

@dp.message(Command("start_lottery"))
async def cmd_start_lottery(message: Message):
    if not await is_admin(message.chat.id, message.from_user.id):
        await message.reply("仅群主或管理员可使用此命令。")
        return

    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        await message.reply("用法：/start_lottery <活动ID>")
        return

    lottery_id = int(args[1])
    lottery = db.get_lottery(lottery_id)

    if not lottery:
        await message.reply(f"活动 #{lottery_id} 不存在。")
        return
    if lottery["status"] != "draft":
        await message.reply(f"活动当前状态为「{STATUS_LABELS.get(lottery['status'], lottery['status'])}」，无法发布。")
        return

    count = db.count_participants(lottery_id)
    text = build_announce_text(lottery, count)
    sent = await message.answer(text, reply_markup=build_join_keyboard(lottery_id), parse_mode="Markdown")

    db.update_lottery(lottery_id, {
        "status": "active",
        "announce_msg_id": sent.message_id,
        "group_id": message.chat.id,
    })
    logger.info(f"活动 #{lottery_id} 已发布")


# ── 命令：/draw <id> ─────────────────────────────────────────────

@dp.message(Command("draw"))
async def cmd_draw(message: Message):
    if not await is_admin(message.chat.id, message.from_user.id):
        await message.reply("仅群主或管理员可使用此命令。")
        return

    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        await message.reply("用法：/draw <活动ID>")
        return

    await execute_draw(int(args[1]), message.chat.id)


async def execute_draw(lottery_id: int, chat_id: int):
    lottery = db.get_lottery(lottery_id)
    if not lottery:
        await bot.send_message(chat_id, f"活动 #{lottery_id} 不存在。")
        return
    if lottery["status"] != "active":
        await bot.send_message(chat_id, f"活动状态为「{STATUS_LABELS.get(lottery['status'], lottery['status'])}」，无法开奖。")
        return

    participants = db.get_participants(lottery_id)
    if not participants:
        await bot.send_message(chat_id, "暂无参与者，无法开奖。")
        return

    # 确定获奖者
    preset_id = lottery.get("preset_winner_id")
    winner = None
    if preset_id:
        winner = next((p for p in participants if p["user_id"] == preset_id), None)
    if not winner:
        winner = random.choice(participants)

    winner_name = winner.get("display_name") or winner.get("username") or str(winner["user_id"])
    template = lottery.get("result_template") or DEFAULT_RESULT_TEMPLATE
    result_text = template.format(winner=winner_name)

    full_text = (
        f"🎉 *{lottery.get('title', '抽奖')}* 开奖结果\n\n"
        f"{result_text}\n\n"
        f"📊 共 {len(participants)} 人参与"
    )
    await bot.send_message(chat_id, full_text, parse_mode="Markdown")

    db.update_lottery(lottery_id, {
        "status": "finished",
        "winner_id": winner["user_id"],
        "winner_name": winner_name,
    })
    db.archive_lottery(lottery_id)
    logger.info(f"活动 #{lottery_id} 开奖完成，获奖者：{winner_name}")


# ── 命令：/cancel_lottery <id> ───────────────────────────────────

@dp.message(Command("cancel_lottery"))
async def cmd_cancel_lottery(message: Message):
    if not await is_admin(message.chat.id, message.from_user.id):
        await message.reply("仅群主或管理员可使用此命令。")
        return

    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        await message.reply("用法：/cancel_lottery <活动ID>")
        return

    lottery_id = int(args[1])
    lottery = db.get_lottery(lottery_id)
    if not lottery:
        await message.reply(f"活动 #{lottery_id} 不存在。")
        return
    if lottery["status"] in ("finished", "cancelled"):
        await message.reply("活动已结束或已取消。")
        return

    db.update_lottery(lottery_id, {"status": "cancelled"})
    await message.reply(f"活动 #{lottery_id}「{lottery['title']}」已取消。")


# ── 命令：/lottery_status ────────────────────────────────────────

@dp.message(Command("lottery_status"))
async def cmd_lottery_status(message: Message):
    active = db.list_lotteries(status="active")
    if not active:
        await message.reply("当前没有进行中的抽奖活动。")
        return
    lines = ["📋 *当前活跃抽奖*\n"]
    for lot in active:
        count = db.count_participants(lot["id"])
        lines.append(f"• ID `{lot['id']}` — {lot['title']} （{count} 人参与）")
    await message.reply("\n".join(lines), parse_mode="Markdown")


# ── 命令：/score ─────────────────────────────────────────────────

@dp.message(Command("score"))
async def cmd_score(message: Message):
    user = message.from_user
    group_id = message.chat.id
    user_data = db.get_user_points(group_id, user.id)

    if not user_data:
        await message.reply("你还没有积分记录，在群内发言即可开始积累积分！")
        return

    name = user_data.get("display_name") or user.full_name or str(user.id)
    lines = [
        f"📊 *{name} 的积分*\n",
        f"💰 当前余额：**{user_data['balance']}** 分",
        f"📈 累计获得：{user_data['total_earned']} 分",
        f"📉 累计消耗：{user_data['total_spent']} 分",
        f"💬 群内发言：{user_data['message_count']} 条",
    ]
    await message.reply("\n".join(lines), parse_mode="Markdown")


# ── 命令：/leaderboard ───────────────────────────────────────────

@dp.message(Command("leaderboard"))
async def cmd_leaderboard(message: Message):
    group_id = message.chat.id
    top = db.get_leaderboard(group_id, limit=10)

    if not top:
        await message.reply("暂无积分数据。")
        return

    lines = ["🏆 *积分排行榜 Top 10*\n"]
    medals = ["🥇", "🥈", "🥉"]
    for i, u in enumerate(top):
        name = u.get("display_name") or u.get("username") or str(u["user_id"])
        prefix = medals[i] if i < 3 else f"{i + 1}."
        lines.append(f"{prefix} {name} — **{u['balance']}** 分")

    await message.reply("\n".join(lines), parse_mode="Markdown")


# ── 命令：/addpoints <用户ID> <分数> ────────────────────────────

@dp.message(Command("addpoints"))
async def cmd_addpoints(message: Message):
    if not await is_admin(message.chat.id, message.from_user.id):
        await message.reply("仅管理员可使用此命令。")
        return

    args = message.text.split()
    if len(args) < 3 or not args[1].lstrip("-").isdigit() or not args[2].isdigit():
        await message.reply("用法：/addpoints <用户ID> <分数>\n例：/addpoints 123456789 50")
        return

    target_uid = int(args[1])
    amount = int(args[2])
    group_id = message.chat.id

    new_balance = db.add_points(group_id, target_uid, amount, "管理员手动添加")
    if new_balance == -1:
        await message.reply("操作失败：余额不足。")
        return

    await message.reply(f"✅ 已为用户 `{target_uid}` 添加 {amount} 积分，当前余额：{new_balance} 分。",
                         parse_mode="Markdown")


# ── 命令：/removepoints <用户ID> <分数> ─────────────────────────

@dp.message(Command("removepoints"))
async def cmd_removepoints(message: Message):
    if not await is_admin(message.chat.id, message.from_user.id):
        await message.reply("仅管理员可使用此命令。")
        return

    args = message.text.split()
    if len(args) < 3 or not args[1].lstrip("-").isdigit() or not args[2].isdigit():
        await message.reply("用法：/removepoints <用户ID> <分数>\n例：/removepoints 123456789 20")
        return

    target_uid = int(args[1])
    amount = int(args[2])
    group_id = message.chat.id

    new_balance = db.add_points(group_id, target_uid, -amount, "管理员手动扣除")
    if new_balance == -1:
        user_data = db.get_user_points(group_id, target_uid)
        current = user_data["balance"] if user_data else 0
        await message.reply(f"操作失败：用户当前余额 {current} 分，无法扣除 {amount} 分。")
        return

    await message.reply(f"✅ 已扣除用户 `{target_uid}` 的 {amount} 积分，当前余额：{new_balance} 分。",
                         parse_mode="Markdown")


# ── 参与按钮回调 ─────────────────────────────────────────────────

@dp.callback_query(F.data.startswith("join:"))
async def cb_join_lottery(query: CallbackQuery):
    lottery_id = int(query.data.split(":")[1])
    user = query.from_user
    lottery = db.get_lottery(lottery_id)

    if not lottery or lottery["status"] != "active":
        await query.answer("活动已结束或不存在。", show_alert=True)
        return

    group_id = lottery["group_id"] or query.message.chat.id
    display_name = user.full_name or user.username or str(user.id)
    username = user.username or ""

    # 非积分参与条件前置检查（入群天数、发言数等不在事务内的检查）
    try:
        db.check_participation_conditions(lottery, group_id, user.id)
    except ConditionError as e:
        await query.answer(str(e), show_alert=True)
        return

    # 原子操作：条件复验 + 扣积分 + 插入参与者
    result = db.atomic_join(lottery_id, lottery, group_id, user.id, username, display_name)

    if result == "already":
        await query.answer("您已经参与过本次抽奖！", show_alert=True)
        return
    if result == "inactive":
        await query.answer("活动已结束。", show_alert=True)
        return
    if result == "insufficient":
        points_cost = lottery.get("points_cost", 0) or 0
        user_data = db.get_user_points(group_id, user.id)
        balance = user_data["balance"] if user_data else 0
        await query.answer(f"积分不足！参与需要 {points_cost} 分，你当前有 {balance} 分。", show_alert=True)
        return

    points_cost = lottery.get("points_cost", 0) or 0
    tip = f"，已扣除 {points_cost} 积分" if points_cost > 0 else ""
    await query.answer(f"参与成功！祝您好运 🍀{tip}", show_alert=True)
    await refresh_announce_message(lottery)
    logger.info(f"用户 {display_name}（{user.id}）参与了活动 #{lottery_id}")


# ── 口令参与监听 ─────────────────────────────────────────────────

@dp.message(F.text & F.chat.type.in_({"group", "supergroup"}))
async def handle_group_message(message: Message):
    if not message.from_user or message.from_user.is_bot:
        return

    user = message.from_user
    group_id = message.chat.id
    display_name = user.full_name or user.username or str(user.id)
    username = user.username or ""

    # 积分：处理发言事件
    await award_message_points(group_id, user.id, username, display_name)

    # 口令抽奖参与检查
    text = (message.text or "").strip()
    if not text:
        return

    active_lotteries = db.list_lotteries(status="active")
    for lottery in active_lotteries:
        keyword = (lottery.get("keyword") or "").strip()
        if not keyword or keyword != text:
            continue
        if lottery.get("group_id") and lottery["group_id"] != group_id:
            continue
        if db.is_participant(lottery["id"], user.id):
            continue

        # 非积分条件前置检查
        try:
            db.check_participation_conditions(lottery, group_id, user.id)
        except ConditionError as e:
            await message.reply(f"❌ {e}")
            break

        # 原子操作：条件复验 + 扣积分 + 插入
        result = db.atomic_join(lottery["id"], lottery, group_id, user.id, username, display_name)

        if result == "already":
            break  # 已参与，静默跳过
        if result == "insufficient":
            points_cost = lottery.get("points_cost", 0) or 0
            user_data = db.get_user_points(group_id, user.id)
            balance = user_data["balance"] if user_data else 0
            await message.reply(f"❌ 积分不足，参与需要 {points_cost} 分，你当前有 {balance} 分。")
            break
        if result == "inactive":
            break

        points_cost = lottery.get("points_cost", 0) or 0
        tip = f"，已扣除 {points_cost} 积分" if points_cost > 0 else ""
        await message.reply(f"✅ {display_name} 口令正确，已成功参与「{lottery['title']}」！🎉{tip}")
        await refresh_announce_message(lottery)
        break


# ── 新成员加入：发放入群积分 ─────────────────────────────────────

@dp.chat_member()
async def handle_new_member(event: ChatMemberUpdated):
    old_status = event.old_chat_member.status
    new_status = event.new_chat_member.status

    # 只处理"加入"事件（非成员/被踢 → 成员/管理员）
    if old_status in ("left", "kicked", "restricted") and new_status in ("member", "administrator"):
        user = event.new_chat_member.user
        if user.is_bot:
            return

        group_id = event.chat.id
        display_name = user.full_name or user.username or str(user.id)
        username = user.username or ""

        rules = db.get_point_rules(group_id)
        rule = rules.get("join", {})
        if rule.get("enabled") and rule.get("points", 0) > 0:
            pts = int(rule["points"])
            db.add_points(group_id, user.id, pts, "加入群组奖励", username, display_name)
            try:
                await bot.send_message(
                    chat_id=group_id,
                    text=f"👋 欢迎 {display_name} 加入！获得入群奖励 {pts} 积分！",
                )
            except Exception:
                pass


# ── 后台轮询：响应 Web UI 的开奖信号 ────────────────────────────

async def poll_pending_signals():
    while True:
        await asyncio.sleep(POLL_INTERVAL)
        try:
            signal = db.pop_draw_signal()
            if signal:
                lottery = db.get_lottery(signal["lottery_id"])
                # 校验 chat_id 必须与活动绑定的群组一致，防止向任意群发消息
                if lottery and lottery["group_id"] and lottery["group_id"] != signal["chat_id"]:
                    logger.warning(
                        f"信号 chat_id={signal['chat_id']} 与活动 group_id={lottery['group_id']} 不符，已忽略"
                    )
                    continue
                logger.info(f"收到 UI 开奖信号：活动 #{signal['lottery_id']}")
                await execute_draw(signal["lottery_id"], signal["chat_id"])
        except Exception as e:
            logger.error(f"处理信号时出错：{e}")


# ── 启动 ─────────────────────────────────────────────────────────

async def main():
    db.init_db()
    logger.info("抽奖机器人启动中...")
    asyncio.create_task(poll_pending_signals())
    await dp.start_polling(
        bot,
        allowed_updates=["message", "callback_query", "chat_member"]
    )


if __name__ == "__main__":
    asyncio.run(main())
