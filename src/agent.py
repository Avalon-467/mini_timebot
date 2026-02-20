import os
import json
import copy
import asyncio
from typing import Annotated, TypedDict, Optional

# LangGraph related
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

# Model related
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.prebuilt import ToolNode


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
    # 外部调用方传入的 tools 定义（OpenAI function calling 格式）
    # 当 LLM 选择调用这些工具时，中断图执行并以 tool_calls 格式返回给调用方
    external_tools: Optional[list[dict]]


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
                    content=f"❌ 工具 '{tc['name']}' 当前已被禁用。这通常是为了保护您的系统安全或优化当前会话资源。如果您确实需要此功能，请在管理面板中将其开启。同时，您可以告诉我您的最终目标，我会尝试用其他已启用的工具为您寻找替代方案。",
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

        # 启动时一次性加载 prompt 模板
        self._prompts = self._load_prompts()

    # ------------------------------------------------------------------
    # Prompt loader (启动时读取一次)
    # ------------------------------------------------------------------
    @staticmethod
    def _load_prompts() -> dict[str, str]:
        """从 data/prompts/ 加载所有 prompt 模板文件，服务启动时调用一次。"""
        prompts_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "prompts")
        prompt_files = {
            "base_system": "base_system.txt",
            "system_trigger": "system_trigger.txt",
            "tool_status": "tool_status.txt",
        }
        loaded = {}
        for key, filename in prompt_files.items():
            filepath = os.path.join(prompts_dir, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    loaded[key] = f.read().strip()
                print(f"[prompts] ✅ 已加载 {filename}")
            except FileNotFoundError:
                print(f"[prompts] ⚠️ 未找到 {filepath}，将使用内置默认值")
                loaded[key] = ""

        # 记录 user_files 根目录路径（用户画像存在各用户目录下）
        loaded["_user_files_dir"] = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "data", "user_files"
        )

        return loaded

    def _get_user_profile(self, user_id: str) -> str:
        """从 data/user_files/{user_id}/user_profile.txt 读取用户画像。"""
        user_files_dir = self._prompts.get("_user_files_dir", "")
        fpath = os.path.join(user_files_dir, user_id, "user_profile.txt")
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                return f.read().strip()
        except FileNotFoundError:
            return ""

    def _get_user_skills(self, user_id: str) -> str:
        """
        从 data/user_files/{user_id}/skills_manifest.json 读取用户的 skill list，
        并返回格式化的 skill 信息字符串。
        即使没有 skill，也会返回位置信息。
        """
        user_files_dir = self._prompts.get("_user_files_dir", "")
        manifest_path = os.path.join(user_files_dir, user_id, "skills_manifest.json")
        skills_dir = os.path.join(user_files_dir, user_id, "skills")

        skills_manifest = []
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                skills_manifest = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            pass

        # 格式化 skill 信息（即使为空也返回位置信息）
        skill_lines = ["\n【用户技能列表】"]
        skill_lines.append(f"技能清单文件位置: {manifest_path}")
        skill_lines.append(f"技能文件目录位置: {skills_dir}")

        if skills_manifest:
            skill_lines.append("可用技能：")
            for skill in skills_manifest:
                skill_name = skill.get("name", "未命名技能")
                skill_desc = skill.get("description", "无描述")
                skill_file = skill.get("file", "")
                skill_lines.append(f"  - {skill_name}: {skill_desc}")
                if skill_file:
                    skill_lines.append(f"    文件: {os.path.join(skills_dir, skill_file)}")
            skill_lines.append("如需使用某个技能，请使用文件管理工具读取对应的技能文件。")
        else:
            skill_lines.append("当前暂无已注册的技能。")
            skill_lines.append("如需添加技能，请在技能清单文件中添加技能信息。")

        return "\n".join(skill_lines)

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
        # 收集所有内部 MCP 工具名称，用于条件路由
        self._internal_tool_names = frozenset(t.name for t in self._mcp_tools)

        workflow = StateGraph(AgentState)
        workflow.add_node("chatbot", self._call_model)
        workflow.add_node("tools", UserAwareToolNode(self._mcp_tools, lambda: self._mcp_tools))
        workflow.add_edge(START, "chatbot")
        workflow.add_conditional_edges("chatbot", self._should_continue)
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
    def _get_model() -> ChatOpenAI:
        api_key = os.getenv("LLM_API_KEY")
        base_url = os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1")
        model = os.getenv("LLM_MODEL", "deepseek-chat")
        if not api_key:
            raise ValueError("未检测到 LLM_API_KEY，请在环境变量中设置。")
        return ChatOpenAI(
            model=model,
            base_url=base_url,
            api_key=api_key,
            temperature=0.7,
            max_tokens=2048,
            timeout=60,
            max_retries=2,
        )

    # ------------------------------------------------------------------
    # Conditional edge: route internal tools vs external tools vs end
    # ------------------------------------------------------------------
    def _should_continue(self, state: AgentState) -> str:
        """
        条件路由：
        - 无 tool_calls → "end" (正常结束)
        - 所有 tool_calls 都是内部工具 → "tools" (继续内部循环)
        - 存在外部工具调用 → "end" (中断返回 tool_calls 给调用方)
        """
        last_msg = state["messages"][-1]
        if not hasattr(last_msg, "tool_calls") or not last_msg.tool_calls:
            return END

        for tc in last_msg.tool_calls:
            if tc["name"] not in self._internal_tool_names:
                # 发现外部工具调用，中断循环让调用方处理
                print(f">>> [route] 🔀 外部工具调用检测: {tc['name']}，中断返回给调用方")
                return END
        return "tools"

    # ------------------------------------------------------------------
    # Core graph node
    # ------------------------------------------------------------------
    async def _call_model(self, state: AgentState):
        """LangGraph node: invoke LLM with dynamic tool binding & tool-state notification."""

        # Dynamic tool binding based on enabled_tools + external_tools
        all_tools = self._mcp_tools
        enabled_names = state.get("enabled_tools")
        if enabled_names is not None:
            filtered_tools = [t for t in all_tools if t.name in enabled_names]
        else:
            filtered_tools = all_tools

        # 将外部工具定义（OpenAI function format）转为 LangChain 可绑定的格式
        external_tools_defs = state.get("external_tools") or []
        bind_tools_list: list = list(filtered_tools)
        external_tool_names: set[str] = set()
        for ext_tool in external_tools_defs:
            # 支持 OpenAI 标准格式: {"type":"function","function":{...}} 或简化格式 {"name":...,"parameters":...}
            if ext_tool.get("type") == "function":
                func_def = ext_tool.get("function", {})
            else:
                func_def = ext_tool
            if func_def.get("name"):
                external_tool_names.add(func_def["name"])
                # 以 OpenAI function 格式传入 bind_tools（LangChain 支持 dict 格式）
                bind_tools_list.append({
                    "type": "function",
                    "function": {
                        "name": func_def["name"],
                        "description": func_def.get("description", ""),
                        "parameters": func_def.get("parameters", {"type": "object", "properties": {}}),
                    },
                })

        base_model = self._get_model()
        llm = base_model.bind_tools(bind_tools_list) if bind_tools_list else base_model

        # --- KV-Cache-friendly tool state management ---
        all_names = sorted(t.name for t in all_tools)
        all_tool_list_str = ", ".join(all_names)

        base_prompt = (
            self._prompts["base_system"] + "\n\n"
            f"【默认可用工具列表】\n{all_tool_list_str}\n"
            "以上工具默认全部启用。如果后续有工具状态变更，系统会另行通知。\n"
        )

        # Detect tool state change
        current_enabled = frozenset(enabled_names) if enabled_names is not None else frozenset(all_names)
        user_id = state.get("user_id", "__global__")

        # 注入用户专属画像
        user_profile = self._get_user_profile(user_id)
        if user_profile:
            base_prompt += f"\n{user_profile}\n"

        # 注入用户技能列表（总是显示位置信息）
        base_prompt += self._get_user_skills(user_id) + "\n"

        last_state = self._user_last_tool_state.get(user_id)

        tool_status_prompt = ""
        if last_state is not None and current_enabled != last_state:
            all_names_set = set(all_names)
            enabled_set = set(current_enabled)
            disabled_names_set = all_names_set - enabled_set
            tool_status_prompt = self._prompts["tool_status"].format(
                enabled_tools=', '.join(sorted(enabled_set & all_names_set)) if (enabled_set & all_names_set) else '无',
                disabled_tools=', '.join(sorted(disabled_names_set)) if disabled_names_set else '无',
            )
        elif last_state is None and enabled_names is not None:
            all_names_set = set(all_names)
            enabled_set = set(current_enabled)
            disabled_names_set = all_names_set - enabled_set
            if disabled_names_set:
                tool_status_prompt = self._prompts["tool_status"].format(
                    enabled_tools=', '.join(sorted(enabled_set & all_names_set)) if (enabled_set & all_names_set) else '无',
                    disabled_tools=', '.join(sorted(disabled_names_set)),
                )

        # Update cache
        self._user_last_tool_state[user_id] = current_enabled

        history_messages = list(state["messages"])

        # 每次进入前清理：移除末尾不完整的 tool_calls（有 AIMessage 带 tool_calls 但缺少 ToolMessage 回复）
        # 但保留外部工具的未回复 tool_calls（它们正等待调用方回传结果）
        history_messages = self._sanitize_messages(history_messages, external_tool_names)

        # 清理历史消息中的多模态内容（file/image/audio parts），只保留文本
        # 避免旧的二进制附件在后续轮次反复发送给 LLM 导致上游 API 报错
        # 注意：保留最后一条 HumanMessage 的多模态内容（当前轮用户输入）
        if len(history_messages) > 1:
            history_messages = self._strip_multimodal_parts(history_messages[:-1]) + [history_messages[-1]]

        # 如果是系统触发，且最后一条不是 ToolMessage（非工具回调轮），给它加上系统触发说明
        is_system = state.get("trigger_source") == "system"
        if is_system and history_messages and isinstance(history_messages[-1], HumanMessage):
            original_text = history_messages[-1].content
            system_trigger_prompt = self._prompts["system_trigger"].format(
                original_text=original_text
            )
            history_messages = history_messages[:-1] + [HumanMessage(content=system_trigger_prompt)]

        # 正常对话流程（用户和系统触发共用）
        if tool_status_prompt and len(history_messages) >= 1:
            last_msg = history_messages[-1]
            # 如果最后一条是多模态 content（list），将通知插入为第一个 text part
            if isinstance(last_msg.content, list):
                notification = {"type": "text", "text": f"[系统通知] {tool_status_prompt}\n\n---\n"}
                augmented_content = [notification] + list(last_msg.content)
                augmented_msg = HumanMessage(content=augmented_content)
            else:
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
    def _sanitize_messages(messages: list, external_tool_names: set[str] | None = None) -> list:
        """
        清理消息列表，确保每条带 tool_calls 的 AI 消息后面都有对应的 ToolMessage。
        如果末尾有不完整的 tool_calls 序列，直接截断丢弃。

        但如果 external_tool_names 非空，则保留末尾 AIMessage 中属于外部工具的
        未回复 tool_calls（它们正等待调用方回传结果）。
        """
        if not external_tool_names:
            external_tool_names = set()

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
                    # 检查未回复的 tool_calls 是否全部属于外部工具
                    unanswered_calls = [
                        tc for tc in last.tool_calls if tc["id"] not in answered_ids
                    ]
                    all_external = all(
                        tc["name"] in external_tool_names for tc in unanswered_calls
                    )
                    if all_external and external_tool_names:
                        # 外部工具等待回传，保留此消息
                        break
                    # 内部工具未完成 → 截断
                    clean.pop()
                    continue
            break
        return clean

    @staticmethod
    def _strip_multimodal_parts(messages: list) -> list:
        """
        将所有 HumanMessage 中的多模态 content（list 格式）转为纯文本。
        - type:"text" 的 part 保留文本
        - type:"file" 替换为 "[用户上传了文件: {filename}]"
        - type:"image_url" 替换为 "[用户上传了图片]"
        - 其他未知 type 丢弃
        """
        result = []
        for msg in messages:
            if isinstance(msg, HumanMessage) and isinstance(msg.content, list):
                text_parts = []
                for part in msg.content:
                    if not isinstance(part, dict):
                        text_parts.append(str(part))
                        continue
                    ptype = part.get("type", "")
                    if ptype == "text":
                        text_parts.append(part.get("text", ""))
                    elif ptype == "file":
                        fname = part.get("file", {}).get("filename", "附件")
                        text_parts.append(f"[用户上传了文件: {fname}]")
                    elif ptype == "image_url":
                        text_parts.append("[用户上传了图片]")
                combined = "\n".join(t for t in text_parts if t)
                result.append(HumanMessage(content=combined or "(空消息)"))
            else:
                result.append(msg)
        return result

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
