import os
import json
import hashlib
import asyncio
import secrets
import base64
from contextlib import asynccontextmanager

import aiosqlite
import httpx
from fastapi import FastAPI, HTTPException, Header
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional
import uvicorn

from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

from dotenv import load_dotenv

# API patch（提供音频格式适配和 MIME 修复）
from api_patch import patch_langchain_file_mime, build_audio_part
patch_langchain_file_mime()

from agent import MiniTimeAgent

# --- Path setup ---
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(current_dir)

env_path = os.path.join(root_dir, "config", ".env")
db_path = os.path.join(root_dir, "data", "agent_memory.db")
users_path = os.path.join(root_dir, "config", "users.json")
prompts_dir = os.path.join(root_dir, "data", "prompts")

load_dotenv(dotenv_path=env_path)

# 启动时加载 oasis_trigger prompt 模板
_oasis_trigger_tpl = ""
try:
    with open(os.path.join(prompts_dir, "oasis_trigger.txt"), "r", encoding="utf-8") as f:
        _oasis_trigger_tpl = f.read().strip()
    print("[prompts] ✅ mainagent 已加载 oasis_trigger.txt")
except FileNotFoundError:
    print("[prompts] ⚠️ 未找到 oasis_trigger.txt，将使用内置默认值")


# --- Internal token for service-to-service auth ---
INTERNAL_TOKEN = os.getenv("INTERNAL_TOKEN", "").strip()
if not INTERNAL_TOKEN:
    # Auto-generate a token and append to .env (replacing any empty INTERNAL_TOKEN= line)
    INTERNAL_TOKEN = secrets.token_hex(32)
    # Read existing content, replace empty placeholder if present
    with open(env_path, "r", encoding="utf-8") as f:
        content = f.read()
    if "INTERNAL_TOKEN=" in content:
        # Replace empty or placeholder line with real value
        import re
        content = re.sub(
            r"^INTERNAL_TOKEN=\s*$",
            f"INTERNAL_TOKEN={INTERNAL_TOKEN}",
            content,
            flags=re.MULTILINE,
        )
        with open(env_path, "w", encoding="utf-8") as f:
            f.write(content)
    else:
        with open(env_path, "a", encoding="utf-8") as f:
            f.write(f"\n# 内部服务间通信密钥（自动生成，勿泄露）\nINTERNAL_TOKEN={INTERNAL_TOKEN}\n")
    print(f"🔑 已自动生成 INTERNAL_TOKEN 并写入 {env_path}")


def verify_internal_token(token: str | None):
    """校验内部服务通信 token，失败抛 403"""
    if not token or token != INTERNAL_TOKEN:
        raise HTTPException(status_code=403, detail="无效的内部通信凭证")


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

# --- Oasis Bridge: 增量历史偏移量 ---
# session_id -> read offset (for incremental history delivery)
oasis_session_offsets: dict[str, int] = {}


# --- FastAPI lifespan ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    await agent.startup()
    yield
    await agent.shutdown()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


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
    images: Optional[list[str]] = None  # list of base64 data URIs
    files: Optional[list[dict]] = None  # list of {name: str, content: str}
    audios: Optional[list[dict]] = None  # list of {base64: str, name: str, format: str}

class SystemTriggerRequest(BaseModel):
    user_id: str
    text: str = "summary"
    session_id: str = "default"

class CancelRequest(BaseModel):
    user_id: str
    password: str
    session_id: str = "default"

class OasisAskRequest(BaseModel):
    """外部 OASIS 论坛调用本 Agent 参与讨论的请求"""
    session_id: str
    topic: str = "未知议题"
    history: list[dict] = []
    user_id: str = "oasis_external"


def _decode_pdf_data_uri(data_uri: str) -> bytes:
    """从 base64 data URI 解码出 PDF 字节。"""
    if "," in data_uri:
        data_uri = data_uri.split(",", 1)[1]
    return base64.b64decode(data_uri)


def _extract_pdf_text(data_uri: str) -> str:
    """从 base64 data URI 中提取 PDF 文本内容（纯文本模式）。"""
    try:
        import fitz  # pymupdf
        pdf_bytes = _decode_pdf_data_uri(data_uri)
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        pages = []
        for i, page in enumerate(doc):
            text = page.get_text()
            if text.strip():
                pages.append(f"--- 第{i+1}页 ---\n{text.strip()}")
        doc.close()
        if not pages:
            return "(PDF 未提取到文本内容，可能是扫描件/纯图片 PDF)"
        return "\n\n".join(pages)
    except ImportError:
        return "(服务端未安装 pymupdf，无法解析 PDF。请运行: pip install pymupdf)"
    except Exception as e:
        return f"(PDF 解析失败: {str(e)})"



