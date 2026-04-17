import json

from .form_state import normalize_base_url
from .telegram import ensure_character_ids

PROVIDER_MAP = {
    "Groq（免费）": ("https://api.groq.com/openai/v1", "llama-3.3-70b-versatile"),
    "Gemini（免费）": ("https://generativelanguage.googleapis.com/v1beta/openai/", "gemini-2.0-flash"),
    "DeepSeek": ("https://api.deepseek.com", "deepseek-chat"),
    "OpenAI": ("https://api.openai.com/v1", "gpt-4o-mini"),
    "Claude": ("https://api.anthropic.com/v1/", "claude-sonnet-4-6"),
    "自定义": ("", ""),
}

DEFAULT_TOPIC_DIRECTIONS = [
    "工作、加班、老板、同事",
    "吃饭、外卖、今天吃什么",
    "钱、消费、买了什么",
    "手机、App、刷到的内容",
    "睡眠、作息、熬夜",
    "交通、堵车、出行",
    "游戏、娱乐、追剧",
    "朋友、聚会、社交",
    "天气、季节、身体状态",
    "随便一件今天发生的小事",
]


def resolve_initial_provider(saved_ai_url: str, saved_ai_model: str) -> str:
    initial_provider = "自定义"
    for label, (candidate_url, candidate_model) in PROVIDER_MAP.items():
        if label == "自定义":
            continue
        if (
            normalize_base_url(saved_ai_url) == normalize_base_url(candidate_url)
            and saved_ai_model == candidate_model
        ):
            initial_provider = label
            break
    return initial_provider


def load_saved_characters(env: dict) -> list[dict]:
    chars_json = env.get("CHARACTERS_JSON", "")
    try:
        saved_chars = json.loads(chars_json) if chars_json else []
    except Exception:
        saved_chars = []

    if not saved_chars:
        saved_chars = [
            {
                "id": "小明",
                "name": "小明",
                "phone": env.get("CHARACTER_XIAOMING_PHONE", ""),
                "system": env.get("CHARACTER_XIAOMING_SYSTEM", "25岁打工人，嘴欠爱吐槽，说话简短口语化。"),
            },
            {
                "id": "老王",
                "name": "老王",
                "phone": env.get("CHARACTER_LAOWANG_PHONE", ""),
                "system": env.get("CHARACTER_LAOWANG_SYSTEM", "28岁老油条，冷静毒舌，一句话戳心窝。"),
            },
        ]

    return ensure_character_ids(saved_chars)
