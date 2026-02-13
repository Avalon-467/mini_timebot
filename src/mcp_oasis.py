"""
MCP Tool Server: OASIS Forum

Exposes tools for the user's Agent to interact with the OASIS discussion forum:
  - post_to_oasis: Submit a question and wait for expert discussion conclusion
  - check_oasis_discussion: Check the current state of a discussion
  - list_oasis_topics: List all discussion topics

Runs as a stdio MCP server, just like the other mcp_*.py tools.
"""

import os
import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("OASIS Forum")

OASIS_BASE_URL = os.getenv("OASIS_BASE_URL", "http://127.0.0.1:51202")


@mcp.tool()
async def post_to_oasis(question: str, max_rounds: int = 5) -> str:
    """
    Submit a question to the OASIS forum for multi-expert discussion.
    Expert agents will debate the question in parallel, vote on each other's posts,
    and produce a comprehensive conclusion.
    
    Use this tool for complex questions that benefit from multiple perspectives,
    such as strategy analysis, pros/cons evaluation, or controversial topics.

    Args:
        question: The question or topic to discuss
        max_rounds: Maximum number of discussion rounds (1-20, default 5)
    
    Returns:
        The final conclusion summarizing the expert discussion
    """
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout=300.0)) as client:
            # Step 1: Create topic
            resp = await client.post(
                f"{OASIS_BASE_URL}/topics",
                json={
                    "question": question,
                    "user_id": "agent_user",
                    "max_rounds": max_rounds,
                },
            )
            if resp.status_code != 200:
                return f"❌ Failed to create topic: {resp.text}"

            topic_id = resp.json()["topic_id"]

            # Step 2: Wait for conclusion (blocking)
            result = await client.get(
                f"{OASIS_BASE_URL}/topics/{topic_id}/conclusion",
                params={"timeout": 280},
            )

            if result.status_code == 200:
                data = result.json()
                return (
                    f"🏛️ OASIS 论坛讨论完成\n"
                    f"主题: {data['question']}\n"
                    f"讨论轮次: {data['rounds']}\n"
                    f"总帖子数: {data['total_posts']}\n\n"
                    f"📋 结论:\n{data['conclusion']}\n\n"
                    f"💡 如需查看完整讨论过程，Topic ID: {topic_id}"
                )
            elif result.status_code == 504:
                return f"⏰ 讨论超时未完成 (Topic ID: {topic_id})，可稍后通过 check_oasis_discussion 查看结果"
            else:
                return f"❌ 获取结论失败: {result.text}"

    except httpx.ConnectError:
        return "❌ 无法连接 OASIS 论坛服务器。请确认 OASIS 服务已启动 (端口 51202)。"
    except Exception as e:
        return f"❌ 工具调用异常: {str(e)}"


@mcp.tool()
async def check_oasis_discussion(topic_id: str) -> str:
    """
    Check the current status of a discussion on the OASIS forum.
    Shows the discussion progress, recent posts, and conclusion if available.

    Args:
        topic_id: The topic ID returned by post_to_oasis

    Returns:
        Formatted discussion status and recent posts
    """
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(f"{OASIS_BASE_URL}/topics/{topic_id}")

            if resp.status_code == 404:
                return f"❌ 未找到讨论主题: {topic_id}"
            if resp.status_code != 200:
                return f"❌ 查询失败: {resp.text}"

            data = resp.json()

            lines = [
                f"🏛️ OASIS 讨论详情",
                f"主题: {data['question']}",
                f"状态: {data['status']} ({data['current_round']}/{data['max_rounds']}轮)",
                f"帖子数: {len(data['posts'])}",
                "",
                "--- 最近帖子 ---",
            ]

            # Show last 10 posts
            for p in data["posts"][-10:]:
                prefix = f"  ↳回复#{p['reply_to']}" if p.get("reply_to") else "📌"
                content_preview = p["content"][:150]
                if len(p["content"]) > 150:
                    content_preview += "..."
                lines.append(
                    f"{prefix} [#{p['id']}] {p['author']} "
                    f"(👍{p['upvotes']} 👎{p['downvotes']}): {content_preview}"
                )

            if data.get("conclusion"):
                lines.extend(["", "🏆 === 最终结论 ===", data["conclusion"]])
            elif data["status"] == "discussing":
                lines.extend(["", "⏳ 讨论进行中..."])

            return "\n".join(lines)

    except httpx.ConnectError:
        return "❌ 无法连接 OASIS 论坛服务器。请确认 OASIS 服务已启动 (端口 51202)。"
    except Exception as e:
        return f"❌ 查询异常: {str(e)}"


@mcp.tool()
async def list_oasis_topics(user_id: str = "") -> str:
    """
    List all discussion topics on the OASIS forum.

    Args:
        user_id: Optional filter by user ID. Leave empty to list all.
    
    Returns:
        Formatted list of all discussion topics
    """
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            params = {}
            if user_id:
                params["user_id"] = user_id
            resp = await client.get(f"{OASIS_BASE_URL}/topics", params=params)

            if resp.status_code != 200:
                return f"❌ 查询失败: {resp.text}"

            topics = resp.json()
            if not topics:
                return "📭 论坛暂无讨论主题"

            lines = [f"🏛️ OASIS 论坛 - 共 {len(topics)} 个主题\n"]
            for t in topics:
                status_icon = {
                    "pending": "⏳",
                    "discussing": "💬",
                    "concluded": "✅",
                    "error": "❌",
                }.get(t["status"], "❓")
                lines.append(
                    f"{status_icon} [{t['topic_id']}] {t['question'][:50]} "
                    f"| {t['status']} | {t['post_count']}帖 | {t['current_round']}/{t['max_rounds']}轮"
                )

            return "\n".join(lines)

    except httpx.ConnectError:
        return "❌ 无法连接 OASIS 论坛服务器。请确认 OASIS 服务已启动 (端口 51202)。"
    except Exception as e:
        return f"❌ 查询异常: {str(e)}"


if __name__ == "__main__":
    mcp.run(transport="stdio")
