"""
MCP Tool Server: OASIS Forum

Exposes tools for the user's Agent to interact with the OASIS discussion forum:
  - list_oasis_experts: List all available expert agents (public + user custom)
  - add_oasis_expert: Create a custom expert for the user
  - update_oasis_expert: Update a custom expert
  - delete_oasis_expert: Delete a custom expert
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
_FALLBACK_USER = os.getenv("MCP_OASIS_USER", "agent_user")

_CONN_ERR = "❌ 无法连接 OASIS 论坛服务器。请确认 OASIS 服务已启动 (端口 51202)。"


# ======================================================================
# Expert management tools
# ======================================================================

@mcp.tool()
async def list_oasis_experts(username: str = "") -> str:
    """
    List all available expert agents on the OASIS forum.
    Shows both public (built-in) experts and the current user's custom experts.
    Call this BEFORE post_to_oasis to see which experts can participate.

    Args:
        username: (auto-injected) current user identity; do NOT set manually

    Returns:
        Formatted list of experts with their tags, personas, and source (public/custom)
    """
    effective_user = username or _FALLBACK_USER
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{OASIS_BASE_URL}/experts",
                params={"user_id": effective_user},
            )
            if resp.status_code != 200:
                return f"❌ 查询失败: {resp.text}"

            experts = resp.json().get("experts", [])
            if not experts:
                return "📭 暂无可用专家"

            public = [e for e in experts if e.get("source") == "public"]
            custom = [e for e in experts if e.get("source") == "custom"]

            lines = [f"🏛️ OASIS 可用专家 - 共 {len(experts)} 位\n"]

            if public:
                lines.append(f"📋 公共专家 ({len(public)} 位):")
                for e in public:
                    persona_preview = e["persona"][:60] + "..." if len(e["persona"]) > 60 else e["persona"]
                    lines.append(f"  • {e['name']} (tag: \"{e['tag']}\") — {persona_preview}")

            if custom:
                lines.append(f"\n🔧 自定义专家 ({len(custom)} 位):")
                for e in custom:
                    persona_preview = e["persona"][:60] + "..." if len(e["persona"]) > 60 else e["persona"]
                    lines.append(f"  • {e['name']} (tag: \"{e['tag']}\") — {persona_preview}")

            lines.append(
                "\n💡 用 expert_tags 选专家参与讨论，用 schedule_yaml 控制发言顺序。"
                "\n   用 add_oasis_expert 创建自定义专家。"
            )
            return "\n".join(lines)

    except httpx.ConnectError:
        return _CONN_ERR
    except Exception as e:
        return f"❌ 查询异常: {str(e)}"


@mcp.tool()
async def add_oasis_expert(
    username: str,
    name: str,
    tag: str,
    persona: str,
    temperature: float = 0.7,
) -> str:
    """
    Create a custom expert for the current user.
    The expert will appear alongside public experts in list_oasis_experts
    and can be selected via expert_tags in post_to_oasis.

    Args:
        username: (auto-injected) current user identity; do NOT set manually
        name: Expert display name (e.g. "产品经理", "前端架构师")
        tag: Unique identifier tag (e.g. "pm", "frontend_arch"). Must not conflict with existing tags.
        persona: Expert persona description — defines how the expert thinks and speaks
        temperature: LLM temperature (0.0-1.0, default 0.7). Lower = more deterministic.

    Returns:
        Confirmation with the created expert info
    """
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{OASIS_BASE_URL}/experts/user",
                json={
                    "user_id": username,
                    "name": name,
                    "tag": tag,
                    "persona": persona,
                    "temperature": temperature,
                },
            )
            if resp.status_code != 200:
                return f"❌ 创建失败: {resp.json().get('detail', resp.text)}"

            expert = resp.json()["expert"]
            return (
                f"✅ 自定义专家已创建\n"
                f"  名称: {expert['name']}\n"
                f"  Tag: {expert['tag']}\n"
                f"  Persona: {expert['persona']}\n"
                f"  Temperature: {expert['temperature']}"
            )

    except httpx.ConnectError:
        return _CONN_ERR
    except Exception as e:
        return f"❌ 创建异常: {str(e)}"


@mcp.tool()
async def update_oasis_expert(
    username: str,
    tag: str,
    name: str = "",
    persona: str = "",
    temperature: float = -1,
) -> str:
    """
    Update an existing custom expert. Only user-created experts can be updated (not public ones).

    Args:
        username: (auto-injected) current user identity; do NOT set manually
        tag: The tag of the custom expert to update (immutable, used as identifier)
        name: New display name (leave empty to keep current)
        persona: New persona description (leave empty to keep current)
        temperature: New temperature (-1 = keep current)

    Returns:
        Confirmation with the updated expert info
    """
    try:
        body: dict = {"user_id": username}
        if name:
            body["name"] = name
        if persona:
            body["persona"] = persona
        if temperature >= 0:
            body["temperature"] = temperature

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.put(
                f"{OASIS_BASE_URL}/experts/user/{tag}",
                json=body,
            )
            if resp.status_code != 200:
                return f"❌ 更新失败: {resp.json().get('detail', resp.text)}"

            expert = resp.json()["expert"]
            return (
                f"✅ 自定义专家已更新\n"
                f"  名称: {expert['name']}\n"
                f"  Tag: {expert['tag']}\n"
                f"  Persona: {expert['persona']}\n"
                f"  Temperature: {expert['temperature']}"
            )

    except httpx.ConnectError:
        return _CONN_ERR
    except Exception as e:
        return f"❌ 更新异常: {str(e)}"


@mcp.tool()
async def delete_oasis_expert(username: str, tag: str) -> str:
    """
    Delete a custom expert. Only user-created experts can be deleted (not public ones).

    Args:
        username: (auto-injected) current user identity; do NOT set manually
        tag: The tag of the custom expert to delete

    Returns:
        Confirmation of deletion
    """
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.delete(
                f"{OASIS_BASE_URL}/experts/user/{tag}",
                params={"user_id": username},
            )
            if resp.status_code != 200:
                return f"❌ 删除失败: {resp.json().get('detail', resp.text)}"

            deleted = resp.json()["deleted"]
            return f"✅ 已删除自定义专家: {deleted['name']} (tag: \"{deleted['tag']}\")"

    except httpx.ConnectError:
        return _CONN_ERR
    except Exception as e:
        return f"❌ 删除异常: {str(e)}"


# ======================================================================
# Discussion tools
# ======================================================================

@mcp.tool()
async def post_to_oasis(
    question: str,
    username: str = "",
    expert_tags: list[str] = [],
    max_rounds: int = 5,
    schedule_yaml: str = "",
    schedule_file: str = "",
    use_bot_session: bool = False,
    detach: bool = False,
) -> str:
    """
    Submit a question or work task to the OASIS forum for multi-expert collaboration.

    Two modes of operation:
    1. **Discussion mode** (default, use_bot_session=False): Expert agents debate the question
       with lightweight stateless LLM calls, vote on each other's posts, and produce a conclusion.
       Best for: strategy analysis, pros/cons evaluation, controversial topics.
    2. **Bot sub-agent mode** (use_bot_session=True): Experts run as stateful sub-agents with
       tool-calling ability and memory across rounds. The `question` field serves as the **work task**
       assigned to the sub-agents. The `schedule_yaml` defines not only speaking order but also
       the **work execution order**. Best for: complex task flows requiring multi-agent collaboration.

    **Workflow**: call list_oasis_experts first to see available experts (including custom ones),
    then use expert_tags and schedule_yaml to control who participates and in what order.

    Args:
        question: The question/topic to discuss, or the work task to assign to sub-agents (in bot session mode)
        username: (auto-injected) current user identity; do NOT set manually
        expert_tags: List of expert tags to include (e.g. ["creative", "critical", "my_custom_tag"]).
            Empty list = all experts (public + custom) participate.
        max_rounds: Maximum number of discussion rounds (1-20, default 5)
        schedule_yaml: Inline YAML to control speaking order per round.
            If omitted, all selected experts speak in parallel each round.
            Format:
              version: 1
              repeat: true
              plan:
                - expert: "创意专家"
                - expert: "批判专家"
                - parallel:
                    - "数据分析师"
                    - "经济学家"
                - all_experts: true
            Step types:
              - expert: single expert speaks (use expert NAME, not tag)
              - parallel: multiple experts speak simultaneously (use NAMEs)
              - all_experts: all selected experts speak
            repeat: true = repeat the plan each round; false = execute plan steps once across rounds
            Note: in bot sub-agent mode, the plan defines the work execution order, not just speaking order
        schedule_file: Path to a YAML schedule file (alternative to schedule_yaml)
        use_bot_session: If True, experts run as full bot sub-agents (stateful, with tool-calling
            ability and memory across rounds). The question becomes a work task assigned to sub-agents,
            and schedule_yaml defines the work execution order. Default False uses lightweight stateless LLM calls.
        detach: If True, submit the task and return immediately with the topic_id without waiting
            for the discussion/task to complete. Use check_oasis_discussion later to check progress
            and retrieve the conclusion. Default False waits for the full conclusion.

    Returns:
        The final conclusion summarizing the expert discussion, or (if detach=True) the topic_id for later retrieval
    """
    effective_user = username or _FALLBACK_USER
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout=300.0)) as client:
            body = {
                "question": question,
                "user_id": effective_user,
                "max_rounds": max_rounds,
            }
            if expert_tags:
                body["expert_tags"] = expert_tags
            if schedule_yaml:
                body["schedule_yaml"] = schedule_yaml
            if schedule_file:
                body["schedule_file"] = schedule_file
            if use_bot_session:
                body["use_bot_session"] = True

            resp = await client.post(
                f"{OASIS_BASE_URL}/topics",
                json=body,
            )
            if resp.status_code != 200:
                return f"❌ Failed to create topic: {resp.text}"

            topic_id = resp.json()["topic_id"]

            if detach:
                return (
                    f"🏛️ OASIS 任务已提交（脱离模式）\n"
                    f"主题: {question[:80]}\n"
                    f"Topic ID: {topic_id}\n\n"
                    f"💡 讨论/任务将在后台运行，稍后使用 check_oasis_discussion(topic_id=\"{topic_id}\") 查看进展和结论。"
                )

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
        return _CONN_ERR
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
        return _CONN_ERR
    except Exception as e:
        return f"❌ 查询异常: {str(e)}"


@mcp.tool()
async def dispatch_subagent(
    task: str,
    username: str = "",
    enabled_tools: list[str] = [],
    notify_session: str = "default",
) -> str:
    """
    Quickly dispatch a single sub-agent to complete a task in the background.

    This is a lightweight shortcut that creates a one-expert OASIS session running as
    a bot sub-agent. The task is submitted in **detach mode** — it returns immediately
    and the sub-agent works autonomously. When done, the main agent receives a
    system_trigger notification in the specified session with the conclusion.

    Use this when:
      - You want to offload a time-consuming task (research, data processing, etc.)
      - The task can be described in a single prompt
      - You don't need multi-expert debate, just one capable agent with tools

    Args:
        task: The work task description for the sub-agent (be specific and detailed)
        username: (auto-injected) current user identity; do NOT set manually
        enabled_tools: Optional tool whitelist for the sub-agent. Empty = all tools available.
        notify_session: (auto-injected) Session ID where the main agent should receive the
            completion notification. Defaults to current session. Override to route
            notifications to a different session (e.g. for cross-session workflows).

    Returns:
        Confirmation with topic_id for tracking progress
    """
    effective_user = username or _FALLBACK_USER
    port = os.getenv("PORT_AGENT", "51200")
    callback_url = f"http://127.0.0.1:{port}/system_trigger"

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout=30.0)) as client:
            body = {
                "question": task,
                "user_id": effective_user,
                "max_rounds": 1,
                "expert_tags": [],
                "use_bot_session": True,
                "callback_url": callback_url,
                "callback_session_id": notify_session,
                # Single anonymous agent — no preset persona, identity comes from the task
                "expert_configs": [
                    {
                        "name": "子Agent",
                        "tag": "_dispatch",
                        "persona": "",
                        "temperature": 0.7,
                    }
                ],
            }
            if enabled_tools:
                body["bot_enabled_tools"] = enabled_tools

            # Use a minimal single-expert schedule: one "all_experts" step
            # OASIS will use whatever experts are available; with max_rounds=1
            # and a single round, it's effectively a single-shot sub-agent.

            resp = await client.post(
                f"{OASIS_BASE_URL}/topics",
                json=body,
            )
            if resp.status_code != 200:
                return f"❌ 子 Agent 创建失败: {resp.text}"

            topic_id = resp.json()["topic_id"]

            return (
                f"🚀 子 Agent 已派遣（后台运行中）\n"
                f"任务: {task[:100]}\n"
                f"Topic ID: {topic_id}\n"
                f"完成后将自动通知会话: {notify_session}\n\n"
                f"💡 可用 check_oasis_discussion(topic_id=\"{topic_id}\") 查看进展。"
            )

    except httpx.ConnectError:
        return _CONN_ERR
    except Exception as e:
        return f"❌ 派遣失败: {str(e)}"


@mcp.tool()
async def list_oasis_topics(username: str = "") -> str:
    """
    List all discussion topics on the OASIS forum.

    Args:
        username: (auto-injected) current user identity; leave empty to list all.

    Returns:
        Formatted list of all discussion topics
    """
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            params = {}
            if username:
                params["user_id"] = username
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
        return _CONN_ERR
    except Exception as e:
        return f"❌ 查询异常: {str(e)}"


if __name__ == "__main__":
    mcp.run(transport="stdio")
