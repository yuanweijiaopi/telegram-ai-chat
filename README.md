# Telegram AI 群聊机器人

让多个 AI 角色以不同 Telegram 账号加入同一个群，自动接话、互相聊天、定时起话题，适合做群活跃、氛围测试和人设对话实验。

当前项目自带一个 Web 配置页，支持：

- 配置 Telegram / AI / 代理参数
- 配置多个角色的人设和手机号
- 在网页内完成 Telegram 登录
- 在网页内读取可见群组并一键填入群 ID
- 启动、停止机器人并查看日志

## 项目结构

- [ui.py](REDACTED_LOCAL_PATHui.py)
  Web 配置页面，基于 Streamlit
- [main.py](REDACTED_LOCAL_PATHmain.py)
  机器人主程序，负责登录、监听消息、调用 AI 回复
- [characters.py](REDACTED_LOCAL_PATHcharacters.py)
  角色配置读取与默认角色定义
- [behavior.py](REDACTED_LOCAL_PATHbehavior.py)
  回复策略、重复检测、上下文拼装
- [check_groups.py](REDACTED_LOCAL_PATHcheck_groups.py)
  命令行查看已登录账号可见群组

## 环境要求

- Python 3.10+
- macOS / Linux / Windows 均可
- 每个角色需要一个独立的 Telegram 账号
- 一个可用的 AI API Key

已支持的 AI 服务：

- Groq
- Gemini
- DeepSeek
- OpenAI
- Claude
- 自定义兼容 OpenAI 格式的接口

## 安装

1. 克隆项目

```bash
git clone https://github.com/yuanweijiaopi/telegram-ai-chat.git
cd telegram-ai-chat
```

2. 创建虚拟环境

```bash
python3 -m venv .venv
```

3. 激活虚拟环境

macOS / Linux:

```bash
source .venv/bin/activate
```

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

4. 安装依赖

```bash
pip install -r requirements.txt
```

5. 启动 Web 配置页

```bash
streamlit run ui.py
```

如果系统里找不到 `streamlit` 命令，请改用：

```bash
python -m streamlit run ui.py
```

如果你想强制使用项目当前虚拟环境，可直接运行：

```bash
./.venv/bin/python -m streamlit run ui.py
```

打开页面后，后续大多数操作都可以在 Web 界面完成。

## 你需要提前准备的内容

### 1. Telegram API ID 和 API Hash

获取方法：

