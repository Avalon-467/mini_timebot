import os
import copy
import json
import hashlib
import asyncio
from datetime import datetime
from typing import Annotated, TypedDict, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import uvicorn

# LangGraph 相关
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

# 模型相关
from langchain_deepseek import ChatDeepSeek
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain_core.runnables import RunnableConfig
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.prebuilt import ToolNode, tools_condition

from dotenv import load_dotenv

# 1. 获取当前脚本 (src/main.py) 的绝对路径
current_dir = os.path.dirname(os.path.abspath(__file__))

# 2. 定位项目根目录 (src 的上一级)
root_dir = os.path.dirname(current_dir)

# 3. 拼接 env 和 db 的路径
env_path = os.path.join(root_dir, "config", ".env")
db_path = os.path.join(root_dir, "data", "agent_memory.db")
users_path = os.path.join(root_dir, "config", "users.json")

# 加载配置
load_dotenv(dotenv_path=env_path)


def load_users() -> dict:
    """加载用户名-密码哈希配置"""
    if not os.path.exists(users_path):
        print(f"⚠️ 未找到用户配置文件 {users_path}，请先运行 python tools/gen_password.py 创建用户")
        return {}
    with open(users_path, "r", encoding="utf-8") as f:
        return json.load(f)


def verify_password(username: str, password: str) -> bool:
    """验证用户密码：对输入密码做 sha256 后与配置中的哈希比对"""
    users = load_users()
    if username not in users:
        return False
    pw_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
    return pw_hash == users[username]

# 需要自动注入 username 的工具集合（文件管理 + 指令执行）
USER_INJECTED_TOOLS = {
    # 文件管理工具
    "list_files", "read_file", "write_file", "append_file", "delete_file",
    # 指令执行工具
    "run_command", "run_python_code",
}


class UserAwareToolNode:
    """
    自定义工具节点：从 RunnableConfig 中读取 thread_id，
    自动注入为文件管理工具的 username 参数。
    LLM 不需要传 username，由 config.thread_id 自动提供。
    """
    def __init__(self, tools):
        self.tool_node = ToolNode(tools)

    async def __call__(self, state, config: RunnableConfig):
        thread_id = config.get("configurable", {}).get("thread_id", "anonymous")

        last_message = state["messages"][-1]
        if not hasattr(last_message, "tool_calls") or not last_message.tool_calls:
            return {"messages": []}

        # 深拷贝并注入 username
        modified_message = copy.deepcopy(last_message)
        for tc in modified_message.tool_calls:
            if tc["name"] in USER_INJECTED_TOOLS:
                tc["args"]["username"] = thread_id

        modified_state = {**state, "messages": state["messages"][:-1] + [modified_message]}
        return await self.tool_node.ainvoke(modified_state, config)


# --- 1. 定义状态 (State) ---
class State(TypedDict):
    # 消息列表：使用 add_messages 叠加
    messages: Annotated[list, add_messages]
    # 标记来源：区分 "user" 或 "system"
    trigger_source: str 

# --- 2. 定义节点 (Nodes) ---
def get_model():
    """
    配置并返回 LLM 实例
    """
    # 确保 API KEY 已设置
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise ValueError("未检测到 DEEPSEEK_API_KEY，请在环境变量中设置。")

    return ChatDeepSeek(
        model='deepseek-chat', 
        # 1. 核心 Token 设置
        api_key=api_key,
        # 2. 控制生成的随机性 (0.0 为最严谨，1.0 为最发散)
        temperature=0.7,
        # 3. 最大输出 Token 数，防止生成过长浪费额度（总结任务建议设高一点）
        max_tokens=2048,
        # 4. 网络超时设置 (单位：秒)
        timeout=60,
        # 5. 最大重试次数，应对网络波动
        max_retries=2,
        # 6. 如果使用中转 API，取消下面注释
        # api_base="https://your-proxy-url.com/v1"
    )



# --- 修改后的 call_model 节点 ---

