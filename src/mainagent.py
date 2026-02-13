import os
import json
import hashlib
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional
import uvicorn

from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

from dotenv import load_dotenv

from agent import MiniTimeAgent

# --- Path setup ---
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(current_dir)

env_path = os.path.join(root_dir, "config", ".env")
db_path = os.path.join(root_dir, "data", "agent_memory.db")
users_path = os.path.join(root_dir, "config", "users.json")

load_dotenv(dotenv_path=env_path)


# --- User auth helpers ---
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


# --- Create agent instance ---
agent = MiniTimeAgent(src_dir=current_dir, db_path=db_path)


# --- FastAPI lifespan ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    await agent.startup()
    yield
    await agent.shutdown()


app = FastAPI(lifespan=lifespan)


# --- Request models ---
class LoginRequest(BaseModel):
    user_id: str
    password: str

class UserRequest(BaseModel):
    user_id: str
    password: str
    text: str
    enabled_tools: Optional[list[str]] = None
    session_id: str = "default"

class SystemTriggerRequest(BaseModel):
    user_id: str
    text: str = "summary"

class CancelRequest(BaseModel):
    user_id: str
    password: str
    session_id: str = "default"


# --- Routes ---

@app.get("/tools")
async def get_tools_list():
    """返回当前 Agent 加载的所有 MCP 工具信息"""
    return {"status": "success", "tools": agent.get_tools_info()}


@app.post("/login")
async def login(req: LoginRequest):
    if verify_password(req.user_id, req.password):
        return {"status": "success", "message": "登录成功"}
    raise HTTPException(status_code=401, detail="用户名或密码错误")


@app.post("/ask")
async def ask_agent(req: UserRequest):
    if not verify_password(req.user_id, req.password):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    # Compose thread_id: user_id#session_id for conversation isolation
    thread_id = f"{req.user_id}#{req.session_id}"
    config = {"configurable": {"thread_id": thread_id}}
    user_input = {
        "messages": [HumanMessage(content=req.text)],
        "trigger_source": "user",
        "enabled_tools": req.enabled_tools,
        "user_id": req.user_id,
    }

    result = await agent.agent_app.ainvoke(user_input, config)
    return {"status": "success", "response": result["messages"][-1].content}


@app.post("/ask_stream")
async def ask_agent_stream(req: UserRequest):
    if not verify_password(req.user_id, req.password):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    # Cancel previous active task for this user+session
    task_key = f"{req.user_id}#{req.session_id}"
    await agent.cancel_task(task_key)

    # Compose thread_id: user_id#session_id for conversation isolation
    thread_id = f"{req.user_id}#{req.session_id}"
    config = {"configurable": {"thread_id": thread_id}}
    user_input = {
        "messages": [HumanMessage(content=req.text)],
        "trigger_source": "user",
        "enabled_tools": req.enabled_tools,
        "user_id": req.user_id,
    }

    queue: asyncio.Queue[str | None] = asyncio.Queue()

    async def _stream_worker(task_key=task_key):
        """在独立 Task 中运行 astream_events，产出数据写入 queue"""
        collected_tokens = []
        try:
            async for event in agent.agent_app.astream_events(user_input, config, version="v2"):
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
            # 终止时，修复 checkpoint 中可能不完整的消息序列
            try:
                snapshot = await agent.agent_app.aget_state(config)
                last_msgs = snapshot.values.get("messages", [])
                if last_msgs:
                    last_msg = last_msgs[-1]
                    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
                        tool_messages = [
                            ToolMessage(
                                content="⚠️ 工具调用被用户终止",
                                tool_call_id=tc["id"],
                            )
                            for tc in last_msg.tool_calls
                        ]
                        await agent.agent_app.aupdate_state(config, {"messages": tool_messages})
            except Exception:
                pass

            partial_text = "".join(collected_tokens)
            if partial_text:
                partial_text += "\n\n⚠️ （回复被用户终止）"
                partial_msg = AIMessage(content=partial_text)
                await agent.agent_app.aupdate_state(config, {"messages": [partial_msg]})
            await queue.put(f"data: \\n\\n⚠️ 已终止思考\n\n")
            await queue.put("data: [DONE]\n\n")
        except Exception as e:
            await queue.put(f"data: \\n❌ 流式响应异常: {str(e)}\n\n")
            await queue.put("data: [DONE]\n\n")
        finally:
            await queue.put(None)
            agent.unregister_task(task_key)

    task = asyncio.create_task(_stream_worker())
    agent.register_task(task_key, task)

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


@app.post("/cancel")
async def cancel_agent(req: CancelRequest):
    """终止指定用户的智能体思考"""
    if not verify_password(req.user_id, req.password):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    task_key = f"{req.user_id}#{req.session_id}"
    await agent.cancel_task(task_key)
    return {"status": "success", "message": "已终止"}


@app.post("/system_trigger")
async def system_trigger(req: SystemTriggerRequest):
    # System triggers use a dedicated session to avoid mixing with user conversations
    thread_id = f"{req.user_id}#__system__"
    config = {"configurable": {"thread_id": thread_id}}
    system_input = {
        "messages": [HumanMessage(content=f"执行指令: {req.text}")],
        "trigger_source": "system",
    }
    asyncio.create_task(agent.agent_app.ainvoke(system_input, config))
    return {"status": "received", "message": f"已经为用户 {req.user_id} 启动外部定时任务"}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("PORT_AGENT", "51200")))
