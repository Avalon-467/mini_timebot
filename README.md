# Mini TimeBot

一个基于 LLM 的智能定时任务助手。用户可以通过自然语言与 AI 对话，设置、查询和删除定时任务/闹钟，同时支持联网搜索和个人文件管理。

## 架构概览

项目由 4 个协作服务组成：

```
浏览器 (聊天 UI + 登录页)
    │  HTTP :9000
    ▼
front.py (Flask + Session)     ── 前端代理，渲染登录/聊天页面，管理会话凭证
    │  HTTP :8000
    ▼
mainagent.py (FastAPI + LangGraph)  ── 核心 AI Agent，集成 DeepSeek LLM + 对话记忆 + 密码认证
    │  stdio (MCP)
    ├── mcp_scheduler.py (FastMCP)  ── MCP 工具服务，暴露闹钟管理工具
    │       │  HTTP :8001
    │       ▼
    ├── time.py (FastAPI + APScheduler)  ── 定时调度中心，管理 cron 任务
    ├── mcp_search.py (FastMCP)    ── MCP 搜索服务，提供联网搜索（DuckDuckGo）
    └── mcp_filemanager.py (FastMCP) ── MCP 文件服务，提供用户文件管理
```

### 服务说明

| 服务 | 端口 | 说明 |
|------|------|------|
| `src/front.py` | 9000 | Flask Web UI，提供登录页 + 聊天界面，通过 Session 管理用户凭证 |
| `src/mainagent.py` | 8000 | 核心 AI Agent（LangGraph + DeepSeek），管理对话、工具调用与密码认证 |
| `src/mcp_scheduler.py` | - | MCP 工具服务（Agent 子进程），提供 add_alarm / list_alarms / delete_alarm |
| `src/mcp_search.py` | - | MCP 搜索服务（Agent 子进程），提供 web_search / web_news |
| `src/mcp_filemanager.py` | - | MCP 文件服务（Agent 子进程），提供 list_files / read_file / write_file / append_file / delete_file |
| `src/time.py` | 8001 | 定时任务调度中心（APScheduler），任务到期时回调 Agent |
| `test/chat.py` | - | 命令行测试客户端 |

## 快速开始

### 1. 环境配置（推荐使用 uv）

推荐使用 [uv](https://docs.astral.sh/uv/) 管理 Python 环境，比 pip 快 10-100 倍。

**安装 uv：**

```bash
# Linux / macOS
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

安装后重启终端，确认 `uv --version` 可用。

**创建虚拟环境并安装依赖：**

```bash
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
uv pip install -r requirements.txt
```

> 也可以用传统方式：`python -m venv .venv` + `pip install -r requirements.txt`

### 2. 配置环境变量

在 `config/` 目录下创建 `.env` 文件：

```
DEEPSEEK_API_KEY=your_deepseek_api_key_here
```

### 3. 创建用户账号

使用脚本创建用户（交互式输入用户名和密码）：

```bash
# Linux / macOS（首次使用需赋予执行权限）
chmod +x adduser.sh
./adduser.sh

# Windows
adduser.bat
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
chmod +x start.sh
./start.sh

# Windows
start.bat
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

启动后访问 http://127.0.0.1:9000，输入用户名和密码登录后即可使用聊天界面。

也可以使用命令行客户端进行测试：

```bash
python test/chat.py
```

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
├── requirements.txt
├── start.sh               # 一键启动脚本 (Linux / macOS)
├── start.bat              # 一键启动脚本 (Windows)
├── adduser.sh             # 添加用户脚本 (Linux / macOS)
├── adduser.bat            # 添加用户脚本 (Windows)
├── config/
│   ├── .env               # 环境变量配置（需自行创建，不纳入版本控制）
│   ├── users.json         # 用户名-密码哈希（需用 gen_password.py 生成，不纳入版本控制）
│   └── users.json.example # 用户配置格式示例
├── data/
│   ├── agent_memory.db    # Agent 对话记忆数据库（运行时自动生成）
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