def _build_human_message(text: str, images: list[str] | None = None, files: list[dict] | None = None, audios: list[dict] | None = None) -> HumanMessage:
    """构造 HumanMessage，支持图片、文件附件（文本/PDF）和音频。
    - 图片：当 LLM_VISION_SUPPORT=true 时构造 OpenAI vision 格式；否则降级提示。
    - 文本文件：将文件内容以 markdown 代码块形式拼接到消息文本中。
    - PDF 文件：
        * 视觉模式：以 file content part 直传原始 PDF + 提取文本
        * 非视觉模式：pymupdf 提取纯文本
    - 音频：以 file content part 格式传入（data URI，兼容 OpenAI 代理）
    """
    vision_supported = os.getenv("LLM_VISION_SUPPORT", "true").lower() == "true"

    # 收集需要以 file content part 传入的 PDF（视觉模式下）
    pdf_file_parts: list[dict] = []

    # 拼接文件内容到消息末尾
    file_text = ""
    if files:
        file_parts = []
        for f in files:
            fname = f.get("name", "未知文件")
            ftype = f.get("type", "text")
            fcontent = f.get("content", "")

            if ftype == "pdf":
                if vision_supported:
                    # 视觉模式：以 file content part 直传 PDF + 提取文本备用
                    pdf_text = _extract_pdf_text(fcontent)
                    if len(pdf_text) > 50000:
                        pdf_text = pdf_text[:50000] + f"\n\n... (文件过长，已截断)"
                    # 确保 data URI 格式正确
                    pdf_data_uri = fcontent if fcontent.startswith("data:") else f"data:application/pdf;base64,{fcontent}"
                    pdf_file_parts.append({
                        "type": "file",
                        "file": {
                            "filename": fname,
                            "file_data": pdf_data_uri,
                        },
                    })
                    file_parts.append(f"📄 **附件: {fname}** (已上传原始 PDF 供分析，同时附上提取的文本)\n```\n{pdf_text}\n```")
                else:
                    # 非视觉模式：仅文本
                    pdf_text = _extract_pdf_text(fcontent)
                    if len(pdf_text) > 50000:
                        pdf_text = pdf_text[:50000] + f"\n\n... (文件过长，已截断)"
                    file_parts.append(f"📄 **附件: {fname}**\n```\n{pdf_text}\n```")
            else:
                # 普通文本文件
                if len(fcontent) > 50000:
                    fcontent = fcontent[:50000] + f"\n\n... (文件过长，已截断，共 {len(f.get('content', ''))} 字符)"
                file_parts.append(f"📄 **附件: {fname}**\n```\n{fcontent}\n```")

        if file_parts:
            file_text = "\n\n" + "\n\n".join(file_parts)

    combined_text = (text or "") + file_text

    # 用户上传的图片
    all_images = list(images or [])

    # 判断是否有多模态内容（图片、PDF file parts、音频）
    has_multimodal = bool(all_images) or bool(pdf_file_parts) or bool(audios)

    if not has_multimodal:
        return HumanMessage(content=combined_text or "(空消息)")

    if not vision_supported and all_images:
        hint = f"\n\n[系统提示：你发送了{len(images or [])}张图片，但当前模型不支持图片识别，图片已忽略。请切换到支持视觉的模型（如 gemini-2.0-flash、gpt-4o）后重试。]"
        combined_text = combined_text + hint
        # 如果没有音频和 PDF file，直接返回纯文本
        if not audios and not pdf_file_parts:
            return HumanMessage(content=combined_text)
        all_images = []  # 清空图片，但继续处理音频/PDF

    # 多模态：构造 content list
    content_parts = []
    if combined_text:
        content_parts.append({"type": "text", "text": combined_text})
    elif audios:
        # 用户只发了语音没有文字，添加占位 text（API 代理要求至少有一个 text part）
        content_parts.append({"type": "text", "text": "请听取并处理以下音频："})

    # 图片：OpenAI vision 格式
    for img_data in all_images:
        content_parts.append({
            "type": "image_url",
            "image_url": {"url": img_data},
        })

    # PDF 文件：以 file content part 直传
    content_parts.extend(pdf_file_parts)

    # 音频：根据模式自动选择格式
    # 标准模式 -> type: "input_audio"，非标准模式 -> type: "file"
    if audios:
        for audio in audios:
            audio_b64 = audio.get("base64", "")
            audio_fmt = audio.get("format", "webm")
            audio_name = audio.get("name", f"recording.{audio_fmt}")
            content_parts.append(build_audio_part(audio_b64, audio_fmt, audio_name))

    return HumanMessage(content=content_parts)


