"""
lottery_db.py - 抽奖机器人 SQLite 数据访问层

供 lottery_bot.py（异步进程）和 lottery_ui.py（Streamlit 进程）共享使用。
启用 WAL 模式支持两个进程并发读写。
"""

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

# 共享常量，避免多处硬编码
DEFAULT_RESULT_TEMPLATE = "🏆 恭喜 {winner} 获奖！感谢大家参与！"
STATUS_LABELS = {
    "draft":     "草稿",
    "active":    "进行中",
    "finished":  "已结束",
    "cancelled": "已取消",
}
LOCAL_TZ = ZoneInfo("Asia/Shanghai")

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lottery.db")

DDL = """
CREATE TABLE IF NOT EXISTS lotteries (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    title               TEXT    NOT NULL DEFAULT '',
    description         TEXT    NOT NULL DEFAULT '',
    group_id            INTEGER NOT NULL DEFAULT 0,
    status              TEXT    NOT NULL DEFAULT 'draft',
    preset_winner_id    INTEGER,
    preset_winner_name  TEXT    NOT NULL DEFAULT '',
    winner_id           INTEGER,
    winner_name         TEXT    NOT NULL DEFAULT '',
    announce_msg_id     INTEGER,
    keyword             TEXT    NOT NULL DEFAULT '',
    result_template     TEXT    NOT NULL DEFAULT '🏆 恭喜 {winner} 获奖！感谢大家参与！',
    -- 参与条件
    min_points          INTEGER NOT NULL DEFAULT 0,
    min_messages        INTEGER NOT NULL DEFAULT 0,
    min_days            INTEGER NOT NULL DEFAULT 0,
    -- 积分消耗
    points_cost         INTEGER NOT NULL DEFAULT 0,
    created_by          INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS participants (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    lottery_id      INTEGER NOT NULL REFERENCES lotteries(id) ON DELETE CASCADE,
    user_id         INTEGER NOT NULL,
    username        TEXT    NOT NULL DEFAULT '',
    display_name    TEXT    NOT NULL DEFAULT '',
    joined_at       TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE(lottery_id, user_id)
);

CREATE TABLE IF NOT EXISTS group_members_cache (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id        INTEGER NOT NULL,
    user_id         INTEGER NOT NULL,
    username        TEXT    NOT NULL DEFAULT '',
    display_name    TEXT    NOT NULL DEFAULT '',
    is_bot          INTEGER NOT NULL DEFAULT 0,
    cached_at       TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE(group_id, user_id)
);

CREATE TABLE IF NOT EXISTS pending_signals (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    action      TEXT    NOT NULL,
    lottery_id  INTEGER NOT NULL,
    chat_id     INTEGER NOT NULL,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS lottery_history (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    lottery_id          INTEGER NOT NULL,
    title               TEXT    NOT NULL,
    group_id            INTEGER NOT NULL,
    winner_user_id      INTEGER,
    winner_name         TEXT    NOT NULL DEFAULT '',
    total_participants  INTEGER NOT NULL DEFAULT 0,
    preset_used         INTEGER NOT NULL DEFAULT 0,
    finished_at         TEXT    NOT NULL DEFAULT (datetime('now')),
    snapshot_json       TEXT    NOT NULL DEFAULT '{}'
);

-- ── 积分系统 ────────────────────────────────────────────────────

-- 用户积分账户（每个群独立）
CREATE TABLE IF NOT EXISTS user_points (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id        INTEGER NOT NULL,
    user_id         INTEGER NOT NULL,
    username        TEXT    NOT NULL DEFAULT '',
    display_name    TEXT    NOT NULL DEFAULT '',
    balance         INTEGER NOT NULL DEFAULT 0,
    total_earned    INTEGER NOT NULL DEFAULT 0,
    total_spent     INTEGER NOT NULL DEFAULT 0,
    message_count   INTEGER NOT NULL DEFAULT 0,
    first_seen_at   TEXT    NOT NULL DEFAULT (datetime('now')),
    last_seen_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE(group_id, user_id)
);

-- 积分流水记录
CREATE TABLE IF NOT EXISTS point_transactions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id    INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    amount      INTEGER NOT NULL,
    balance_after INTEGER NOT NULL DEFAULT 0,
    reason      TEXT    NOT NULL DEFAULT '',
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- 积分规则配置（每个群独立）
-- rule_type: 'per_message'（每条消息）| 'daily_first'（每日首次发言）| 'join'（加入群组）
CREATE TABLE IF NOT EXISTS point_rules (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id    INTEGER NOT NULL,
    rule_type   TEXT    NOT NULL,
    points      INTEGER NOT NULL DEFAULT 1,
    enabled     INTEGER NOT NULL DEFAULT 1,
    UNIQUE(group_id, rule_type)
);

-- 每日首次发言记录（用于 daily_first 规则去重）
CREATE TABLE IF NOT EXISTS daily_first_seen (
    group_id    INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    date        TEXT    NOT NULL,
    PRIMARY KEY (group_id, user_id, date)
);

CREATE INDEX IF NOT EXISTS idx_participants_lottery ON participants(lottery_id);
CREATE INDEX IF NOT EXISTS idx_lotteries_status ON lotteries(status);
CREATE INDEX IF NOT EXISTS idx_cache_group ON group_members_cache(group_id);
CREATE INDEX IF NOT EXISTS idx_points_group ON user_points(group_id);
CREATE INDEX IF NOT EXISTS idx_transactions_user ON point_transactions(group_id, user_id);
"""

