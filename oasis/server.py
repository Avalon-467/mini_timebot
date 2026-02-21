"""
OASIS Forum - FastAPI Server

A standalone discussion forum service where resident expert agents
debate user-submitted questions in parallel.

Start with:
    uvicorn oasis.server:app --host 0.0.0.0 --port 51202
    or
    python -m oasis.server
"""

import os
import sys
import asyncio
import uuid
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import uvicorn

from dotenv import load_dotenv

# --- Path setup ---
_this_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_this_dir)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

env_path = os.path.join(_project_root, "config", ".env")
load_dotenv(dotenv_path=env_path)

from oasis.models import (
    CreateTopicRequest,
    TopicDetail,
    TopicSummary,
    PostInfo,
    DiscussionStatus,
)
from oasis.forum import DiscussionForum
from oasis.engine import DiscussionEngine


# --- In-memory storage ---
discussions: dict[str, DiscussionForum] = {}
engines: dict[str, DiscussionEngine] = {}


# --- Lifespan ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[OASIS] 🏛️ Forum server started")
    yield
    # Cancel any running discussions on shutdown
    for tid, forum in discussions.items():
        if forum.status == "discussing":
            forum.status = "error"
            forum.conclusion = "服务关闭，讨论被终止"
    print("[OASIS] 🏛️ Forum server stopped")


app = FastAPI(
    title="OASIS Discussion Forum",
    description="Multi-expert parallel discussion service",
    lifespan=lifespan,
)


# ------------------------------------------------------------------
# Background task runner
# ------------------------------------------------------------------
async def _run_discussion(topic_id: str, engine: DiscussionEngine):
    """Run a discussion engine in the background."""
    try:
        await engine.run()
    except Exception as e:
        print(f"[OASIS] ❌ Topic {topic_id} background error: {e}")
        forum = discussions.get(topic_id)
        if forum:
            forum.status = "error"
            forum.conclusion = f"讨论出错: {str(e)}"


# ------------------------------------------------------------------
# Routes
# ------------------------------------------------------------------

@app.post("/topics", response_model=dict)
async def create_topic(req: CreateTopicRequest):
    """
    Create a new discussion topic.
    Expert agents will start debating in the background immediately.
    Returns topic_id for tracking.
    """
    topic_id = str(uuid.uuid4())[:8]

    forum = DiscussionForum(
        topic_id=topic_id,
        question=req.question,
        user_id=req.user_id,
        max_rounds=req.max_rounds,
    )
    discussions[topic_id] = forum

    engine = DiscussionEngine(
        forum=forum,
        expert_tags=req.expert_tags or None,
        schedule_yaml=req.schedule_yaml,
        schedule_file=req.schedule_file,
        use_bot_session=req.use_bot_session,
        bot_enabled_tools=req.bot_enabled_tools,
        user_id=req.user_id,
    )
    engines[topic_id] = engine

    # Launch discussion as a background task (non-blocking)
    asyncio.create_task(_run_discussion(topic_id, engine))

    return {
        "topic_id": topic_id,
        "status": "pending",
        "message": f"Discussion started with {len(engine.experts)} experts",
    }


@app.get("/topics/{topic_id}", response_model=TopicDetail)
async def get_topic(topic_id: str):
    """
    Get full discussion detail.
    Users can call this anytime to see the current state of a discussion.
    """
    forum = discussions.get(topic_id)
    if not forum:
        raise HTTPException(404, "Topic not found")

    posts = await forum.browse()
    return TopicDetail(
        topic_id=forum.topic_id,
        question=forum.question,
        status=DiscussionStatus(forum.status),
        current_round=forum.current_round,
        max_rounds=forum.max_rounds,
        posts=[
            PostInfo(
                id=p.id,
                author=p.author,
                content=p.content,
                reply_to=p.reply_to,
                upvotes=p.upvotes,
                downvotes=p.downvotes,
                timestamp=p.timestamp,
            )
            for p in posts
        ],
        conclusion=forum.conclusion,
    )