# --- Routes ---

@app.get("/tools")
async def get_tools_list(x_internal_token: str | None = Header(None)):
    """返回当前 Agent 加载的所有 MCP 工具信息（需要内部 token）"""
    verify_internal_token(x_internal_token)
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
        "messages": [_build_human_message(req.text, req.images, req.files, req.audios)],
        "trigger_source": "user",
        "enabled_tools": req.enabled_tools,
        "user_id": req.user_id,
        "session_id": req.session_id,
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
        "messages": [_build_human_message(req.text, req.images, req.files, req.audios)],
        "trigger_source": "user",
        "enabled_tools": req.enabled_tools,
        "user_id": req.user_id,
        "session_id": req.session_id,
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


# ------------------------------------------------------------------
# TTS: 文本转语音
# ------------------------------------------------------------------

class TTSRequest(BaseModel):
    user_id: str
    password: str
    text: str
    voice: Optional[str] = None

@app.post("/tts")
async def text_to_speech(req: TTSRequest):
    """将文本转为语音，返回 mp3 音频流"""
    if not verify_password(req.user_id, req.password):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    tts_text = req.text.strip()
    if not tts_text:
        raise HTTPException(status_code=400, detail="文本不能为空")

    # 限制长度，避免过长文本
    if len(tts_text) > 4000:
        tts_text = tts_text[:4000]

    api_key = os.getenv("LLM_API_KEY", "")
    base_url = os.getenv("LLM_BASE_URL", "").rstrip("/")
    tts_model = os.getenv("TTS_MODEL", "gemini-2.5-flash-preview-tts")
    tts_voice = req.voice or os.getenv("TTS_VOICE", "charon")

    if not api_key or not base_url:
        raise HTTPException(status_code=500, detail="TTS API 未配置")

    tts_url = f"{base_url}/audio/speech"

    async def audio_stream():
        async with httpx.AsyncClient(timeout=60.0) as client:
            async with client.stream(
                "POST",
                tts_url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": tts_model,
                    "input": tts_text,
                    "voice": tts_voice,
                    "response_format": "mp3",
                },
            ) as resp:
                if resp.status_code != 200:
                    error_body = await resp.aread()
                    raise HTTPException(
                        status_code=resp.status_code,
                        detail=f"TTS API 错误: {error_body.decode('utf-8', errors='replace')[:200]}",
                    )
                async for chunk in resp.aiter_bytes(chunk_size=4096):
                    yield chunk

    return StreamingResponse(
        audio_stream(),
        media_type="audio/mpeg",
        headers={"Content-Disposition": "inline; filename=tts_output.mp3"},
    )


# ------------------------------------------------------------------
# Session history: 从 checkpoint DB 读取会话列表和历史消息
# ------------------------------------------------------------------

class SessionListRequest(BaseModel):
    user_id: str
    password: str

class SessionHistoryRequest(BaseModel):
    user_id: str
    password: str
    session_id: str

class DeleteSessionRequest(BaseModel):
    user_id: str
    password: str
    session_id: str = ""  # 为空则删除该用户所有会话