# 迁移：为已存在的 lotteries 表安全添加新列
MIGRATIONS = [
    "ALTER TABLE lotteries ADD COLUMN min_points INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE lotteries ADD COLUMN min_messages INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE lotteries ADD COLUMN min_days INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE lotteries ADD COLUMN points_cost INTEGER NOT NULL DEFAULT 0",
]


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _run_migrations(conn: sqlite3.Connection):
    """安全执行迁移，已有的列会被忽略"""
    for sql in MIGRATIONS:
        try:
            conn.execute(sql)
        except sqlite3.OperationalError:
            pass  # 列已存在，忽略


def init_db():
    with get_conn() as conn:
        conn.executescript(DDL)
        _run_migrations(conn)


def _row_to_dict(row) -> Optional[dict]:
    return dict(row) if row else None


# ── 抽奖活动 CRUD ────────────────────────────────────────────────

def create_lottery(title: str, description: str, group_id: int, created_by: int,
                   keyword: str = "", result_template: str = "",
                   min_points: int = 0, min_messages: int = 0,
                   min_days: int = 0, points_cost: int = 0) -> int:
    template = result_template or "🏆 恭喜 {winner} 获奖！感谢大家参与！"
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO lotteries
               (title, description, group_id, keyword, result_template, created_by,
                min_points, min_messages, min_days, points_cost)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (title, description, group_id, keyword, template, created_by,
             min_points, min_messages, min_days, points_cost)
        )
        return cur.lastrowid


def get_lottery(lottery_id: int) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM lotteries WHERE id = ?", (lottery_id,)).fetchone()
        return _row_to_dict(row)


_ALLOWED_LOTTERY_FIELDS = {
    "title", "description", "group_id", "status", "keyword", "result_template",
    "preset_winner_id", "preset_winner_name", "winner_id", "winner_name",
    "announce_msg_id", "min_points", "min_messages", "min_days", "points_cost",
    "updated_at",
}


def update_lottery(lottery_id: int, fields: dict):
    if not fields:
        return
    invalid = set(fields) - _ALLOWED_LOTTERY_FIELDS
    if invalid:
        raise ValueError(f"不允许更新的字段：{invalid}")
    fields["updated_at"] = datetime.now(timezone.utc).isoformat()
    cols = ", ".join(f"{k} = ?" for k in fields)
    vals = list(fields.values()) + [lottery_id]
    with get_conn() as conn:
        conn.execute(f"UPDATE lotteries SET {cols} WHERE id = ?", vals)


def list_lotteries(status: Optional[str] = None) -> list:
    with get_conn() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM lotteries WHERE status = ? ORDER BY id DESC", (status,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM lotteries ORDER BY id DESC").fetchall()
        return [_row_to_dict(r) for r in rows]


def delete_lottery(lottery_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM lotteries WHERE id = ?", (lottery_id,))


# ── 参与者 ───────────────────────────────────────────────────────

def add_participant(lottery_id: int, user_id: int, username: str, display_name: str) -> bool:
    try:
        with get_conn() as conn:
            conn.execute(
                """INSERT INTO participants (lottery_id, user_id, username, display_name)
                   VALUES (?, ?, ?, ?)""",
                (lottery_id, user_id, username or "", display_name or str(user_id))
            )
        return True
    except sqlite3.IntegrityError:
        return False


def is_participant(lottery_id: int, user_id: int) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM participants WHERE lottery_id = ? AND user_id = ?",
            (lottery_id, user_id)
        ).fetchone()
        return row is not None


