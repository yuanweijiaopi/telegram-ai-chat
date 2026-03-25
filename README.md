# Telegram AI 群聊机器人

多个 AI 角色在 Telegram 群里自动互相聊天，让群组保持活跃。

---

## 环境要求

- Python 3.10+
- 多个 Telegram 账号（每个角色一个）
- 一个兼容 OpenAI Chat Completions 的模型服务

---

## 安装依赖

```bash
pip install -r requirements.txt
```

---

## 配置步骤

### 1. 获取 Telegram API ID 和 API Hash

1. 打开 https://my.telegram.org，用手机号登录（会发验证码到 Telegram）
2. 点击 **API development tools**
3. 填写表单创建应用：
   - **App title**：随便填，如 `MyApp`
   - **Short name**：随便填，如 `myapp`
   - **Platform**：选 `Other`
   - **Description**：可以不填
4. 点击 **Create application**
5. 记录页面上的 `App api_id` 和 `App api_hash`

> 注意：每个 Telegram 账号只需要一组 api_id / api_hash，所有角色共用。

---

### 2. 获取群组 ID

1. 在 Telegram 中搜索并添加 [@userinfobot](https://t.me/userinfobot)
2. 转发目标群的任意一条消息给它
3. 它会返回该群的 ID（负数，如 `-1001234567890`）

---

### 3. 获取 AI API Key

你可以选任意一个当前 `.env.example` 里支持的提供商，比如 Gemini、Groq、Claude 或 OpenAI。

---

### 4. 填写配置文件

```bash
cp .env.example .env
```

编辑 `.env`：

```
TELEGRAM_API_ID=你的api_id
TELEGRAM_API_HASH=你的api_hash
TELEGRAM_GROUP_ID=-1001234567890
AI_API_KEY=你的key
AI_BASE_URL=对应服务的 OpenAI 兼容地址
AI_MODEL=对应模型名
REPLY_DELAY_MIN=15
REPLY_DELAY_MAX=60
MIN_SECONDS_BETWEEN_REPLIES=45
MENTION_REPLY_BONUS=0.25
MAX_CONTEXT=12
MAX_HISTORY=80
```

如果你本地使用 Clash X 之类的代理，也可以额外配置：

```
PROXY_HOST=127.0.0.1
PROXY_PORT=50656
```

如果不填这两个值，程序会默认直连 Telegram。

---

### 5. 配置角色

编辑 `characters.py`，为每个角色填入对应的手机号：

```python
{
    "name": "小明",
    "phone": "+8613800000001",  # 该角色登录的手机号
    ...
}
```

---

## 运行

```bash
python main.py
```

首次运行时，每个账号会依次要求输入 Telegram 验证码：

```
请输入 +8613800000001 的验证码: 12345
✓ 小明 登录成功
...
所有角色已就绪，监听群中...
```

登录后会在 `sessions/` 目录保存会话文件，之后运行无需重复登录。

---

## 行为策略

当前项目已经接入了 4 层行为策略，核心配置在 `characters.py` 和 `.env`：

- `GLOBAL_RULES`：全局语气、边界和输出约束
- `CHARACTERS[*].system`：角色人设
- `BEHAVIOR_POLICY`：上下文长度、历史长度、连续 AI 轮次、冷却时间等运行策略
- `.env` 调参项：`MIN_SECONDS_BETWEEN_REPLIES`、`MIN_SECONDS_BETWEEN_REPLIES_HUMAN`、`MIN_SECONDS_BETWEEN_REPLIES_CHARACTER`、`MENTION_REPLY_BONUS`、`MAX_CONTEXT`、`MAX_HISTORY`
- 场景调参项：`QUIET_WINDOW_SECONDS`、`RECENT_REPLY_WINDOW_SECONDS`、`STALE_PENDING_REPLY_SECONDS`、`SAME_SENDER_STREAK_LIMIT`

现在回复链路会自动处理这些问题：

- 合并全局规则和角色规则生成 prompt
- 限制连续 AI 接龙，避免机器人自己聊嗨
- 控制单个角色回复冷却，减少刷屏感
- 区分普通消息、`@提及`、其他机器人消息，按角色单独设置回复概率
- 群冷场更容易接话，刚有人接过则自动抑制跟风回复
- 延迟等待期间如果群里已经有人接上，原计划回复会自动取消
- 去重最近消息，避免同一条内容被多账号重复记入历史
- 发起新话题时沿用同一套行为约束，而不是单独裸调模型
- 把策略命中结果写入 `strategy.log`，方便复盘为什么这次回了或没回

推荐你后面主要调这几类参数：

1. 在 `CHARACTERS[*].reply_probs` 里控制不同消息类型下的活跃度
2. 在 `CHARACTERS[*].scene_reply_bonus` 里控制冷场接话、跟风抑制、连续单人发言时的介入力度
3. 在 `CHARACTERS[*].extra_rules`、`relationship_style`、`taboo_topics` 里细化角色边界
4. 观察 `strategy.log` 里的 `reply_skip`、`reply_cancelled`、`reply_sent`、`topic_sent` 事件，再决定是否继续调冷却和场景阈值

---

## 后台运行（可选）

```bash
# 启动
nohup python main.py > chat.log 2>&1 &

# 查看日志
tail -f chat.log

# 停止
kill $(pgrep -f main.py)
```

---

## 注意事项

- `api_id`、`api_hash`、API Key 属于私密凭证，不要泄露或上传到 GitHub
- `.env` 和 `sessions/` 已在 `.gitignore` 中排除
- 每个角色需要独立的 Telegram 账号和手机号