@app.post("/sessions")
async def list_sessions(req: SessionListRequest):
    """列出用户的所有会话，返回 session_id 列表及每个会话的摘要信息。"""
    if not verify_password(req.user_id, req.password):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    prefix = f"{req.user_id}#"
    sessions = []

    # 从 checkpoint DB 中查询该用户的所有 thread_id
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            "SELECT DISTINCT thread_id FROM checkpoints WHERE thread_id LIKE ? ORDER BY thread_id",
            (f"{prefix}%",),
        )
        rows = await cursor.fetchall()

    for (thread_id,) in rows:
        sid = thread_id[len(prefix):]

        # 获取最新 checkpoint 中的第一条和最后一条用户消息作为摘要
        config = {"configurable": {"thread_id": thread_id}}
        snapshot = await agent.agent_app.aget_state(config)
        msgs = snapshot.values.get("messages", []) if snapshot and snapshot.values else []

        # 找第一条用户消息作为标题
        first_human = ""
        last_human = ""
        msg_count = 0
        for m in msgs:
            if hasattr(m, "content") and type(m).__name__ == "HumanMessage":
                # 多模态 content 可能是 list，提取其中的文本部分
                raw = m.content
                if isinstance(raw, str):
                    content = raw
                elif isinstance(raw, list):
                    content = " ".join(
                        p.get("text", "") for p in raw if isinstance(p, dict) and p.get("type") == "text"
                    ) or "(图片消息)"
                else:
                    content = str(raw)
                # 跳过系统触发消息
                if content.startswith("[系统触发]") or content.startswith("[外部学术会议邀请]"):
                    continue
                msg_count += 1
                if not first_human:
                    first_human = content[:50]
                last_human = content[:50]

        if not first_human:
            continue  # 空会话或纯系统会话，不展示

        sessions.append({
            "session_id": sid,
            "title": first_human,
            "last_message": last_human,
            "message_count": msg_count,
        })

    return {"status": "success", "sessions": sessions}


@app.post("/session_history")
async def get_session_history(req: SessionHistoryRequest):
    """获取指定会话的完整对话历史（仅返回 Human/AI 消息）。"""
    if not verify_password(req.user_id, req.password):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    thread_id = f"{req.user_id}#{req.session_id}"
    config = {"configurable": {"thread_id": thread_id}}
    snapshot = await agent.agent_app.aget_state(config)

    if not snapshot or not snapshot.values:
        return {"status": "success", "messages": []}

    msgs = snapshot.values.get("messages", [])
    result = []
    for m in msgs:
        msg_type = type(m).__name__
        if msg_type == "HumanMessage":
            # 多模态消息 content 可能是 list（含 text+image_url），直接透传
            content = m.content
            result.append({"role": "user", "content": content})
        elif msg_type == "AIMessage":
            content = m.content if isinstance(m.content, str) else str(m.content)
            # 提取 tool_calls 信息
            tool_calls = []
            if hasattr(m, "tool_calls") and m.tool_calls:
                for tc in m.tool_calls:
                    tool_calls.append({
                        "name": tc.get("name", ""),
                        "args": tc.get("args", {}),
                    })
            if content or tool_calls:
                entry = {"role": "assistant", "content": content}
                if tool_calls:
                    entry["tool_calls"] = tool_calls
                result.append(entry)
        elif msg_type == "ToolMessage":
            content = m.content if isinstance(m.content, str) else str(m.content)
            tool_name = getattr(m, "name", "")
            result.append({
                "role": "tool",
                "content": content,
                "tool_name": tool_name,
            })

    return {"status": "success", "messages": result}