def get_participants(lottery_id: int) -> list:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM participants WHERE lottery_id = ? ORDER BY joined_at",
            (lottery_id,)
        ).fetchall()
        return [_row_to_dict(r) for r in rows]


def count_participants(lottery_id: int) -> int:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM participants WHERE lottery_id = ?", (lottery_id,)
        ).fetchone()
        return row[0]


# ── 群成员缓存 ───────────────────────────────────────────────────

def upsert_members_cache(group_id: int, members: list):
    with get_conn() as conn:
        for m in members:
            conn.execute(
                """INSERT INTO group_members_cache
                   (group_id, user_id, username, display_name, is_bot, cached_at)
                   VALUES (?, ?, ?, ?, ?, datetime('now'))
                   ON CONFLICT(group_id, user_id) DO UPDATE SET
                     username = excluded.username,
                     display_name = excluded.display_name,
                     cached_at = excluded.cached_at""",
                (group_id, m["user_id"], m.get("username", ""),
                 m.get("display_name", ""), m.get("is_bot", 0))
            )


def search_members(group_id: int, keyword: str = "", limit: int = 100) -> list:
    with get_conn() as conn:
        if keyword:
            q = f"%{keyword.lower()}%"
            rows = conn.execute(
                """SELECT * FROM group_members_cache
                   WHERE group_id = ? AND is_bot = 0
                     AND (LOWER(display_name) LIKE ? OR LOWER(username) LIKE ?)
                   ORDER BY display_name LIMIT ?""",
                (group_id, q, q, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT * FROM group_members_cache
                   WHERE group_id = ? AND is_bot = 0
                   ORDER BY display_name LIMIT ?""",
                (group_id, limit)
            ).fetchall()
        return [_row_to_dict(r) for r in rows]


def get_cached_member(group_id: int, user_id: int) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM group_members_cache WHERE group_id = ? AND user_id = ?",
            (group_id, user_id)
        ).fetchone()
        return _row_to_dict(row)


# ── 积分系统 ─────────────────────────────────────────────────────

def _ensure_user_points(conn: sqlite3.Connection, group_id: int, user_id: int,
                         username: str = "", display_name: str = ""):
    """确保用户积分账户存在，不存在则创建"""
    conn.execute(
        """INSERT INTO user_points (group_id, user_id, username, display_name)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(group_id, user_id) DO UPDATE SET
             username = CASE WHEN excluded.username != '' THEN excluded.username ELSE username END,
             display_name = CASE WHEN excluded.display_name != '' THEN excluded.display_name ELSE display_name END,
             last_seen_at = datetime('now')""",
        (group_id, user_id, username or "", display_name or str(user_id))
    )


def get_user_points(group_id: int, user_id: int) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM user_points WHERE group_id = ? AND user_id = ?",
            (group_id, user_id)
        ).fetchone()
        return _row_to_dict(row)


def add_points(group_id: int, user_id: int, amount: int, reason: str,
               username: str = "", display_name: str = "") -> int:
    """
    给用户增加积分（amount 为负数时减分）。
    返回变动后的余额，若余额不足（减分超过余额）则返回 -1 且不执行。
    """
    with get_conn() as conn:
        _ensure_user_points(conn, group_id, user_id, username, display_name)
        row = conn.execute(
            "SELECT balance FROM user_points WHERE group_id = ? AND user_id = ?",
            (group_id, user_id)
        ).fetchone()
        current = row["balance"] if row else 0

        if amount < 0 and current + amount < 0:
            return -1  # 余额不足

        new_balance = current + amount
        conn.execute(
            """UPDATE user_points
               SET balance      = balance + ?,
                   total_earned = total_earned + CASE WHEN ? > 0 THEN ? ELSE 0 END,
                   total_spent  = total_spent  + CASE WHEN ? < 0 THEN -? ELSE 0 END,
                   last_seen_at = datetime('now')
               WHERE group_id = ? AND user_id = ?""",
            (amount, amount, amount, amount, amount, group_id, user_id)
        )
        conn.execute(
            """INSERT INTO point_transactions (group_id, user_id, amount, balance_after, reason)
               VALUES (?, ?, ?, ?, ?)""",
            (group_id, user_id, amount, new_balance, reason)
        )
        return new_balance


def increment_message_count(group_id: int, user_id: int,
                             username: str = "", display_name: str = ""):
    """消息计数 +1，同时更新 last_seen_at"""
    with get_conn() as conn:
        _ensure_user_points(conn, group_id, user_id, username, display_name)
        conn.execute(
            """UPDATE user_points
               SET message_count = message_count + 1, last_seen_at = datetime('now')
               WHERE group_id = ? AND user_id = ?""",
            (group_id, user_id)
        )


def check_and_mark_daily_first(group_id: int, user_id: int) -> bool:
    """
    检查今天是否是该用户在该群的首次发言。
    是则记录并返回 True，否则返回 False。
    """
    today = datetime.now(LOCAL_TZ).strftime("%Y-%m-%d")
    try:
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO daily_first_seen (group_id, user_id, date) VALUES (?, ?, ?)",
                (group_id, user_id, today)
            )
        return True
    except sqlite3.IntegrityError:
        return False  # 今天已经记录过


def get_leaderboard(group_id: int, limit: int = 10) -> list:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT user_id, username, display_name, balance, total_earned, message_count
               FROM user_points WHERE group_id = ?
               ORDER BY balance DESC, total_earned DESC LIMIT ?""",
            (group_id, limit)
        ).fetchall()
        return [_row_to_dict(r) for r in rows]


def get_all_user_points(group_id: int) -> list:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM user_points WHERE group_id = ?
               ORDER BY balance DESC""",
            (group_id,)
        ).fetchall()
        return [_row_to_dict(r) for r in rows]


def get_point_transactions(group_id: int, user_id: int, limit: int = 20) -> list:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM point_transactions
               WHERE group_id = ? AND user_id = ?
               ORDER BY created_at DESC LIMIT ?""",
            (group_id, user_id, limit)
        ).fetchall()
        return [_row_to_dict(r) for r in rows]


