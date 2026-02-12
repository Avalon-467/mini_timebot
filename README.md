# Mini TimeBot

一个基于 LLM 的智能定时任务助手。用户可以通过自然语言与 AI 对话，设置、查询和删除定时任务/闹钟，同时支持联网搜索和个人文件管理。

## 架构概览

项目由 4 个协作服务组成：

```
浏览器 (聊天 UI + 登录页)
    │  HTTP :51209
    ▼
front.py (Flask + Session)     ── 前端代理，渲染登录/聊天页面，管理会话凭证
    │  HTTP :51200
    ▼
mainagent.py (FastAPI + LangGraph)  ── 核心 AI Agent，集成 DeepSeek LLM + 对话记忆 + 密码认证
    │  stdio (MCP)
    ├── mcp_scheduler.py (FastMCP)  ── MCP 工具服务，暴露闹钟管理工具
    │       │  HTTP :51201
    │       ▼
    ├── time.py (FastAPI + APScheduler)  ── 定时调度中心，管理 cron 任务
    ├── mcp_search.py (FastMCP)    ── MCP 搜索服务，提供联网搜索（DuckDuckGo）
    └── mcp_filemanager.py (FastMCP) ── MCP 文件服务，提供用户文件管理
```

### 服务说明

| 服务 | 端口 | 说明 |
|------|------|------|
| `src/front.py` | 51209 | Flask Web UI，提供登录页 + 聊天界面，通过 Session 管理用户凭证 |
| `src/mainagent.py` | 51200 | 核心 AI Agent（LangGraph + DeepSeek），管理对话、工具调用与密码认证 |
| `src/mcp_scheduler.py` | - | MCP 工具服务（Agent 子进程），提供 add_alarm / list_alarms / delete_alarm |
| `src/mcp_search.py` | - | MCP 搜索服务（Agent 子进程），提供 web_search / web_news |
| `src/mcp_filemanager.py` | - | MCP 文件服务（Agent 子进程），提供 list_files / read_file / write_file / append_file / delete_file |
| `src/time.py` | 51201 | 定时任务调度中心（APScheduler），任务到期时回调 Agent |
| `test/chat.py` | - | 命令行测试客户端 |

> **端口可配置**：在 `config/.env` 中设置 `PORT_SCHEDULER`、`PORT_AGENT`、`PORT_FRONTEND` 即可自定义端口，参考 `config/.env.example`。

## 快速开始

### 一键运行（推荐）

**一站式脚本**，自动完成 环境配置 → API Key 配置 → 创建用户 → 启动服务，无需手动执行其他步骤：

```bash
# Linux / macOS（首次使用需赋予执行权限）
chmod +x run.sh
./run.sh

# Windows
run.bat
```

脚本会依次执行：
1. **环境配置** — 检查并安装 uv、创建虚拟环境、安装依赖（已完成则自动跳过）
2. **API Key 配置** — 检查并引导输入 DeepSeek API Key（已配置则自动跳过）
3. **用户管理** — 询问是否添加新用户（可跳过）
4. **启动服务** — 拉起全部服务并打开 Web UI

> 一切交给脚本处理，无需手动编辑任何配置文件。
> 以下章节为手动分步操作说明，使用 `run.sh` / `run.bat` 可跳过。

### 1. 环境配置

**一键配置（推荐）：**

自动检查并安装 uv、创建虚拟环境、安装所有依赖：

```bash
# Linux / macOS（首次使用需赋予执行权限）
chmod +x scripts/setup_env.sh
scripts/setup_env.sh

# Windows
scripts\setup_env.bat
```

**手动配置：**

