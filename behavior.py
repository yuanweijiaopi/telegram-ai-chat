import random
import time
from typing import Any


DEFAULT_BEHAVIOR_POLICY = {
    "max_context": 12,
    "max_history": 80,
    "max_consecutive_ai_turns": 2,
    "duplicate_window": 6,
    "min_seconds_between_replies": 45,
    "min_seconds_between_replies_human": 45,
    "min_seconds_between_replies_character": 8,
    "topic_prompt_style": "像群里真人一样自然起个头，不要像主持人。",
    "mention_reply_bonus": 0.25,
    "quiet_window_seconds": 180,
    "recent_reply_window_seconds": 90,
    "stale_pending_reply_seconds": 25,
    "same_sender_streak_limit": 3,
    "max_reply_sentences": 2,
    "disable_character_cooldown": True,
    "disable_character_move_on_cancel": True,
}


def merge_policy(*policies: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(DEFAULT_BEHAVIOR_POLICY)
    for policy in policies:
        if policy:
            merged.update(policy)
    return merged


def build_system_prompt(
    character: dict[str, Any],
    history: list[dict[str, Any]],
    global_rules: str,
    policy: dict[str, Any],
    mode: str = "reply",
) -> str:
    other_names = [name for name in policy.get("other_names", []) if name != character["name"]]
    context = format_history(history[-policy["max_context"] :])
    style_hint = random.choice(
        [
            "这次更像顺嘴接一句，不用把意思讲满。",
            "这次优先像真人插话，允许半句、反问、吐槽、接梗。",
            "这次别太工整，像聊天里随手回的一句。",
            "这次可以故意留白一点，不必正面回答完整。",
        ]
    )

    mode_instructions = {
        "reply": (
            "任务：延续当前对话，像正在群里实时聊天。"
            "优先接上一句的情绪、梗或潜台词，不要凭空换频道。"
            "不一定要正面回答，可以调侃、岔开一点、误解一下、顺手追问。"
        ),
        "topic": (
            "任务：自然发起一个新话题或轻轻续上最近氛围。"
            "像顺手说一句，不要像主持人开场。"
            "更像生活里的碎碎念、吐槽、临时想到的事，不要像标准提问。"
        ),
    }

    extra_rules = character.get("extra_rules", "")
    relationship_style = character.get("relationship_style", "")
    taboo_topics = character.get("taboo_topics", [])
    extra_rule_block = f"角色补充规则：{extra_rules}\n" if extra_rules else ""
    relationship_block = f"你和群友的互动偏好：{relationship_style}\n" if relationship_style else ""
    taboo_block = (
        f"尽量回避这些话题或角度：{'、'.join(taboo_topics)}\n" if taboo_topics else ""
    )
    return (
        f"你是群聊成员“{character['name']}”。\n"
        f"角色设定：{character['system']}\n\n"
        f"全局行为规则：{global_rules}\n"
        f"{extra_rule_block}"
        f"{relationship_block}"
        f"{taboo_block}"
        f"群里其他人：{'、'.join(other_names) if other_names else '暂无'}\n"
        f"最近聊天记录：\n{context or '暂无'}\n\n"
        f"{mode_instructions.get(mode, mode_instructions['reply'])}\n"
        f"风格提醒：{style_hint}\n"
        "输出要求：\n"
        "1. 只输出要发送的话，不要名字前缀，不要引号，不要解释。\n"
        f"2. 控制在 1 到 {policy['max_reply_sentences']} 句话，短句优先，也可以只有半句话。\n"
        "3. 避免复读、总结、说教、客服腔、AI 自述，避免标准问答题口吻。\n"
        "4. 优先用口语、碎句、语气词、插话感，不必把前因后果讲完整。\n"
        "5. 如果当前话题不适合接得太满，就轻一点、留白一点。"
    )


def format_history(history: list[dict[str, Any]]) -> str:
    lines = []
    for item in history:
        source = item.get("name", "未知")
        text = (item.get("text") or "").strip()
        if not text:
            continue
        lines.append(f"{source}: {text}")
    return "\n".join(lines)


def record_message(
    history: list[dict[str, Any]],
    policy: dict[str, Any],
    *,
    name: str,
    text: str,
    source: str,
) -> None:
    history.append(
        {
            "name": name,
            "text": text,
            "source": source,
            "timestamp": time.time(),
        }
    )
    max_history = policy["max_history"]
    if len(history) > max_history:
        del history[:-max_history]


def is_recent_duplicate_entry(
    history: list[dict[str, Any]],
    *,
    name: str,
    text: str,
    window: int = 3,
) -> bool:
    normalized = normalize_text(text)
    if not normalized:
        return True

    for item in reversed(history[-window:]):
        if item.get("name") != name:
            continue
        if normalize_text(item.get("text", "")) == normalized:
            return True
    return False


def should_reply(
    character: dict[str, Any],
    history: list[dict[str, Any]],
    policy: dict[str, Any],
    last_reply_at: dict[str, float],
    message_meta: dict[str, Any],
) -> tuple[bool, str]:
    if not history:
        return False, "no-history"

    scene = message_meta.get("scene", {})
    # 只在“人类消息刚被别的角色接过”时抑制跟风回复，
    # 避免所有角色都扑向同一条人类消息；角色之间的多轮对话仍然允许继续发展。
    if (
        message_meta.get("source") == "human"
        and scene.get("recent_other_character_reply")
        and not message_meta.get("is_direct_mention")
    ):
        return False, "recently-answered"

    if scene.get("same_sender_streak", 0) >= policy["same_sender_streak_limit"]:
        if not message_meta.get("is_direct_mention"):
            return False, "same-speaker-streak"

    reply_probability = resolve_reply_probability(character, policy, message_meta)
    if random.random() > reply_probability:
        return False, "probability-skip"

    last_message = history[-1]
    if last_message["name"] == character["name"]:
        return False, "self-last-message"

    min_gap = policy["min_seconds_between_replies_human"]
    if message_meta.get("source") == "character":
        if policy.get("disable_character_cooldown", False):
            min_gap = 0
        else:
            min_gap = policy.get(
                "min_seconds_between_replies_character",
                policy["min_seconds_between_replies_human"],
            )
    now = time.time()
    cooldown_until = last_reply_at.get(character["name"], 0) + min_gap
    if now < cooldown_until:
        return False, "cooldown"

    # 暂时关闭连续 AI 轮次限制。
    # 当前项目主要是双角色自聊，这条规则会把对话硬掐断；
    # 之后如果要混入真人群，再考虑按场景恢复成可配置开关。
    # consecutive_ai_turns = count_recent_ai_turns(history)
    # if consecutive_ai_turns >= policy["max_consecutive_ai_turns"]:
    #     return False, "too-many-ai-turns"

    if is_duplicate_risk(character["name"], history, policy["duplicate_window"]):
        return False, "duplicate-risk"

    return True, "ok"


def resolve_reply_probability(
    character: dict[str, Any],
    policy: dict[str, Any],
    message_meta: dict[str, Any],
) -> float:
    base_probability = character.get("reply_prob", 0)
    reply_probs = character.get("reply_probs", {})
    message_type = message_meta.get("message_type", "human")
    probability = reply_probs.get(message_type, base_probability)

    if message_meta.get("is_direct_mention"):
        probability += policy.get("mention_reply_bonus", 0)

    scene = message_meta.get("scene", {})
    if scene.get("is_quiet"):
        probability += character.get("scene_reply_bonus", {}).get("quiet", 0)
    if scene.get("recent_other_character_reply") and message_meta.get("source") == "human":
        probability += character.get("scene_reply_bonus", {}).get("recent_character_reply", 0)
    if scene.get("same_sender_streak", 0) >= 2:
        probability += character.get("scene_reply_bonus", {}).get("same_sender_streak", 0)

    return max(0.0, min(1.0, probability))


def detect_message_meta(
    *,
    text: str,
    sender_name: str,
    source: str,
    character_name: str,
    aliases: list[str],
) -> dict[str, Any]:
    lowered_text = normalize_text(text)
    normalized_aliases = [normalize_text(alias) for alias in aliases if normalize_text(alias)]
    is_direct_mention = any(alias in lowered_text for alias in normalized_aliases)
    message_type = "human"
    if source == "character":
        message_type = "character"
    elif is_direct_mention:
        message_type = "mention"

    return {
        "sender_name": sender_name,
        "source": source,
        "message_type": message_type,
        "is_direct_mention": is_direct_mention,
        "target_character": character_name,
    }


def enrich_message_meta(
    history: list[dict[str, Any]],
    policy: dict[str, Any],
    message_meta: dict[str, Any],
) -> dict[str, Any]:
    previous_message = history[-2] if len(history) >= 2 else None
    now = time.time()
    previous_gap_seconds = None
    if previous_message:
        previous_gap_seconds = max(0, int(now - previous_message.get("timestamp", now)))

    recent_other_character_reply = has_recent_character_reply(
        history[:-1],
        window_seconds=policy["recent_reply_window_seconds"],
        exclude_names=[message_meta.get("target_character")],
    )
    same_sender_streak = count_same_sender_streak(history)

    enriched = dict(message_meta)
    enriched["scene"] = {
        "is_quiet": previous_gap_seconds is not None
        and previous_gap_seconds >= policy["quiet_window_seconds"],
        "previous_gap_seconds": previous_gap_seconds,
        "recent_other_character_reply": recent_other_character_reply,
        "same_sender_streak": same_sender_streak,
    }
    return enriched


def should_send_after_delay(
    character: dict[str, Any],
    history: list[dict[str, Any]],
    policy: dict[str, Any],
    pending_text: str,
    pending_sender: str,
    message_meta: dict[str, Any],
) -> tuple[bool, str]:
    if not history:
        return False, "history-cleared"

    latest = history[-1]
    if normalize_text(latest.get("text", "")) != normalize_text(pending_text):
        if message_meta.get("is_direct_mention"):
            return True, "mention-kept"
        if (
            message_meta.get("source") == "character"
            and policy.get("disable_character_move_on_cancel", False)
        ):
            return True, "character-kept"
        if latest.get("source") == "character":
            return False, "conversation-moved-on"
        return False, "newer-human-message"

    if latest.get("name") != pending_sender:
        return False, "sender-changed"

    if (
        message_meta.get("source") == "character"
        and policy.get("disable_character_move_on_cancel", False)
    ):
        return True, "character-kept"

    if has_recent_character_reply(
        history[:-1],
        window_seconds=policy["stale_pending_reply_seconds"],
    ):
        return False, "someone-else-replied"

    return True, "ok"


def has_recent_character_reply(
    history: list[dict[str, Any]],
    window_seconds: int,
    exclude_names: list[str] | None = None,
) -> bool:
    now = time.time()
    excluded = set(exclude_names or [])
    for item in reversed(history):
        if item.get("source") != "character":
            continue
        if item.get("name") in excluded:
            continue
        age = now - item.get("timestamp", now)
        if age <= window_seconds:
            return True
        if age > window_seconds:
            break
    return False


def count_same_sender_streak(history: list[dict[str, Any]]) -> int:
    if not history:
        return 0

    sender_name = history[-1].get("name")
    total = 0
    for item in reversed(history):
        if item.get("name") != sender_name:
            break
        total += 1
    return total


def count_recent_ai_turns(history: list[dict[str, Any]]) -> int:
    total = 0
    for item in reversed(history):
        if item.get("source") != "character":
            break
        total += 1
    return total


def is_duplicate_risk(name: str, history: list[dict[str, Any]], window: int) -> bool:
    recent_texts = []
    for item in reversed(history[-window:]):
        if item.get("name") != name:
            continue
        text = normalize_text(item.get("text", ""))
        if text:
            recent_texts.append(text)
    return len(recent_texts) >= 2 and len(set(recent_texts[-2:])) == 1


def normalize_text(text: str) -> str:
    return " ".join(text.strip().lower().split())