# ── 积分规则 ─────────────────────────────────────────────────────

DEFAULT_RULES = [
    {"rule_type": "per_message",  "points": 1, "enabled": 0},
    {"rule_type": "daily_first",  "points": 3, "enabled": 0},
    {"rule_type": "join",         "points": 10, "enabled": 0},
]

RULE_LABELS = {
    "per_message": "每条消息",
    "daily_first": "每日首次发言",
    "join":        "加入群组",
}


def get_point_rules(group_id: int) -> dict:
    """返回 {rule_type: {points, enabled}} 的字典，未配置的规则用默认值"""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM point_rules WHERE group_id = ?", (group_id,)
        ).fetchall()
    existing = {r["rule_type"]: _row_to_dict(r) for r in rows}
    result = {}
    for default in DEFAULT_RULES:
        rt = default["rule_type"]
        result[rt] = existing.get(rt, {**default, "group_id": group_id})
    return result


def save_point_rules(group_id: int, rules: dict):
    """rules: {rule_type: {points, enabled}}"""
    with get_conn() as conn:
        for rule_type, cfg in rules.items():
            conn.execute(
                """INSERT INTO point_rules (group_id, rule_type, points, enabled)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(group_id, rule_type) DO UPDATE SET
                     points = excluded.points,
                     enabled = excluded.enabled""",
                (group_id, rule_type, int(cfg.get("points", 1)),
                 1 if cfg.get("enabled") else 0)
            )


# ── 参与条件检查 ─────────────────────────────────────────────────

class ConditionError(Exception):
    """用户不满足参与条件时抛出，message 为给用户看的提示"""
    pass


def check_participation_conditions(lottery: dict, group_id: int, user_id: int) -> None:
    """
    检查用户是否满足参与条件。
    不满足时抛出 ConditionError，满足时正常返回。
    注意：此函数只检查，不扣分。扣分在 deduct_participation_cost 中进行。
    """
    min_points = lottery.get("min_points", 0) or 0
    min_messages = lottery.get("min_messages", 0) or 0
    min_days = lottery.get("min_days", 0) or 0
    points_cost = lottery.get("points_cost", 0) or 0

    if min_points == 0 and min_messages == 0 and min_days == 0 and points_cost == 0:
        return  # 无条件，直接通过

    user = get_user_points(group_id, user_id)

    if min_points > 0:
        balance = user["balance"] if user else 0
        if balance < min_points:
            raise ConditionError(f"需要持有至少 {min_points} 积分才能参与，你当前有 {balance} 积分。")

    if min_messages > 0:
        msg_count = user["message_count"] if user else 0
        if msg_count < min_messages:
            raise ConditionError(f"需要在群内发言 {min_messages} 条以上才能参与，你当前发言 {msg_count} 条。")

    if min_days > 0:
        if not user:
            raise ConditionError(f"需要加入群满 {min_days} 天才能参与。")
        first_seen = datetime.fromisoformat(user["first_seen_at"].replace("Z", "+00:00"))
        days = (datetime.now(timezone.utc) - first_seen).days
        if days < min_days:
            raise ConditionError(f"需要加入群满 {min_days} 天才能参与，你已加入 {days} 天。")

    if points_cost > 0:
        balance = user["balance"] if user else 0
        if balance < points_cost:
            raise ConditionError(f"参与此次抽奖需要消耗 {points_cost} 积分，你当前只有 {balance} 积分。")


