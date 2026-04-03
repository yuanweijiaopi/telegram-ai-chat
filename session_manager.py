"""
Session 文件管理工具

负责三件事：
1. 检测重复手机号（多角色不能共用同一个号）
2. 清理孤立 session 文件（角色删除后遗留的文件）
3. 校验 session 与角色是否匹配（手机号改动后的错位检测）
"""

import glob
import os
from pathlib import Path


def validate_no_duplicate_phones(characters: list) -> None:
    """检查是否有多个角色配置了相同的手机号，有则抛出异常"""
    seen: dict[str, str] = {}
    for character in characters:
        phone = (character.get("phone") or "").strip()
        if not phone:
            continue
        if phone in seen:
            raise ValueError(
                f"手机号冲突：{phone} 同时被 [{seen[phone]}] 和 [{character['name']}] 使用，"
                "每个角色必须使用独立的手机号"
            )
        seen[phone] = character["name"]


def find_orphaned_sessions(characters: list, sessions_dir: str = "sessions") -> list[str]:
    """找出 sessions/ 目录下没有对应角色的孤立 .session 文件"""
    known_stems = {Path(c["session_file"]).stem for c in characters}
    orphaned = []
    for path in glob.glob(os.path.join(sessions_dir, "*.session")):
        if Path(path).stem not in known_stems:
            orphaned.append(path)
    return sorted(orphaned)


def cleanup_orphaned_sessions(characters: list, sessions_dir: str = "sessions") -> list[str]:
    """删除孤立 session 文件，返回已删除的文件列表"""
    orphaned = find_orphaned_sessions(characters, sessions_dir)
    removed = []
    for path in orphaned:
        try:
            os.remove(path)
            removed.append(path)
            # 同步删除 SQLite journal 文件
            for suffix in ("-journal", "-wal", "-shm"):
                companion = path + suffix
                if os.path.exists(companion):
                    os.remove(companion)
        except OSError as e:
            print(f"警告：无法删除孤立 session 文件 {path}：{e}")
    return removed


async def validate_session_identity(client, character: dict) -> tuple[bool, str]:
    """
    连接后验证 session 里存的账号是否与角色配置的手机号一致。

    Returns:
        (True, "") — 匹配或 session 未登录
        (False, reason) — 不匹配，reason 说明原因
    """
    try:
        me = await client.get_me()
    except Exception as e:
        return False, f"无法读取 session 账号信息：{e}"

    if me is None:
        return True, ""  # session 未登录，后续 client.start() 会处理

    config_phone = (character.get("phone") or "").strip().lstrip("+")
    session_phone = (str(me.phone or "")).strip().lstrip("+")

    if not config_phone:
        return True, ""  # 角色没配手机号，跳过校验

    if session_phone and session_phone != config_phone:
        return False, (
            f"session 文件 [{character['session_file']}] 存储的是手机号 +{session_phone}，"
            f"但角色 [{character['name']}] 配置的手机号是 +{config_phone}。\n"
            "请删除该 session 文件后重新登录，或检查角色配置是否填错。"
        )

    return True, ""