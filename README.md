# Mini TimeBot

一个基于 LLM 的智能定时任务助手。用户可以通过自然语言与 AI 对话，设置、查询和删除定时任务/闹钟。

## 架构概览

项目由 4 个协作服务组成：

```
浏览器 (聊天 UI)
    │  HTTP :9000
    ▼
front.py (Flask)           ── 前端代理，渲染聊天页面并转发请求
    │  HTTP :8000
    ▼
mainagent.py (FastAPI + LangGraph)  ── 核心 AI Agent，集成 DeepSeek LLM + 对话记忆
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
| `src/front.py` | 9000 | Flask Web UI，提供聊天界面并代理请求到 Agent |
| `src/mainagent.py` | 8000 | 核心 AI Agent（LangGraph + DeepSeek），管理对话与工具调用 |
| `src/mcp_scheduler.py` | - | MCP 工具服务（作为 Agent 子进程启动），提供 add_alarm / list_alarms / delete_alarm |
| `src/mcp_search.py` | - | MCP 搜索服务（作为 Agent 子进程启动），提供 web_search / web_news |
| `src/mcp_filemanager.py` | - | MCP 文件服务（作为 Agent 子进程启动），提供 list_files / read_file / write_file / append_file / delete_file |
| `src/time.py` | 8001 | 定时任务调度中心（APScheduler），任务到期时回调 Agent |
| `test/chat.py` | - | 命令行测试客户端 |

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

在 `config/` 目录下创建 `.env` 文件：

```
DEEPSEEK_API_KEY=your_deepseek_api_key_here
```

### 3. 启动服务

**一键启动（推荐）：**

```bash
./start.sh
```

按 `Ctrl+C` 即可停止所有服务。

**手动分别启动**（需 3 个终端）：

```bash
# 终端 1：启动定时调度中心
python src/time.py

# 终端 2：启动 AI Agent（会自动拉起 mcp_scheduler.py 子进程）
python src/mainagent.py

# 终端 3：启动前端 Web UI
python src/front.py
```

启动后访问 http://127.0.0.1:9000 即可使用聊天界面。

也可以使用命令行客户端进行测试：

```bash
python test/chat.py
```

## 项目结构

```
mini_timebot/
├── LICENSE
├── README.md
├── requirements.txt
├── start.sh               # 一键启动脚本
├── config/
│   └── .env               # 环境变量配置（需自行创建，不纳入版本控制）
├── data/
│   ├── agent_memory.db    # Agent 对话记忆数据库（运行时自动生成）
│   └── user_files/        # 用户文件存储目录（按用户名隔离，运行时自动生成）
│       └── <username>/    # 各用户的独立文件空间
├── src/
│   ├── front.py           # 前端 Web UI
│   ├── mainagent.py       # 核心 AI Agent
│   ├── mcp_scheduler.py   # MCP 工具服务（定时任务）
│   ├── mcp_search.py      # MCP 搜索服务（联网搜索）
│   ├── mcp_filemanager.py # MCP 文件服务（用户文件管理）
│   └── time.py            # 定时任务调度中心
└── test/
    ├── chat.py            # 命令行测试客户端
    └── view_history.py    # 查看历史聊天记录
```

### 目录说明

**`config/`** — 配置文件目录

需手动创建 `.env` 文件，内容如下：

```
DEEPSEEK_API_KEY=your_deepseek_api_key_here
```

该文件包含 API 密钥，已被 `.gitignore` 排除，不会提交到版本库。

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
- **定时调度**: APScheduler
- **对话持久化**: SQLite (aiosqlite)
- **前端**: Tailwind CSS + Marked.js + Highlight.js

## 许可证

MIT License