def atomic_join(lottery_id: int, lottery: dict, group_id: int,
                user_id: int, username: str, display_name: str) -> str:
    """
    原子操作：检查条件 + 扣积分 + 插入参与者，在同一个事务中完成。
    返回值：
      'ok'            — 参与成功
      'already'       — 已参与过
      'insufficient'  — 积分不足
      'inactive'      — 活动不在进行中
    """
    points_cost = lottery.get("points_cost", 0) or 0
    with get_conn() as conn:
        # 锁定活动状态
        lot_row = conn.execute(
            "SELECT status FROM lotteries WHERE id = ?", (lottery_id,)
        ).fetchone()
        if not lot_row or lot_row["status"] != "active":
            return "inactive"

        # 重复参与检查
        dup = conn.execute(
            "SELECT 1 FROM participants WHERE lottery_id = ? AND user_id = ?",
            (lottery_id, user_id)
        ).fetchone()
        if dup:
            return "already"

        # 积分余额检查（在事务内读取，避免 TOCTOU）
        if points_cost > 0:
            _ensure_user_points(conn, group_id, user_id, username, display_name)
            bal_row = conn.execute(
                "SELECT balance FROM user_points WHERE group_id = ? AND user_id = ?",
                (group_id, user_id)
            ).fetchone()
            balance = bal_row["balance"] if bal_row else 0
            if balance < points_cost:
                return "insufficient"

        # 插入参与者
        conn.execute(
            "INSERT INTO participants (lottery_id, user_id, username, display_name) VALUES (?,?,?,?)",
            (lottery_id, user_id, username or "", display_name or str(user_id))
        )

        # 扣积分（插入成功后才扣，确保不会扣了但没参与）
        if points_cost > 0:
            new_balance = balance - points_cost
            conn.execute(
                """UPDATE user_points
                   SET balance = balance - ?, total_spent = total_spent + ?,
                       last_seen_at = datetime('now')
                   WHERE group_id = ? AND user_id = ?""",
                (points_cost, points_cost, group_id, user_id)
            )
            conn.execute(
                """INSERT INTO point_transactions (group_id, user_id, amount, balance_after, reason)
                   VALUES (?, ?, ?, ?, ?)""",
                (group_id, user_id, -points_cost, new_balance,
                 f"参与抽奖「{lottery.get('title', '')}」扣除")
            )

    return "ok"


# ── 跨进程信号（UI → Bot）────────────────────────────────────────

def push_draw_signal(lottery_id: int, chat_id: int):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO pending_signals (action, lottery_id, chat_id) VALUES ('draw', ?, ?)",
            (lottery_id, chat_id)
        )


def pop_draw_signal() -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM pending_signals WHERE action = 'draw' ORDER BY id LIMIT 1"
        ).fetchone()
        if row:
            conn.execute("DELETE FROM pending_signals WHERE id = ?", (row["id"],))
            return _row_to_dict(row)
        return None


# ── 历史归档 ─────────────────────────────────────────────────────

def archive_lottery(lottery_id: int):
    lottery = get_lottery(lottery_id)
    if not lottery:
        return
    participants = get_participants(lottery_id)
    preset_used = 1 if (lottery.get("preset_winner_id") and
                        lottery.get("winner_id") == lottery.get("preset_winner_id")) else 0
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO lottery_history
               (lottery_id, title, group_id, winner_user_id, winner_name,
                total_participants, preset_used, snapshot_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                lottery_id,
                lottery["title"],
                lottery["group_id"],
                lottery.get("winner_id"),
                lottery.get("winner_name", ""),
                len(participants),
                preset_used,
                json.dumps({"lottery": lottery, "participants": participants}, ensure_ascii=False),
            )
        )


def get_history(limit: int = 50) -> list:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM lottery_history ORDER BY finished_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
