import os
import copy
import asyncio
from typing import Annotated, TypedDict, Optional

# LangGraph related
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

# Model related
from langchain_deepseek import ChatDeepSeek
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.prebuilt import ToolNode, tools_condition


# --- Tools that need automatic username injection ---
USER_INJECTED_TOOLS = {
    # File management tools
    "list_files", "read_file", "write_file", "append_file", "delete_file",
    # Command execution tools
    "run_command", "run_python_code",
    # Alarm management tools
    "add_alarm", "list_alarms", "delete_alarm",
    # Bark push notification tools
    "set_push_key", "send_push_notification", "get_push_status",
    "set_public_url", "get_public_url", "clear_public_url",
}


# --- State definition ---
class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    trigger_source: str
    enabled_tools: Optional[list[str]]
    user_id: Optional[str]
    session_id: Optional[str]


class UserAwareToolNode:
    """
    Custom tool node:
    1. Reads thread_id from RunnableConfig, auto-injects as username for file/command tools
    2. Intercepts calls to disabled tools at runtime, returns error ToolMessage
    """
    def __init__(self, tools, get_mcp_tools_fn):
        self.tool_node = ToolNode(tools)
        self._get_mcp_tools = get_mcp_tools_fn

    async def __call__(self, state, config: RunnableConfig):
        # Get user_id directly from state (injected by mainagent) instead of
        # parsing thread_id, because user_id itself may contain the separator.
        user_id = state.get("user_id") or "anonymous"

        last_message = state["messages"][-1]
        if not hasattr(last_message, "tool_calls") or not last_message.tool_calls:
            return {"messages": []}

        # Get currently enabled tool set
        enabled_names = state.get("enabled_tools")
        if enabled_names is not None:
            enabled_set = set(enabled_names)
        else:
            enabled_set = None  # None = all allowed

        # Separate blocked and allowed calls
        modified_message = copy.deepcopy(last_message)
        blocked_calls = []
        allowed_calls = []
        for tc in modified_message.tool_calls:
            if enabled_set is not None and tc["name"] not in enabled_set:
                blocked_calls.append(tc)
                print(f">>> [tools] 🚫 拦截禁用工具调用: {tc['name']}")
            else:
                if tc["name"] in USER_INJECTED_TOOLS:
                    tc["args"]["username"] = user_id
                # 给 add_alarm 额外注入 session_id，让闹钟记住设置时的会话
                if tc["name"] == "add_alarm":
                    tc["args"]["session_id"] = state.get("session_id") or "default"
                allowed_calls.append(tc)
                print(f">>> [tools] ✅ 调用工具: {tc['name']}")

        result_messages = []

        # For blocked tools, return error ToolMessages directly
        for tc in blocked_calls:
            result_messages.append(
                ToolMessage(
                    content=f"❌ 工具 '{tc['name']}' 当前已被禁用，无法执行。请用户先在工具面板中启用该工具。",
                    tool_call_id=tc["id"],
                )
            )

        # For allowed tools, execute normally via ToolNode
        if allowed_calls:
            modified_message.tool_calls = allowed_calls
            modified_state = {**state, "messages": state["messages"][:-1] + [modified_message]}
            tool_result = await self.tool_node.ainvoke(modified_state, config)
            result_messages.extend(tool_result.get("messages", []))

        return {"messages": result_messages}


