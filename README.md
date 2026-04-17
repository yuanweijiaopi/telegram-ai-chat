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

# 2. 复制示例配置
cp env/example.env .env

# 3. 启动 AI 机器人配置页
streamlit run ui.py

# 4. 启动 AI 群聊主进程（也可在配置页内启动）
python main.py

# 5. 启动抽奖管理后台（可选，端口 8502）
streamlit run lottery_ui.py --server.port 8502

# 6. 其他脚本在 scripts/ 目录下
python scripts/check_groups.py
```

详细步骤见 [安装与配置](docs/setup.md)。

部署配置位于 `infra/`，示例环境变量位于 `env/example.env`。

---

## 项目结构

```
├── main.py              # AI 群聊机器人根目录启动入口
├── ui.py                # AI 机器人 Web 根目录启动入口
├── lottery_ui.py        # 抽奖后台根目录启动入口
├── chat_app/            # AI 群聊机器人代码
│   ├── main.py
│   ├── behavior.py
│   ├── characters.py
│   ├── session_manager.py
│   └── ui/
├── lottery_app/         # 抽奖机器人代码
├── scripts/             # 命令行/部署脚本
├── shared/              # 共享路径/工具模块
├── infra/               # Docker / Compose / 部署配置
├── env/                 # 示例环境变量文件
├── data/                # 运行时数据库
├── logs/                # 运行日志
├── run/                 # PID 等运行时文件
└── docs/                # 详细文档
```

---

## 免责声明

请遵守 Telegram 使用条款、群规则和当地法律法规。账号风控、限流、封禁等风险需自行承担。
