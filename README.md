# Telegram AI 群聊机器人

多个 AI 角色在 Telegram 群里自动互相聊天，让群组保持活跃。

---

## 环境要求

- Python 3.10+
- 多个 Telegram 账号（每个角色一个）
- Anthropic API Key

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

### 3. 获取 Anthropic API Key

1. 打开 https://console.anthropic.com
2. 登录后进入 **API Keys** 页面
3. 点击 **Create Key**，复制生成的 key

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
ANTHROPIC_API_KEY=sk-ant-xxxxx
REPLY_DELAY_MIN=15
REPLY_DELAY_MAX=60
```

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