@app.post("/delete_session")
async def delete_session(req: DeleteSessionRequest):
    """删除指定会话或用户的全部会话历史。

    - session_id 非空：删除该用户的指定会话
    - session_id 为空：删除该用户的所有会话
    """
    if not verify_password(req.user_id, req.password):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    try:
        async with aiosqlite.connect(db_path) as db:
            if req.session_id:
                # 删除单个会话
                thread_id = f"{req.user_id}#{req.session_id}"
                for table in ("checkpoints", "writes"):
                    await db.execute(f"DELETE FROM {table} WHERE thread_id = ?", (thread_id,))
                await db.commit()
                # 清理内存中的 oasis 偏移量（如有）
                oasis_session_offsets.pop(thread_id, None)
                return {"status": "success", "message": f"会话 {req.session_id} 已删除"}
            else:
                # 删除该用户所有会话
                pattern = f"{req.user_id}#%"
                for table in ("checkpoints", "writes"):
                    await db.execute(f"DELETE FROM {table} WHERE thread_id LIKE ?", (pattern,))
                await db.commit()
                # 清理内存中的 oasis 偏移量
                keys_to_del = [k for k in oasis_session_offsets if k.startswith(f"{req.user_id}#")]
                for k in keys_to_del:
                    del oasis_session_offsets[k]
                return {"status": "success", "message": f"用户 {req.user_id} 的所有会话已删除"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除失败: {e}")


@app.post("/system_trigger")
async def system_trigger(req: SystemTriggerRequest, x_internal_token: str | None = Header(None)):
    verify_internal_token(x_internal_token)
    thread_id = f"{req.user_id}#{req.session_id}"
    config = {"configurable": {"thread_id": thread_id}}
    system_input = {
        "messages": [HumanMessage(content=req.text)],
        "trigger_source": "system",
        "enabled_tools": None,
        "user_id": req.user_id,
        "session_id": req.session_id,
    }
    # fire-and-forget：立刻返回，graph 在后台异步执行
    asyncio.create_task(agent.agent_app.ainvoke(system_input, config))
    return {"status": "received", "message": f"系统触发已收到，用户 {req.user_id}"}


# ------------------------------------------------------------------
# Oasis Bridge: 外部 OASIS 论坛调用 Agent 参与讨论
# ------------------------------------------------------------------

@app.post("/oasis/ask")
async def oasis_ask(req: OasisAskRequest, x_internal_token: str | None = Header(None)):
    """
    外部 OASIS 论坛调用此接口，邀请本 Agent 参与讨论。
    需要在请求头中携带 X-Internal-Token 进行鉴权。

    流程:
    1. 增量提取历史消息（只发送 Agent 还没见过的新内容）
    2. 格式化为可读文本，构造系统触发消息
    3. 调用 Agent ainvoke 等待思考完成
    4. 直接从 Agent 回复中提取内容返回给外部 OASIS

    Payload 示例:
    {
        "session_id": "oasis_abc123",
        "topic": "AI是否应该有情感？",
        "history": [
            {"role": "创意专家", "content": "我认为AI应该..."},
            {"role": "批判专家", "content": "但是风险在于..."}
        ],
        "user_id": "oasis_external"
    }
    """
    verify_internal_token(x_internal_token)
    session_id = req.session_id

    # --- 增量提取：只获取 Agent 没见过的新消息 ---
    last_idx = oasis_session_offsets.get(session_id, 0)
    new_messages = req.history[last_idx:]

    if not new_messages and last_idx > 0:
        return {"content": "我已了解当前进展，暂无补充。", "status": "skipped"}

    # 格式化新消息为可读文本
    formatted_new_input = "\n".join([
        f"[{msg.get('role', '未知专家')}]: {msg.get('content', '')}"
        for msg in new_messages
    ])

    # 更新偏移量
    oasis_session_offsets[session_id] = len(req.history)

    # --- 构造系统触发消息，通知 Agent 参与讨论 ---
    trigger_text = _oasis_trigger_tpl.format(
        topic=req.topic,
        new_input=formatted_new_input,
    ) if _oasis_trigger_tpl else (
        f"[外部学术会议邀请]\n"
        f"你被邀请参加一场 OASIS 学术讨论会议。\n"
        f"讨论主题: {req.topic}\n\n"
        f"--- 其他专家的最新发言 ---\n"
        f"{formatted_new_input}\n"
        f"--- 发言结束 ---\n\n"
        f"请认真阅读以上内容，作为专家给出你的观点和分析。"
        f"直接回复你的意见即可，不需要调用任何工具。"
    )

    # 使用独立的会话 ID 避免污染用户的正常对话
    oasis_thread_id = f"{req.user_id}#oasis_{session_id}"
    config = {"configurable": {"thread_id": oasis_thread_id}}
    system_input = {
        "messages": [HumanMessage(content=trigger_text)],
        "trigger_source": "system",
        "enabled_tools": None,
        "user_id": req.user_id,
        "session_id": f"oasis_{session_id}",
    }

    try:
        result = await asyncio.wait_for(
            agent.agent_app.ainvoke(system_input, config),
            timeout=120.0,
        )
        reply = result["messages"][-1].content
        return {"content": reply, "expert_name": "MiniTimeBot", "status": "success"}
    except asyncio.TimeoutError:
        return {
            "content": "(Agent 思考过久，未能在规定时间内回应)",
            "expert_name": "MiniTimeBot",
            "status": "timeout",
        }
    except Exception as e:
        return {
            "content": f"(Agent 处理异常: {str(e)})",
            "expert_name": "MiniTimeBot",
            "status": "error",
        }


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("PORT_AGENT", "51200")))
