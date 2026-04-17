import os

import socks
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from shared.paths import SESSIONS_DIR, ensure_runtime_dirs


def session_file_for_character(name: str) -> str:
    safe_name = (name or "角色").replace("/", "_").replace("\\", "_").strip()
    ensure_runtime_dirs()
    os.makedirs(SESSIONS_DIR, exist_ok=True)
    return str(SESSIONS_DIR / f"{safe_name}.session")


def _preferred_character_id(name: str, index: int) -> str:
    return (name or f"角色{index+1}").strip() or f"角色{index+1}"


def _migrate_session_file(old_id: str, new_id: str) -> None:
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
        base_id = _preferred_character_id(item.get("name"), i)
        candidate_id = base_id
        suffix = 2
        while candidate_id in used_ids:
            candidate_id = f"{base_id}_{suffix}"
            suffix += 1
        _migrate_session_file(old_id, candidate_id)
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


async def get_login_status(
    api_id: str,
    api_hash: str,
    proxy_host: str,
    proxy_port: str,
    character: dict,
) -> dict:
    client = TelegramClient(
        session_file_for_character(character["id"]),
        int(api_id),
        api_hash,
        proxy=build_proxy(proxy_host, proxy_port),
    )
    try:
        await client.connect()
        me = await client.get_me()
        if me is None:
            return {"ok": False, "label": "未登录", "account": None, "phone": None, "match": False}
        me_phone = getattr(me, "phone", None)
        expected_phone = (character.get("phone") or "").replace("+", "").strip()
        actual_phone = (me_phone or "").replace("+", "").strip()
        is_match = expected_phone == actual_phone if expected_phone else True
        return {
            "ok": True,
            "label": f"已登录：{format_account_name(me, character['name'])}",
            "account": format_account_name(me, character["name"]),
            "phone": me_phone,
            "match": is_match,
        }
    finally:
        await client.disconnect()


async def send_login_code(
    api_id: str,
    api_hash: str,
    proxy_host: str,
    proxy_port: str,
    character: dict,
) -> dict:
    client = TelegramClient(
        session_file_for_character(character["id"]),
        int(api_id),
        api_hash,
        proxy=build_proxy(proxy_host, proxy_port),
    )
    try:
        await client.connect()
        me = await client.get_me()
        if me is not None:
            return {"status": "already", "account": format_account_name(me, character["name"])}
        sent = await client.send_code_request(character["phone"])
        return {"status": "code_sent", "phone_code_hash": sent.phone_code_hash}
    finally:
        await client.disconnect()


async def complete_login(
    api_id: str,
    api_hash: str,
    proxy_host: str,
    proxy_port: str,
    character: dict,
    code: str,
    phone_code_hash: str,
    password: str,
) -> dict:
    client = TelegramClient(
        session_file_for_character(character["id"]),
        int(api_id),
        api_hash,
        proxy=build_proxy(proxy_host, proxy_port),
    )
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


async def all_characters_logged_in(
    api_id: str,
    api_hash: str,
    proxy_host: str,
    proxy_port: str,
    characters: list[dict],
) -> tuple[bool, list[str]]:
    missing = []
    for char in characters:
        status = await get_login_status(api_id, api_hash, proxy_host, proxy_port, char)
        if not status["ok"]:
            missing.append(char["name"])
        elif not status.get("match", True):
            missing.append(f"{char['name']}（Session 与配置手机号不一致）")
    return len(missing) == 0, missing


def clear_character_session(character_id: str) -> None:
    session_path = session_file_for_character(character_id)
    journal_path = f"{session_path}-journal"
    if os.path.exists(session_path):
        os.remove(session_path)
    if os.path.exists(journal_path):
        os.remove(journal_path)


async def fetch_group_choices(
    api_id: str,
    api_hash: str,
    proxy_host: str,
    proxy_port: str,
    characters: list[dict],
):
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
        return sorted(
            merged_groups.values(),
            key=lambda current: ((current["name"] or "").strip().lower(), str(current["id"])),
        )

    detail = "；".join(errors) if errors else "没有找到可用的已登录会话"
    raise RuntimeError(detail)