class MiniTimeAgent:
    """
    Encapsulates the full LangGraph agent: MCP tool loading, graph building,
    invoke/stream interface, task & tool-state management.
    """

    def __init__(self, src_dir: str, db_path: str):
        """
        Args:
            src_dir:  Path to src/ directory (where mcp_*.py live)
            db_path:  Path to SQLite checkpoint database
        """
        self._src_dir = src_dir
        self._db_path = db_path

        # Populated during startup
        self._mcp_tools: list = []
        self._agent_app = None
        self._mcp_client: Optional[MultiServerMCPClient] = None
        self._memory = None
        self._memory_ctx = None

        # Per-user state
        self._active_tasks: dict[str, asyncio.Task] = {}
        self._task_lock = asyncio.Lock()
        self._user_last_tool_state: dict[str, frozenset[str]] = {}

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------
    @property
    def mcp_tools(self) -> list:
        return self._mcp_tools

    @property
    def agent_app(self):
        return self._agent_app

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    async def startup(self):
        """Initialize MCP client, load tools, build LangGraph workflow."""
        # 1. Open checkpoint DB
        self._memory_ctx = AsyncSqliteSaver.from_conn_string(self._db_path)
        self._memory = await self._memory_ctx.__aenter__()

        # 2. Start MCP servers
        self._mcp_client = MultiServerMCPClient({
            "scheduler_service": {
                "command": "python",
                "args": [os.path.join(self._src_dir, "mcp_scheduler.py")],
                "transport": "stdio",
            },
            "search_service": {
                "command": "python",
                "args": [os.path.join(self._src_dir, "mcp_search.py")],
                "transport": "stdio",
            },
            "file_service": {
                "command": "python",
                "args": [os.path.join(self._src_dir, "mcp_filemanager.py")],
                "transport": "stdio",
            },
            "commander_service": {
                "command": "python",
                "args": [os.path.join(self._src_dir, "mcp_commander.py")],
                "transport": "stdio",
            },
            "oasis_service": {
                "command": "python",
                "args": [os.path.join(self._src_dir, "mcp_oasis.py")],
                "transport": "stdio",
            },
            "bark_service": {
                "command": "python",
                "args": [os.path.join(self._src_dir, "mcp_bark.py")],
                "transport": "stdio",
            },
        })

        # 3. Fetch tool definitions (new API: no context manager needed)
        self._mcp_tools = await self._mcp_client.get_tools()

        # 4. Build LangGraph workflow
        workflow = StateGraph(AgentState)
        workflow.add_node("chatbot", self._call_model)
        workflow.add_node("tools", UserAwareToolNode(self._mcp_tools, lambda: self._mcp_tools))
        workflow.add_edge(START, "chatbot")
        workflow.add_conditional_edges("chatbot", tools_condition)
        workflow.add_edge("tools", "chatbot")

        self._agent_app = workflow.compile(checkpointer=self._memory)
        print("--- Agent 服务已启动，外部定时/用户输入双兼容就绪 ---")

    async def shutdown(self):
        """Clean up MCP client and checkpoint DB."""
        if self._memory_ctx:
            try:
                await self._memory_ctx.__aexit__(None, None, None)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Model factory
    # ------------------------------------------------------------------
    @staticmethod
    def _get_model() -> ChatDeepSeek:
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            raise ValueError("未检测到 DEEPSEEK_API_KEY，请在环境变量中设置。")
        return ChatDeepSeek(
            model="deepseek-chat",
            api_key=api_key,
            temperature=0.7,
            max_tokens=2048,
            timeout=60,
            max_retries=2,
        )

    # ------------------------------------------------------------------
    # Core graph node
    # ------------------------------------------------------------------
    async def _call_model(self, state: AgentState):
        """LangGraph node: invoke LLM with dynamic tool binding & tool-state notification."""

        # Dynamic tool binding based on enabled_tools
        all_tools = self._mcp_tools
        enabled_names = state.get("enabled_tools")
        if enabled_names is not None:
            filtered_tools = [t for t in all_tools if t.name in enabled_names]
        else:
            filtered_tools = all_tools

        base_model = self._get_model()
        llm = base_model.bind_tools(filtered_tools) if filtered_tools else base_model

        # --- KV-Cache-friendly tool state management ---
        all_names = sorted(t.name for t in all_tools)
        all_tool_list_str = ", ".join(all_names)

        base_prompt = (
            "你是一个专业的智能助理，具备以下能力：\n"
            "1. 定时任务管理：可以为用户设置、查看和删除闹钟/定时任务。\n"
            "2. 联网搜索：当用户询问实时信息、新闻或需要查询资料时，请主动使用搜索工具。\n"
            "3. 文件管理：可以为用户创建、读取、追加、删除和列出文件。"
            "调用文件管理工具（list_files, read_file, write_file, append_file, delete_file）时，"
            "username 参数由系统自动注入，你不需要也不应该提供该参数。\n"
            "4. 指令执行：可以在用户的安全沙箱目录中执行系统命令和 Python 代码。\n"
            "5. OASIS 论坛：当用户的问题需要多角度深入分析时（如策略评估、利弊分析、争议话题等），\n"
            "   可以使用 post_to_oasis 工具发起多专家讨论，由创意、批判、数据、综合四位专家并行辩论后给出结论。\n"
            "   使用 check_oasis_discussion 可查看讨论进展，list_oasis_topics 可查看历史讨论。\n"
            "6. 推送通知：可以向用户的手机发送推送通知（通过 Bark）。\n"
            "   - set_push_key：保存用户的 Bark Key（用户首次配置推送时使用）\n"
            "   - send_push_notification：发送推送通知到用户手机\n"
            "   - get_push_status：查看推送配置状态\n"
            "   - set_public_url：设置用户级公网地址（推送点击后跳转用）\n"
            "   - get_public_url：查看当前公网地址配置\n"
            "   - clear_public_url：清除用户级公网地址配置\n"
            "   调用推送工具时，username 参数由系统自动注入，你不需要也不应该提供该参数。\n"
            "   当定时任务触发时，如果用户已配置 Bark Key，可以主动发送推送通知提醒用户。\n"
            "   - run_command：执行 shell 命令（ls、grep、cat、curl 等白名单内的命令）\n"
            "   - run_python_code：执行 Python 代码片段（数据计算、文本处理等）\n"
            "   - list_allowed_commands：查看允许执行的命令白名单\n"
            "   调用 run_command 和 run_python_code 时，username 参数由系统自动注入，你不需要也不应该提供该参数。\n\n"
            "【工具使用规则】\n"
            "- 只有当用户明确要求【测试工具】或【测试tool】时，才对工具进行测试性调用。"
            "日常对话中不要主动测试工具。\n"
            "- 当用户要求你记录、保存、备忘某些事情，或者你判断对话中出现了重要信息值得长期保留时，"
            "请主动使用文件管理工具将内容写入用户的文件中。\n"
            "- 当你需要回忆或查询用户之前记录的长期信息时，请使用文件管理工具读取用户的文件。\n"
            "- 当用户要求执行命令、运行代码、查看系统信息等操作时，使用指令执行工具。\n"
            "- 对于复杂的数据处理任务，优先使用 run_python_code 而非多个 shell 命令。\n\n"
            f"【默认可用工具列表】\n{all_tool_list_str}\n"
            "以上工具默认全部启用。如果后续有工具状态变更，系统会另行通知。\n"
        )

        # Detect tool state change
        current_enabled = frozenset(enabled_names) if enabled_names is not None else frozenset(all_names)
        user_id = state.get("user_id", "__global__")
        last_state = self._user_last_tool_state.get(user_id)

        tool_status_prompt = ""
        if last_state is not None and current_enabled != last_state:
            all_names_set = set(all_names)
            enabled_set = set(current_enabled)
            disabled_names_set = all_names_set - enabled_set
            tool_status_prompt = (
                "【工具可用情况更新】\n"
                f"已启用的工具：{', '.join(sorted(enabled_set & all_names_set)) if (enabled_set & all_names_set) else '无'}\n"
                f"已禁用的工具：{', '.join(sorted(disabled_names_set)) if disabled_names_set else '无'}\n"
                "请注意：被禁用的工具在本次对话中不可使用。如果用户的请求需要被禁用的工具，"
                "请礼貌地告知用户需要先启用对应的工具。\n"
            )
        elif last_state is None and enabled_names is not None:
            all_names_set = set(all_names)
            enabled_set = set(current_enabled)
            disabled_names_set = all_names_set - enabled_set
            if disabled_names_set:
                tool_status_prompt = (
                    "【工具可用情况更新】\n"
                    f"已启用的工具：{', '.join(sorted(enabled_set & all_names_set)) if (enabled_set & all_names_set) else '无'}\n"
                    f"已禁用的工具：{', '.join(sorted(disabled_names_set))}\n"
                    "请注意：被禁用的工具在本次对话中不可使用。如果用户的请求需要被禁用的工具，"
                    "请礼貌地告知用户需要先启用对应的工具。\n"
                )

        # Update cache
        self._user_last_tool_state[user_id] = current_enabled

        history_messages = list(state["messages"])

        # 每次进入前清理：移除末尾不完整的 tool_calls（有 AIMessage 带 tool_calls 但缺少 ToolMessage 回复）
        history_messages = self._sanitize_messages(history_messages)

        # 如果是系统触发，且最后一条不是 ToolMessage（非工具回调轮），给它加上系统触发说明
        is_system = state.get("trigger_source") == "system"
        if is_system and history_messages and isinstance(history_messages[-1], HumanMessage):
            original_text = history_messages[-1].content
            system_trigger_prompt = (
                "[系统触发] 当前请求来自定时任务调度器，而非用户实时对话。\n"
                "请根据触发内容执行相应操作（如发送推送通知提醒用户、执行预设指令等）。\n"
                "你可以正常使用所有已启用的工具。\n"
                f"---\n{original_text}"
            )
            history_messages = history_messages[:-1] + [HumanMessage(content=system_trigger_prompt)]

        # 正常对话流程（用户和系统触发共用）
        if tool_status_prompt and len(history_messages) >= 1:
            last_msg = history_messages[-1]
            augmented_content = f"[系统通知] {tool_status_prompt}\n\n---\n{last_msg.content}"
            augmented_msg = HumanMessage(content=augmented_content)
            input_messages = (
                [SystemMessage(content=base_prompt)]
                + history_messages[:-1]
                + [augmented_msg]
            )
        else:
            input_messages = [SystemMessage(content=base_prompt)] + history_messages

        response = await llm.ainvoke(input_messages)
        return {"messages": [response]}

    # ------------------------------------------------------------------
    # Public interface: tools info
    # ------------------------------------------------------------------
    @staticmethod
    def _sanitize_messages(messages: list) -> list:
        """
        清理消息列表，确保每条带 tool_calls 的 AI 消息后面都有对应的 ToolMessage。
        如果末尾有不完整的 tool_calls 序列，直接截断丢弃。
        """
        # 收集所有已存在的 tool_call_id 回复
        answered_ids = set()
        for msg in messages:
            if isinstance(msg, ToolMessage) and hasattr(msg, "tool_call_id"):
                answered_ids.add(msg.tool_call_id)

        # 从后往前找到第一个"完整"的位置
        clean = list(messages)
        while clean:
            last = clean[-1]
            # 如果最后一条是带 tool_calls 的 AI 消息，检查是否全部有回复
            if isinstance(last, AIMessage) and hasattr(last, "tool_calls") and last.tool_calls:
                pending_ids = {tc["id"] for tc in last.tool_calls}
                if not pending_ids.issubset(answered_ids):
                    clean.pop()
                    continue
            break
        return clean

    def get_tools_info(self) -> list[dict]:
        """Return serializable tool metadata list."""
        return [{"name": t.name, "description": t.description or ""} for t in self._mcp_tools]

    # ------------------------------------------------------------------
    # Public interface: task management
    # ------------------------------------------------------------------
    async def cancel_task(self, user_id: str):
        """Cancel the active streaming task for a user."""
        async with self._task_lock:
            task = self._active_tasks.get(user_id)
            if task and not task.done():
                task.cancel()
                try:
                    await asyncio.wait_for(asyncio.shield(task), timeout=5.0)
                except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
                    pass
            self._active_tasks.pop(user_id, None)

    def register_task(self, user_id: str, task: asyncio.Task):
        """Register an active streaming task for a user."""
        self._active_tasks[user_id] = task

    def unregister_task(self, user_id: str):
        """Remove a finished task from the registry."""
        self._active_tasks.pop(user_id, None)
