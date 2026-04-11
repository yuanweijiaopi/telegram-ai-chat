# Telegram AI 群聊机器人

让多个 AI 角色以不同 Telegram 账号加入同一个群，自动接话、互相聊天、定时起话题，适合做群活跃、氛围测试和人设对话实验。

另附**抽奖机器人**模块：支持群内一键参与、管理员内定中奖人、自定义公告文案。

---

## 文档

| 文档 | 内容 |
|---|---|
| [安装与配置](docs/setup.md) | 环境要求、安装步骤、Telegram 登录、群组 ID 获取、服务器部署 |
| [AI 群聊机器人](docs/ai-chat-bot.md) | 工作原理、回复策略、自动话题、配置说明 |
| [抽奖机器人](docs/lottery-bot.md) | 抽奖 Bot 使用方法、内定功能、管理后台操作 |

---

## 快速上手

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 启动 AI 机器人配置页
streamlit run ui.py

# 3. 启动抽奖管理后台（可选，端口 8502）
streamlit run lottery_ui.py --server.port 8502
```

详细步骤见 [安装与配置](docs/setup.md)。

---

## 项目结构

```
├── main.py              # AI 群聊机器人主程序
├── ui.py                # AI 机器人 Web 配置界面
├── characters.py        # 角色配置
├── behavior.py          # 回复策略
├── session_manager.py   # Session 管理
├── lottery_bot.py       # 抽奖机器人
├── lottery_ui.py        # 抽奖管理后台
├── lottery_db.py        # 抽奖数据层（SQLite）
├── check_groups.py      # 命令行查看群组
└── docs/                # 详细文档
```

---

## 免责声明

请遵守 Telegram 使用条款、群规则和当地法律法规。账号风控、限流、封禁等风险需自行承担。