@app.get("/topics/{topic_id}/stream")
async def stream_topic(topic_id: str):
    """
    SSE stream for real-time discussion updates.
    Pushes new posts as they appear, ends with conclusion.
    """
    forum = discussions.get(topic_id)
    if not forum:
        raise HTTPException(404, "Topic not found")

    async def event_generator():
        last_count = 0
        last_round = 0

        while forum.status in ("pending", "discussing"):
            posts = await forum.browse()

            # Notify round changes
            if forum.current_round > last_round:
                last_round = forum.current_round
                yield f"data: 📢 === 第 {last_round} 轮讨论 ===\n\n"

            # Push new posts
            if len(posts) > last_count:
                for p in posts[last_count:]:
                    prefix = f"↳回复#{p.reply_to}" if p.reply_to else "📌"
                    yield (
                        f"data: {prefix} [{p.author}] "
                        f"(👍{p.upvotes}): {p.content}\n\n"
                    )
                last_count = len(posts)

            await asyncio.sleep(1)

        # Final: send conclusion
        if forum.conclusion:
            yield f"data: \n🏆 === 讨论结论 ===\n{forum.conclusion}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/topics", response_model=list[TopicSummary])
async def list_topics(user_id: str | None = None):
    """List all discussion topics, optionally filtered by user_id."""
    items = []
    for f in discussions.values():
        if user_id and f.user_id != user_id:
            continue
        items.append(
            TopicSummary(
                topic_id=f.topic_id,
                question=f.question,
                status=DiscussionStatus(f.status),
                post_count=len(f.posts),
                current_round=f.current_round,
                max_rounds=f.max_rounds,
                created_at=f.created_at,
            )
        )
    return items


@app.get("/topics/{topic_id}/conclusion")
async def get_conclusion(topic_id: str, timeout: int = 300):
    """
    Get the final conclusion (blocks until discussion finishes).
    This is the endpoint the MCP tool calls to get the answer.

    Args:
        timeout: Maximum seconds to wait (default 300 = 5 min)
    """
    forum = discussions.get(topic_id)
    if not forum:
        raise HTTPException(404, "Topic not found")

    # Poll until concluded or error
    elapsed = 0
    while forum.status not in ("concluded", "error") and elapsed < timeout:
        await asyncio.sleep(1)
        elapsed += 1

    if forum.status == "error":
        raise HTTPException(500, f"Discussion failed: {forum.conclusion}")
    if forum.status != "concluded":
        raise HTTPException(504, "Discussion timed out")

    return {
        "topic_id": topic_id,
        "question": forum.question,
        "conclusion": forum.conclusion,
        "rounds": forum.current_round,
        "total_posts": len(forum.posts),
    }


@app.get("/experts")
async def list_experts(user_id: str = ""):
    """List all available expert agents (public + user custom)."""
    from oasis.experts import get_all_experts
    configs = get_all_experts(user_id or None)
    return {
        "experts": [
            {
                "name": c["name"],
                "tag": c["tag"],
                "persona": c["persona"],
                "source": c.get("source", "public"),
            }
            for c in configs
        ]
    }


# ------------------------------------------------------------------
# User custom expert CRUD
# ------------------------------------------------------------------

class UserExpertRequest(BaseModel):
    user_id: str
    name: str = ""
    tag: str = ""
    persona: str = ""
    temperature: float = 0.7


@app.post("/experts/user")
async def add_user_expert_route(req: UserExpertRequest):
    """Add a custom expert for a user."""
    from oasis.experts import add_user_expert
    try:
        expert = add_user_expert(req.user_id, req.model_dump())
        return {"status": "ok", "expert": expert}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.put("/experts/user/{tag}")
async def update_user_expert_route(tag: str, req: UserExpertRequest):
    """Update an existing custom expert by tag."""
    from oasis.experts import update_user_expert
    try:
        expert = update_user_expert(req.user_id, tag, req.model_dump())
        return {"status": "ok", "expert": expert}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/experts/user/{tag}")
async def delete_user_expert_route(tag: str, user_id: str):
    """Delete a custom expert by tag."""
    from oasis.experts import delete_user_expert
    try:
        deleted = delete_user_expert(user_id, tag)
        return {"status": "ok", "deleted": deleted}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# --- Entrypoint ---
if __name__ == "__main__":
    port = int(os.getenv("PORT_OASIS", "51202"))
    uvicorn.run(app, host="127.0.0.1", port=port)