如需手动操作，推荐使用 [uv](https://docs.astral.sh/uv/) 管理 Python 环境，比 pip 快 10-100 倍。

```bash
# 安装 uv
# Linux / macOS
curl -LsSf https://astral.sh/uv/install.sh | sh
# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# 创建虚拟环境（Python 3.11+）
uv venv .venv --python 3.11

# 激活虚拟环境
# Linux / macOS
source .venv/bin/activate
# Windows (PowerShell)
.venv\Scripts\Activate.ps1
# Windows (CMD)
.venv\Scripts\activate.bat

# 安装依赖
uv pip install -r config/requirements.txt
```

> 也可以用传统方式：`python -m venv .venv` + `pip install -r config/requirements.txt`

### 2. 配置环境变量

在 `config/` 目录下创建 `.env` 文件：

```
DEEPSEEK_API_KEY=your_deepseek_api_key_here
```

### 3. 创建用户账号

使用脚本创建用户（交互式输入用户名和密码）：

```bash
# Linux / macOS（首次使用需赋予执行权限）
chmod +x scripts/adduser.sh
scripts/adduser.sh

# Windows
scripts\adduser.bat
```

该工具会将用户名和密码的 SHA-256 哈希写入 `config/users.json`。可多次运行以添加多个用户。

配置文件格式参考 `config/users.json.example`：

```json
{
    "Xavier_01": "sha256哈希值（用 python tools/gen_password.py 生成）"
}
```

### 4. 启动服务

**一键启动（推荐）：**

```bash
# Linux / macOS（首次使用需赋予执行权限）
chmod +x scripts/start.sh
scripts/start.sh

# Windows
scripts\start.bat
```

Linux 按 `Ctrl+C` 停止所有服务；Windows 按任意键停止。

**手动分别启动**（需 3 个终端）：

```bash
# 终端 1：启动定时调度中心
python src/time.py

# 终端 2：启动 AI Agent（会自动拉起 MCP 子进程）
python src/mainagent.py

# 终端 3：启动前端 Web UI
python src/front.py
```

启动后访问 http://127.0.0.1:51209，输入用户名和密码登录后即可使用聊天界面。

也可以使用命令行客户端进行测试：

```bash
python test/chat.py
```

### 5. 公网部署（可选）

通过 Cloudflare Tunnel 将本地服务一键暴露到公网，无需域名、无需备案，适合临时分享或远程访问。

**集成在一键运行中：**

`run.sh` / `run.bat` 启动服务前会询问"是否部署到公网？"，选择 `y` 即自动完成。

**单独使用：**

```bash
# Linux / macOS
bash scripts/tunnel.sh

# Windows
scripts\tunnel.bat

# 或直接
python scripts/tunnel.py
```

脚本会自动：
1. 检测是否已安装 `cloudflared`（检查 `bin/` 目录和系统 PATH）
2. 未找到时自动下载到 `bin/` 目录（支持 Linux/macOS + amd64/arm64）
3. 启动 Cloudflare Tunnel，分配一个 `https://xxx.trycloudflare.com` 临时公网地址
4. 打印公网地址，按 `Ctrl+C` 关闭隧道

> 每次启动分配的公网地址不同（免费隧道特性）。`bin/` 目录已被 `.gitignore` 排除。

## 认证机制

系统采用**密码认证 + 双层会话管理**，防止用户伪造身份。

### 认证流程

```
用户输入用户名+密码
    │
    ▼
前端 → POST /proxy_login → Flask 代理
    │
    ▼
Flask → POST /login → FastAPI (mainagent.py)
    │  SHA-256(password) 与 config/users.json 中的哈希比对
    ▼
验证成功 → Flask Session 记录凭证 → 返回登录成功
    │
    ▼
每次聊天 → Flask /proxy_ask → 从 Session 取凭证 → FastAPI /ask (每次重新验证)
```

### 安全设计

| 特性 | 说明 |
|------|------|
| 密码存储 | 仅存储 SHA-256 哈希值，明文密码不落盘 |
| 传输安全 | 生产环境通过 Nginx 反向代理提供 HTTPS 加密 |
| 会话管理 | Flask 签名 Cookie，`secret_key` 随机生成，防篡改 |
| 前端状态 | 使用 `sessionStorage`，关闭标签页即失效 |
| 请求验证 | 每次 `/ask` 请求都重新验证密码，防止 Session 劫持后长期有效 |
| 用户隔离 | 对话记忆、文件存储均按 `user_id` 隔离 |

### 相关文件

| 文件 | 说明 |
|------|------|
| `config/users.json` | 用户名-密码哈希配置（不纳入版本控制） |
| `config/users.json.example` | 配置格式示例 |
| `tools/gen_password.py` | 交互式密码哈希生成工具 |

## 项目结构

```
mini_timebot/
├── LICENSE
├── README.md
├── run.sh                     # 一键运行 (Linux / macOS)
├── run.bat                    # 一键运行 (Windows)
├── scripts/                   # 脚本集中目录
│   ├── setup_env.sh           # 自动环境配置 (Linux / macOS)
│   ├── setup_env.bat          # 自动环境配置 (Windows)
│   ├── start.sh               # 一键启动 (Linux / macOS)
│   ├── start.bat              # 一键启动 (Windows)
│   ├── adduser.sh             # 添加用户 (Linux / macOS)
│   ├── adduser.bat            # 添加用户 (Windows)
│   ├── setup_apikey.sh        # API Key 配置 (Linux / macOS)
│   ├── setup_apikey.bat       # API Key 配置 (Windows)
│   ├── tunnel.py              # Cloudflare Tunnel 公网部署（自动下载 cloudflared + 启动隧道）
│   ├── tunnel.sh              # 公网部署 Shell 包装 (Linux / macOS)
│   ├── tunnel.bat             # 公网部署 Bat 包装 (Windows)
│   └── launcher.py            # 跨平台启动器（管理子进程生命周期）
├── packaging/                 # 打包发布相关
│   ├── launcher.py            # exe 启动器源码（调用 run.bat）
│   ├── build.py               # PyInstaller 打包脚本（Windows）
│   ├── build_dmg.sh           # macOS .app + DMG 打包脚本
│   ├── icon.png               # 应用图标源文件
│   └── installer.iss          # Inno Setup 安装包脚本（Windows）
├── config/
│   ├── .env               # 环境变量配置（需自行创建，不纳入版本控制）
│   ├── requirements.txt   # Python 依赖列表
│   ├── users.json         # 用户名-密码哈希（需用 gen_password.py 生成，不纳入版本控制）
│   └── users.json.example # 用户配置格式示例
├── data/
│   ├── agent_memory.db    # Agent 对话记忆数据库（运行时自动生成）
│   ├── timeset/
│   │   └── tasks.json     # 定时任务持久化存储（JSON，可手动编辑）
│   └── user_files/        # 用户文件存储目录（按用户名隔离，运行时自动生成）
│       └── <username>/    # 各用户的独立文件空间
├── src/
│   ├── front.py           # 前端 Web UI（登录页 + 聊天页 + Session 管理）
│   ├── mainagent.py       # 核心 AI Agent（含认证逻辑）
│   ├── mcp_scheduler.py   # MCP 工具服务（定时任务）
│   ├── mcp_search.py      # MCP 搜索服务（联网搜索）
│   ├── mcp_filemanager.py # MCP 文件服务（用户文件管理）
│   └── time.py            # 定时任务调度中心
├── tools/
│   └── gen_password.py    # 密码哈希生成工具
└── test/
    ├── chat.py            # 命令行测试客户端
    └── view_history.py    # 查看历史聊天记录
```

### 目录说明

**`config/`** — 配置文件目录

- `.env`：API 密钥配置，需手动创建：
  ```
  DEEPSEEK_API_KEY=your_deepseek_api_key_here
  ```
- `users.json`：用户认证配置，存储 `{用户名: SHA-256哈希}` 键值对，由 `tools/gen_password.py` 生成。

以上文件均已被 `.gitignore` 排除，不会提交到版本库。

**`data/`** — 运行时数据目录

- `agent_memory.db`：SQLite 数据库，由 LangGraph 的 `AsyncSqliteSaver` 自动创建，用于持久化对话历史。包含 `checkpoints` 和 `writes` 两张表，以 `thread_id`（用户 ID）区分不同用户的对话记录。
- `timeset/tasks.json`：定时任务持久化文件，JSON 格式，重启后自动恢复。可直接编辑修改任务配置。
- `user_files/`：用户文件存储目录，按用户名（`thread_id`）自动创建子目录，实现用户间文件隔离。

**文件管理机制**

Agent 通过 `mcp_filemanager.py` 提供文件管理能力，支持 5 个操作：

| 工具 | 说明 |
|------|------|
| `list_files` | 列出当前用户的所有文件 |
| `read_file` | 读取指定文件内容 |
| `write_file` | 创建或覆盖写入文件 |
| `append_file` | 向文件末尾追加内容 |
| `delete_file` | 删除指定文件 |

用户身份通过 `UserAwareToolNode` 自动注入：LLM 调用工具时不需要传递 `username` 参数，系统从 LangGraph 的 `config.thread_id` 中读取用户 ID 并自动填充，确保用户只能操作自己的文件且无法伪造身份。

**`tools/`** — 管理工具

| 脚本 | 说明 | 用法 |
|------|------|------|
| `gen_password.py` | 交互式创建用户，生成密码哈希并写入 `config/users.json` | `python tools/gen_password.py` |

**`test/`** — 测试与辅助工具

| 脚本 | 说明 | 用法 |
|------|------|------|
| `chat.py` | 命令行交互式聊天客户端，通过 HTTP 向 Agent 发送请求 | `python test/chat.py` |
| `view_history.py` | 读取 `agent_memory.db`，查看历史聊天记录 | `python test/view_history.py [--user USER_ID] [--limit N]` |

## 打包发布

### Windows 安装包

将项目打包为 Windows 安装包，用户双击桌面快捷方式即可运行（exe 本质是 `run.bat` 的启动器壳）。

**打包步骤：**

```bash
# 1. 安装 PyInstaller
pip install pyinstaller

# 2. 打包 exe（生成 MiniTimeBot.exe 到项目根目录）
python packaging/build.py

# 3. 制作安装包（可选）
#    用 Inno Setup 打开 packaging/installer.iss，点击编译
#    生成 dist/MiniTimeBot_Setup_1.0.0.exe
```

安装包功能：
- 创建桌面快捷方式和开始菜单项
- 包含完整源码、脚本和配置模板
- 安装后提示配置 API Key
- 支持卸载

> exe 仅作为 `run.bat` 的快捷方式入口，不改变任何业务逻辑。所有源码保持 `.py` 格式，可随时修改。

### macOS 应用包（.app + DMG）

将项目打包为标准的 macOS `.app` 应用包，并生成 `.dmg` 安装镜像。用户双击 `.app` 即可在终端中自动启动所有服务。

**打包步骤：**

```bash
# 一键打包（在项目根目录执行）
bash packaging/build_dmg.sh
```

脚本会自动完成以下流程：

1. **构建 `.app` 应用包** — 创建标准 macOS 应用结构（`Contents/MacOS/launch` 启动器 + `Contents/Resources/` 项目文件 + `Info.plist` 元数据）
2. **复制项目文件** — 将 `run.sh`、`scripts/`（仅 `.sh`）、`src/`、`tools/`、`config/` 模板等复制到 `Resources/`
3. **生成应用图标** — 从 `packaging/icon.png` 自动生成 `.icns` 图标（使用 `sips` + `iconutil`）
4. **创建 DMG 镜像** — 使用 `hdiutil` 生成带 Applications 快捷方式的 `.dmg` 安装镜像

**产出物：**

| 文件 | 路径 | 说明 |
|------|------|------|
| `.dmg` 安装镜像 | `dist/MiniTimeBot_1.0.0.dmg` | macOS 上打包时生成，可直接分发 |
| `.tar.gz` 压缩包 | `dist/MiniTimeBot_1.0.0_macos.tar.gz` | 非 macOS 系统上打包时生成（替代 DMG） |

**用户安装与使用：**

1. 双击 `.dmg` 文件挂载磁盘镜像
2. 将 `MiniTimeBot.app` 拖入「应用程序」文件夹
3. 首次打开时如遇"无法验证开发者"提示：
   - 右键点击 `.app` → 选择「打开」→ 确认「打开」
   - 或在终端执行：`xattr -cr /Applications/MiniTimeBot.app`
4. 之后双击图标即可启动，服务会在终端中运行
5. 启动后访问 http://127.0.0.1:51209 使用

**`.app` 内部结构：**

```
MiniTimeBot.app/
└── Contents/
    ├── Info.plist          ← 应用元数据（名称、版本、图标等）
    ├── MacOS/
    │   └── launch          ← 启动器脚本（通过 osascript 在 Terminal.app 中运行 run.sh）
    └── Resources/          ← 完整项目文件
        ├── run.sh
        ├── scripts/
        ├── src/
        ├── tools/
        ├── config/         ← 仅包含模板（.env.example, users.json.example, requirements.txt）
        └── data/           ← 空目录结构，运行时自动填充
```

**注意事项：**
- 打包脚本会自动检测运行平台：macOS 上生成 `.dmg`，其他系统生成 `.tar.gz`
- 如需自定义图标，替换 `packaging/icon.png`（建议正方形 PNG，至少 512×512）
- `.app` 本质是 `run.sh` 的包装，所有源码保持 `.py` 格式，可在 `Resources/` 中直接修改
- 首次启动时 `run.sh` 会自动引导用户完成环境配置、API Key 设置和用户创建

## 技术栈

- **LLM**: DeepSeek (`deepseek-chat`)
- **Agent 框架**: LangGraph + LangChain
- **工具协议**: MCP (Model Context Protocol)
- **后端**: FastAPI + Flask
- **认证**: SHA-256 密码哈希 + Flask 签名 Session
- **定时调度**: APScheduler
- **对话持久化**: SQLite (aiosqlite)
- **前端**: Tailwind CSS + Marked.js + Highlight.js

## 许可证

MIT License
