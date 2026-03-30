# Telegram AI 群聊机器人

多个 AI 角色在 Telegram 群里自动互相聊天，让群组保持活跃。

---

## 环境要求

- Python 3.10+
- 每个角色需要一个独立的 Telegram 账号
- 一个免费或付费的 AI API Key（支持 Groq、Gemini、DeepSeek、OpenAI、Claude）

---

## 快速开始

**1. 克隆项目**

```bash
git clone https://github.com/yuanweijiaopi/telegram-ai-chat.git
cd telegram-ai-chat
```

**2. 安装依赖**

```bash
pip install -r requirements.txt
```

**3. 启动配置界面**

```bash
streamlit run ui.py
```

浏览器会自动打开配置页面，在界面里填写所有信息，点击保存并启动即可。

---

## 需要准备什么

### Telegram API ID 和 API Hash

1. 打开 https://my.telegram.org，用手机号登录
2. 点击 **API development tools**
3. 填写表单（App title 和 Short name 随便填，Platform 选 Other）
4. 点击 **Create application**，记录 `App api_id` 和 `App api_hash`

> 所有角色共用同一组 api_id / api_hash。

### 群组 ID

1. 在 Telegram 搜索并添加 [@userinfobot](https://t.me/userinfobot)
2. 转发目标群的任意一条消息给它
3. 它会返回群组 ID（负数，如 `-1002278401337`）

### AI API Key（免费推荐）

| 服务 | 免费额度 | 获取地址 |
|------|---------|---------|
| Groq | 每天大量免费请求 | https://console.groq.com |
| Gemini | 每天 1500 次 | https://aistudio.google.com/apikey |
| DeepSeek | 注册送额度 | https://platform.deepseek.com |

### 角色手机号

每个 AI 角色需要一个独立的 Telegram 账号手机号，首次启动时会发送验证码到对应账号。

---

## 配置界面说明

启动 `streamlit run ui.py` 后，按以下顺序填写：

1. **Telegram 配置** — API ID、API Hash、群组 ID
2. **AI 配置** — 选择服务商，填入 API Key
3. **代理配置** — 国内需要填写 Clash 等代理端口（一般是 127.0.0.1:50656）
4. **角色配置** — 两个角色的手机号和性格描述
5. 点击 **保存配置**，再点击 **启动机器人**

首次启动需要在终端输入每个账号的验证码，之后会保存登录状态无需重复操作。

---

## 注意事项

- `.env` 和 `sessions/` 已在 `.gitignore` 中排除，不会上传到 GitHub
- API Key、手机号等敏感信息请勿泄露
- 国内使用需要代理才能连接 Telegram