async def call_model(state: State):
    """
    模型调用节点：集成完整参数设置
    """
    

    # 获取配置好的模型
    llm=app.state.sharedllm
    
    # 基础系统提示词
    base_prompt = (
        "你是一个专业的智能助理，具备以下能力：\n"
        "1. 定时任务管理：可以为用户设置、查看和删除闹钟/定时任务。\n"
        "2. 联网搜索：当用户询问实时信息、新闻或需要查询资料时，请主动使用搜索工具。\n"
        "3. 文件管理：可以为用户创建、读取、追加、删除和列出文件。"
        "调用文件管理工具（list_files, read_file, write_file, append_file, delete_file）时，"
        "username 参数由系统自动注入，你不需要也不应该提供该参数。\n"
        "4. 指令执行：可以在用户的安全沙箱目录中执行系统命令和 Python 代码。\n"
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
        "- 对于复杂的数据处理任务，优先使用 run_python_code 而非多个 shell 命令。\n"
    )
    
    # 针对系统触发（外部定时）的特殊逻辑
    if state.get("trigger_source") == "system":
        # 构造一个临时的总结指令，不进入历史记录
        summary_prompt = "【系统指令】：请对该用户之前的对话进行核心诉求总结，供管理员参考。"
        input_messages = [SystemMessage(content=base_prompt), SystemMessage(content=summary_prompt)] + state["messages"]
        
        response = await llm.ainvoke(input_messages)
        
        # --- 重点：系统触发时不返回 messages，从而不改动数据库状态 ---
        print(f"\n>>> [外部定时任务执行中] 用户 {state.get('user_id', 'Unknown')} 总结结果:")
        print(f">>> {response.content}")
        return {} 

    # 针对用户触发的正常对话逻辑
    input_messages = [SystemMessage(content=base_prompt)] + state["messages"]
    response = await llm.ainvoke(input_messages)
    
    return {"messages": [response]}


# --- 4. FastAPI 生命周期管理 ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 初始化异步数据库连接
    async with AsyncSqliteSaver.from_conn_string(db_path) as memory:
        # 编译 Agent
        # 1. 定义服务器配置
        # 注意：这里我们手动指定 python 解释器和脚本路径
        client = MultiServerMCPClient({
            "scheduler_service": {
                "command": "python",
                "args": [os.path.join(current_dir, "mcp_scheduler.py")],
                "transport": "stdio"
            },
            "search_service": {
                "command": "python",
                "args": [os.path.join(current_dir, "mcp_search.py")],
                "transport": "stdio"
            },
            "file_service": {
                "command": "python",
                "args": [os.path.join(current_dir, "mcp_filemanager.py")],
                "transport": "stdio"
            },
            "commander_service": {
                "command": "python",
                "args": [os.path.join(current_dir, "mcp_commander.py")],
                "transport": "stdio"
            }
        })

        # 2. 获取工具列表
        # get_tools() 会自动启动子进程并获取定义的 @mcp.tool()
        tools = await client.get_tools()
        app.state.mcp_tools = tools # 存起来备用
        app.state.sharedllm= get_model().bind_tools(app.state.mcp_tools)


                # --- 3. 构建工作流 (Workflow) ---
        workflow = StateGraph(State)
        # --- 2. 构建新的 Graph 结构 ---
        workflow = StateGraph(State)

        # 添加节点
        workflow.add_node("chatbot", call_model)
        workflow.add_node("tools", UserAwareToolNode(tools)) # 自动注入 username 的工具节点

        # 设置起点
        workflow.add_edge(START, "chatbot")

        # --- 3. 设置核心路由逻辑 ---
        # 这一步最关键：模型跑完后，根据返回内容决定去哪里
        workflow.add_conditional_edges(
            "chatbot",
            tools_condition, # 官方提供的判断函数：有 tool_calls 就去 tools，没有就去 END
        )

        # 工具执行完后，必须回到 chatbot 让模型看结果
        workflow.add_edge("tools", "chatbot")
        app.state.agent_app = workflow.compile(checkpointer=memory)
        print("--- Agent 服务已启动，外部定时/用户输入双兼容就绪 ---")
        yield

app = FastAPI(lifespan=lifespan)

# --- 用户级任务管理 ---
# key: user_id, value: 当前活跃的 asyncio.Task
_active_tasks: dict[str, asyncio.Task] = {}
_task_lock = asyncio.Lock()

async def _cancel_and_wait(user_id: str):
    """取消指定用户的活跃任务并等待其结束"""
    task = _active_tasks.get(user_id)
    if task and not task.done():
        task.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=5.0)
        except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
            pass
    _active_tasks.pop(user_id, None)

# --- 5. API 定义 ---

class LoginRequest(BaseModel):
    user_id: str
    password: str

class UserRequest(BaseModel):
    user_id: str
    password: str
    text: str

class SystemTriggerRequest(BaseModel):
    user_id: str
    text: str = "summary" # 默认为总结指令

# 登录验证接口
@app.post("/login")
async def login(req: LoginRequest):
    if verify_password(req.user_id, req.password):
        return {"status": "success", "message": "登录成功"}
    raise HTTPException(status_code=401, detail="用户名或密码错误")

