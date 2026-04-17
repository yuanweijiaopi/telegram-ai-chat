# 安装与配置

## 环境要求

- Python 3.10+
- macOS / Linux / Windows 均可
- 每个 AI 角色需要一个独立的 Telegram 账号
- 一个可用的 AI API Key

支持的 AI 服务：Groq、Gemini、DeepSeek、OpenAI、Claude、自定义 OpenAI 兼容接口

---

## 安装

```bash
git clone https://github.com/yuanweijiaopi/telegram-ai-chat.git
cd telegram-ai-chat

python3 -m venv .venv

# macOS / Linux
source .venv/bin/activate
# Windows PowerShell
.venv\Scripts\Activate.ps1

pip install -r requirements.txt

# 初始化本地配置
cp env/example.env .env
```

---

## 你需要提前准备的内容

### Telegram API ID 和 API Hash

1. 打开 [my.telegram.org](https://my.telegram.org) 并登录
2. 点击 `API development tools`
3. 创建应用，记录 `api_id` 和 `api_hash`

> 所有角色可以共用同一组 `api_id` / `api_hash`，这不是 BotFather 的 Bot Token。

### AI API Key

| 服务 | 获取地址 |
|------|----------|
| Groq | console.groq.com |
| Gemini | aistudio.google.com/apikey |
| DeepSeek | platform.deepseek.com |
| OpenAI | platform.openai.com |

### 代理（可选）

如果所在网络无法直接连接 Telegram，需要本地 SOCKS5 代理（如 Clash / Surge）。

---

## 启动配置页面

```bash
streamlit run ui.py
# 或
python -m streamlit run ui.py
```

> `ui.py` 是保留在根目录的启动入口，页面实现代码位于 `chat_app/ui/`。

---

## 启动机器人主进程

```bash
python main.py
```

> `main.py` 是保留在根目录的启动入口，实际逻辑位于 `chat_app/main.py`。如果你习惯在配置页面里点「启动机器人」，也可以不手动执行这条命令。

---

## 配置步骤

1. **填写 Telegram 配置**：API ID、API Hash、群组 ID
2. **选择 AI 服务**：选服务商，填入 API Key
3. **代理配置**：如需代理勾选并填入地址和端口
4. **配置角色**：填写每个角色的名字、手机号、性格描述
5. **回复行为**：调整延迟、冷却时间、话题间隔等
6. **账号登录**：逐个角色发验证码 → 输入验证码 → 完成登录
7. **选择群组**：点击「读取群组列表」→ 找到目标群 → 点「使用」
8. **保存配置**：点「💾 保存配置」
9. **启动机器人**：点页面里的「▶ 启动机器人」，或手动执行 `python main.py`

---

## 获取群组 ID

**方法一（推荐）**：在 Web 页面点击「读取群组列表」，找到目标群后点「使用」自动填入。

**方法二**：将群内任意消息转发给 [@userinfobot](https://t.me/userinfobot)，它会回复群 ID（通常是负数，如 `-1002278401337`）。

**方法三**：命令行查看
```bash
./.venv/bin/python scripts/check_groups.py
```

---

## 部署到服务器

部署配置文件位于 `infra/` 目录。

创建 `infra/.deploy.env`：
```bash
export DEPLOY_REMOTE_HOST=user@your-server-ip
export DEPLOY_REMOTE_DIR=/home/user/telegram-ai-chat
```

执行部署：
```bash
source infra/.deploy.env && python scripts/deploy.py
```

> 远程服务器需预装 Docker 和 Docker Compose，首次部署前需在服务器上手动创建 `.env` 和 `sessions/` 目录；`data/`、`logs/`、`run/` 会在运行时自动创建。

---

## 常见问题

**Telegram 连不上**：检查代理是否可用，确认 SOCKS5 类型和端口正确。

**已登录还是提示未登录**：Session 文件可能丢失或 Telegram 要求重新验证，回到页面重新登录即可。

**启动没有反应**：检查是否有角色未登录、API Key 是否填写、群组 ID 是否正确，查看日志排查。

**群组列表读不到目标群**：确认该登录账号在 Telegram 客户端里能看到目标群。