1. 打开 [my.telegram.org](https://my.telegram.org)
2. 使用你的手机号登录
3. 点击 `API development tools`
4. 创建一个应用
5. 记录得到的 `api_id` 和 `api_hash`

说明：

- 所有角色可以共用同一组 `api_id` / `api_hash`
- 这是 Telegram 客户端登录所必需的，不是 BotFather 的 bot token

### 2. AI API Key

常见获取地址：

- Groq: [console.groq.com](https://console.groq.com)
- Gemini: [aistudio.google.com/apikey](https://aistudio.google.com/apikey)
- DeepSeek: [platform.deepseek.com](https://platform.deepseek.com)
- OpenAI: [platform.openai.com](https://platform.openai.com)

### 3. Telegram 账号手机号

每个角色都需要绑定一个真实 Telegram 账号手机号。

建议：

- 一个角色对应一个账号
- 首次登录时确保该手机号能收到 Telegram 验证码
- 如果账号开启了二步验证，还需要准备二步验证密码

### 4. 代理

如果你所在网络环境无法直接连接 Telegram，需要准备本地代理。

常见写法：

- 地址：`127.0.0.1`
- 端口：你的 Clash / Surge / v2rayN / Shadowrocket 实际监听端口

项目当前使用的是 SOCKS5 方式连接 Telegram。

## 快速开始

### 第一步：打开 Web 页面

```bash
streamlit run ui.py
```

如果提示 `command not found: streamlit`，请改用：

```bash
python -m streamlit run ui.py
```

### 第二步：填写 Telegram 配置

在页面的 `1. Telegram 配置` 中填写：

- `API ID`
- `API Hash`
- `群组 ID`

如果你暂时还不知道群组 ID，可以先留空，后面通过网页读取群组列表来选。

### 第三步：选择 AI 服务

在 `2. AI 配置` 中：

- 选择服务商
- 填入 API Key
- 如果选的是 `自定义`，还需要手动填 `Base URL` 和模型名

提示：

- 页面会尽量按当前 `.env` 自动回显已使用的 AI 服务
- 保存配置不会再把你原来的 AI 服务偷偷切回默认值

### 第四步：填写代理

在 `3. 代理配置` 中：

- 如果需要代理，勾选 `使用代理`
- 填入代理地址和端口

如果不需要代理，可以不勾选。

### 第五步：配置角色

在 `4. 角色配置` 中，你可以：

- 修改角色名
- 填入手机号
- 编辑角色性格描述
- 添加新角色
- 删除角色

说明：

- 角色名只是本项目内的显示名
- 真正 Telegram 登录的是角色绑定的手机号对应账号
- 每个角色都有稳定的内部 ID，用来绑定 session，不会因为改显示名就丢登录状态

### 第六步：配置回复行为和自动话题

在 `5. 回复行为` 和 `6. 自动发话题` 中可调整：

- 是否每条都回复
- 回复延迟
- 回复真人冷却时间
- AI 互聊冷却时间
- 自动起话题间隔
- 启动后多久发第一条话题
- 话题方向范围

### 第七步：在网页内完成 Telegram 登录

在 `7. 账号登录` 中，每个角色都有独立登录区。

推荐顺序：

1. 点击 `检查登录状态`
2. 如果未登录，点击 `发送验证码`
3. 输入收到的 Telegram 验证码
4. 如果账号开启了二步验证，再输入二步验证密码
5. 点击 `完成登录`

登录成功后，页面会显示该账号的 Telegram 昵称。

说明：

- 登录信息会保存到 `sessions/` 目录
- 一般首次登录完成后，后续不需要重复输入验证码
- 如果 Telegram 判定需要重新验证，仍可以在网页内重新登录

### 第八步：读取群组并选择目标群

在 `快速查看已登录群组 ID` 区块中：

1. 点击 `读取群组列表`
2. 页面会读取所有已登录账号能看到的群组
3. 找到目标群后点击 `使用`

点击 `使用` 后：

- 群 ID 会自动填入输入框
- 配置会同步保存到 `.env`

### 第九步：保存并启动

点击：

- `💾 保存配置`
- `▶ 启动机器人`

启动前页面会自动检查：

- 所有角色是否已经登录

如果还有角色未登录，页面会阻止启动并提示先完成登录。

## 群组 ID 获取方式

### 方法一：Web 页面直接读取

这是当前最推荐的方式。

前提：

- 至少一个角色已经登录成功
- 该账号能在 Telegram 中看到目标群

然后在页面中：

1. 点 `读取群组列表`
2. 找到目标群
3. 点 `使用`

### 方法二：用 @userinfobot

1. 在 Telegram 搜索 [@userinfobot](https://t.me/userinfobot)
2. 把目标群的任意一条消息转发给它
3. 它会回复群 ID，通常是负数，如 `-1002278401337`

### 方法三：命令行查看

```bash
./.venv/bin/python check_groups.py
```

会打印所有已登录账号可见的群组列表。

## 如何运行机器人

### 方式一：在 Web 页面启动

推荐方式，最方便：

- 登录完成后点击 `▶ 启动机器人`

### 方式二：命令行直接启动

```bash
./.venv/bin/python -u main.py
```

适合：

- 调试登录过程
- 直接看终端输出
- 处理验证码、二步验证等细节

### 方式三：部署到服务器

项目自带 `deploy.py` / `deploy.sh`，可一键同步代码到远程服务器并重启 Docker 容器。

1. 创建 `.deploy.env` 文件（已在 `.gitignore` 中，不会提交）：

```bash
# .deploy.env
export DEPLOY_REMOTE_HOST=user@your-server-ip
export DEPLOY_REMOTE_DIR=/home/user/telegram-ai-chat
```

2. 执行部署：

```bash
source .deploy.env && python deploy.py
```

或使用 Shell 版本：

```bash
source .deploy.env && bash deploy.sh
```

说明：

- 部署会通过 `rsync` 同步代码，自动排除 `.env`、`sessions/`、日志等敏感文件
- 远程服务器需要预先安装 Docker 和 Docker Compose
- 首次部署前需要先在服务器上手动创建 `.env` 和 `sessions/` 目录

## 日志

机器人运行日志默认写入：

- [chat.log](REDACTED_LOCAL_PATHchat.log)

在 Web 页面里也可以直接勾选 `查看运行日志`。

## Session 与配置文件

### `.env`

保存页面中的主要配置，例如：

- Telegram API 参数
- AI 服务参数
- 代理配置
- 角色列表
- 回复策略配置

### `sessions/`

保存各个 Telegram 账号的登录 session。

说明：

- 这里面是敏感文件，不要上传到公开仓库
- 删除某个角色对应的 session 文件后，下次需要重新登录

## 常见问题

### 1. 启动时报 Telegram 连不上

通常是代理问题。

排查顺序：

1. 检查代理是否真的可用
2. 检查页面里的代理地址和端口是否正确
3. 确认代理类型是否支持 SOCKS5
4. 确认本机能正常访问 Telegram

### 2. 已经登录过，还是提示未登录

可能原因：

- 这个角色的 session 文件被删了
- 换了角色配置或手机号
- Telegram 要求重新验证

解决：

- 回到 Web 页面，在 `7. 账号登录` 里重新执行登录

### 3. 点击启动没有反应

先检查：

- 是否有角色未登录
- `AI API Key` 是否填写
- `群组 ID` 是否正确
- 日志里是否有报错

### 4. 群组列表读不到目标群

常见原因：

- 当前登录账号根本不在那个群里
- 账号不具备查看该群会话的权限
- session 还没登录成功

解决：

- 换另一个已登录角色账号试试
- 确认该账号在 Telegram 客户端里能看到目标群

### 5. 多行角色设定会不会把配置写坏

不会。

当前版本保存 `.env` 时已经做了安全编码，多行角色设定可以正常保存。

## 安全提示

- `.env`、`sessions/` 都包含敏感信息
- 不要把 API Key、手机号、session 文件发给别人
- 不要把仓库直接公开并连同 `.env` 一起提交
- Telegram 验证码和二步验证密码都属于敏感信息

## 推荐使用流程

第一次使用时，建议严格按下面顺序：

1. 创建虚拟环境并安装依赖
2. 启动 `streamlit run ui.py`
3. 填写 Telegram / AI / 代理参数
4. 填角色手机号和人设
5. 在网页里完成每个角色登录
6. 读取群组列表并选中目标群
7. 保存配置
8. 启动机器人
9. 打开日志观察运行情况

## 免责声明

请自行遵守 Telegram 的使用条款、群规则和当地法律法规。

账号风控、限流、封禁等风险需要自行承担。这个项目更适合测试、实验和小规模使用，不建议直接用于高风险或高曝光场景。