# A. 用户输入接口（需要密码验证）
@app.post("/ask")
async def ask_agent(req: UserRequest):
    if not verify_password(req.user_id, req.password):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    agent_app = app.state.agent_app
    config = {"configurable": {"thread_id": req.user_id}}
    
    user_input = {
        "messages": [HumanMessage(content=req.text)],
        "trigger_source": "user"
    }
    
    result = await agent_app.ainvoke(user_input, config)
    return {
        "status": "success",
        "response": result["messages"][-1].content
    }

# A2. 用户输入接口 — 流式响应（SSE）
@app.post("/ask_stream")
async def ask_agent_stream(req: UserRequest):
    if not verify_password(req.user_id, req.password):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    # 先取消该用户上一轮未完成的任务
    async with _task_lock:
        await _cancel_and_wait(req.user_id)

    agent_app = app.state.agent_app
    config = {"configurable": {"thread_id": req.user_id}}

    user_input = {
        "messages": [HumanMessage(content=req.text)],
        "trigger_source": "user"
    }

    # 用 asyncio.Queue 在 Task 和生成器之间传递 SSE 数据
    queue: asyncio.Queue[str | None] = asyncio.Queue()

    async def _stream_worker():
        """在独立 Task 中运行 astream_events，产出数据写入 queue"""
        collected_tokens = []  # 收集 LLM 输出的原始 token
        try:
            async for event in agent_app.astream_events(user_input, config, version="v2"):
                kind = event.get("event", "")
                if kind == "on_chat_model_stream":
                    chunk = event.get("data", {}).get("chunk")
                    if chunk and hasattr(chunk, "content") and chunk.content:
                        collected_tokens.append(chunk.content)
                        text = chunk.content.replace("\\", "\\\\").replace("\n", "\\n")
                        await queue.put(f"data: {text}\n\n")
                elif kind == "on_tool_start":
                    tool_name = event.get("name", "")
                    await queue.put(f"data: \\n🔧 调用工具: {tool_name}...\\n\n\n")
                elif kind == "on_tool_end":
                    await queue.put(f"data: \\n✅ 工具执行完成\\n\n\n")
            await queue.put("data: [DONE]\n\n")
        except asyncio.CancelledError:
            # 终止时，将已收集的 token 作为 AIMessage 写入 checkpoint
            partial_text = "".join(collected_tokens)
            if partial_text:
                partial_text += "\n\n⚠️ （回复被用户终止）"
                partial_msg = AIMessage(content=partial_text)
                await agent_app.aupdate_state(config, {"messages": [partial_msg]})
            await queue.put(f"data: \\n\\n⚠️ 已终止思考\n\n")
            await queue.put("data: [DONE]\n\n")
        except Exception as e:
            await queue.put(f"data: \\n❌ 流式响应异常: {str(e)}\n\n")
            await queue.put("data: [DONE]\n\n")
        finally:
            await queue.put(None)  # 哨兵值，通知生成器结束
            _active_tasks.pop(req.user_id, None)

    # 启动 worker Task 并注册
    task = asyncio.create_task(_stream_worker())
    _active_tasks[req.user_id] = task

    async def event_generator():
        while True:
            item = await queue.get()
            if item is None:
                break
            yield item

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

# B. 外部定时器触发接口 (兼容独立进程/Cron任务)

class CancelRequest(BaseModel):
    user_id: str
    password: str

@app.post("/cancel")
async def cancel_agent(req: CancelRequest):
    """终止指定用户的智能体思考：取消底层 Task"""
    if not verify_password(req.user_id, req.password):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    await _cancel_and_wait(req.user_id)
    return {"status": "success", "message": "已终止"}

# C. 外部定时器触发接口 (兼容独立进程/Cron任务)
@app.post("/system_trigger")
async def system_trigger(req: SystemTriggerRequest):
    agent_app = app.state.agent_app
    config = {"configurable": {"thread_id": req.user_id}}
    
    # 注意：这里的输入不会被持久化到数据库，因为 call_model 针对 system 触发返回了 {}
    system_input = {
        "messages": [HumanMessage(content=f"执行指令: {req.text}")],
        "trigger_source": "system"
    }
    
    # 异步触发，不需要等待结果返回给外部定时器，或者返回执行成功即可
    asyncio.create_task(agent_app.ainvoke(system_input, config))

    return {
        "status": "received",
        "message": f"已经为用户 {req.user_id} 启动外部定时任务"
    }

if __name__ == "__main__":
    # 启动命令：python main.py
    uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("PORT_AGENT", "51200")))