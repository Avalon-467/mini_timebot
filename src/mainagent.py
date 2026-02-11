import os
import asyncio
from datetime import datetime
from typing import Annotated, TypedDict, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel
import uvicorn

# LangGraph 相关
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

# 模型相关
from langchain_deepseek import ChatDeepSeek
from langchain_core.messages import SystemMessage, HumanMessage
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

# 加载配置
load_dotenv(dotenv_path=env_path)

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
    base_prompt = "你是一个专业的智能助理，具备定时任务管理和联网搜索能力。当用户询问实时信息、新闻或需要查询资料时，请主动使用搜索工具。"
    
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
        workflow.add_node("tools", ToolNode(tools)) # 专门执行工具的节点

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

# --- 5. API 定义 ---

class UserRequest(BaseModel):
    user_id: str
    text: str

class SystemTriggerRequest(BaseModel):
    user_id: str
    text: str = "summary" # 默认为总结指令

# A. 用户输入接口
@app.post("/ask")
async def ask_agent(req: UserRequest):
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

# B. 外部定时器触发接口 (兼容独立进程/Cron任务)
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
    uvicorn.run(app, host="127.0.0.1", port=8000)