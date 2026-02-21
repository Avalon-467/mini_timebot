"""
OASIS Forum - Expert Agent definitions

Two expert backends:
  1. ExpertAgent  — direct LLM call (stateless, single-shot, original behavior)
  2. BotSessionExpert — calls mini_timebot's own /v1/chat/completions endpoint,
     each expert gets an isolated temporary session with full tool-calling ability.
     Sessions are created on demand and cleaned up after the discussion ends.

Each expert participates in forum discussions by reading others' posts,
publishing their own views, and voting.
"""

import json
import os
import sys

import httpx
from langchain_core.messages import HumanMessage

# 确保 src/ 在 import 路径中，以便导入 llm_factory
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))
from llm_factory import create_chat_model, extract_text

from oasis.forum import DiscussionForum


# --- 加载 prompt 和专家配置（模块级别，导入时执行一次） ---
_data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
_prompts_dir = os.path.join(_data_dir, "prompts")

# 加载公共专家配置
_experts_json_path = os.path.join(_prompts_dir, "oasis_experts.json")
try:
    with open(_experts_json_path, "r", encoding="utf-8") as f:
        EXPERT_CONFIGS: list[dict] = json.load(f)
    print(f"[prompts] ✅ oasis 已加载 oasis_experts.json ({len(EXPERT_CONFIGS)} 位公共专家)")
except FileNotFoundError:
    print(f"[prompts] ⚠️ 未找到 {_experts_json_path}，使用内置默认配置")
    EXPERT_CONFIGS = [
        {"name": "创意专家", "tag": "creative", "persona": "你是一个乐观的创新者，善于发现机遇和非常规解决方案。你喜欢挑战传统观念，提出大胆且具有前瞻性的想法。", "temperature": 0.9},
        {"name": "批判专家", "tag": "critical", "persona": "你是一个严谨的批判性思考者，善于发现风险、漏洞和逻辑谬误。你会指出方案中的潜在问题，确保讨论不会忽视重要细节。", "temperature": 0.3},
        {"name": "数据分析师", "tag": "data", "persona": "你是一个数据驱动的分析师，只相信数据和事实。你用数字、案例和逻辑推导来支撑你的观点。", "temperature": 0.5},
        {"name": "综合顾问", "tag": "synthesis", "persona": "你善于综合不同观点，寻找平衡方案，关注实际可操作性。你会识别各方共识，提出兼顾多方利益的务实建议。", "temperature": 0.5},
    ]


# ======================================================================
# Per-user custom expert storage
# ======================================================================
_USER_EXPERTS_DIR = os.path.join(_data_dir, "oasis_user_experts")
os.makedirs(_USER_EXPERTS_DIR, exist_ok=True)


def _user_experts_path(user_id: str) -> str:
    """Return the JSON file path for a user's custom experts."""
    safe = user_id.replace("/", "_").replace("\\", "_").replace("..", "_")
    return os.path.join(_USER_EXPERTS_DIR, f"{safe}.json")


def load_user_experts(user_id: str) -> list[dict]:
    """Load a user's custom expert list (returns [] if none)."""
    path = _user_experts_path(user_id)
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def _save_user_experts(user_id: str, experts: list[dict]) -> None:
    with open(_user_experts_path(user_id), "w", encoding="utf-8") as f:
        json.dump(experts, f, ensure_ascii=False, indent=2)


def _validate_expert(data: dict) -> dict:
    """Validate and normalize an expert config dict. Raises ValueError on bad input."""
    name = data.get("name", "").strip()
    tag = data.get("tag", "").strip()
    persona = data.get("persona", "").strip()
    if not name:
        raise ValueError("专家 name 不能为空")
    if not tag:
        raise ValueError("专家 tag 不能为空")
    if not persona:
        raise ValueError("专家 persona 不能为空")
    return {
        "name": name,
        "tag": tag,
        "persona": persona,
        "temperature": float(data.get("temperature", 0.7)),
    }


def add_user_expert(user_id: str, data: dict) -> dict:
    """Add a custom expert for a user. Returns the normalized expert dict."""
    expert = _validate_expert(data)
    experts = load_user_experts(user_id)
    # Prevent duplicate tag within user's list
    if any(e["tag"] == expert["tag"] for e in experts):
        raise ValueError(f"用户已有 tag=\"{expert['tag']}\" 的专家，请换一个 tag 或使用更新功能")
    # Prevent clash with global expert tags
    if any(e["tag"] == expert["tag"] for e in EXPERT_CONFIGS):
        raise ValueError(f"tag=\"{expert['tag']}\" 与公共专家冲突，请换一个 tag")
    experts.append(expert)
    _save_user_experts(user_id, experts)
    return expert


def update_user_expert(user_id: str, tag: str, data: dict) -> dict:
    """Update an existing custom expert by tag. Returns the updated dict."""
    experts = load_user_experts(user_id)
    for i, e in enumerate(experts):
        if e["tag"] == tag:
            updated = _validate_expert({**e, **data, "tag": tag})  # tag immutable
            experts[i] = updated
            _save_user_experts(user_id, experts)
            return updated
    raise ValueError(f"未找到用户自定义专家 tag=\"{tag}\"")


def delete_user_expert(user_id: str, tag: str) -> dict:
    """Delete a custom expert by tag. Returns the deleted dict."""
    experts = load_user_experts(user_id)
    for i, e in enumerate(experts):
        if e["tag"] == tag:
            deleted = experts.pop(i)
            _save_user_experts(user_id, experts)
            return deleted
    raise ValueError(f"未找到用户自定义专家 tag=\"{tag}\"")


def get_all_experts(user_id: str | None = None) -> list[dict]:
    """Return public experts + user's custom experts (marked with source)."""
    result = [
        {**c, "source": "public"} for c in EXPERT_CONFIGS
    ]
    if user_id:
        result.extend(
            {**c, "source": "custom"} for c in load_user_experts(user_id)
        )
    return result

# 加载讨论 prompt 模板
_discuss_tpl_path = os.path.join(_prompts_dir, "oasis_expert_discuss.txt")
try:
    with open(_discuss_tpl_path, "r", encoding="utf-8") as f:
        _DISCUSS_PROMPT_TPL = f.read().strip()
    print("[prompts] ✅ oasis 已加载 oasis_expert_discuss.txt")
except FileNotFoundError:
    print(f"[prompts] ⚠️ 未找到 {_discuss_tpl_path}，使用内置默认模板")
    _DISCUSS_PROMPT_TPL = ""


def _get_llm(temperature: float = 0.7):
    """Create an LLM instance (reuses the same env config & vendor routing as main agent)."""
    return create_chat_model(temperature=temperature, max_tokens=1024)


# ======================================================================
# Helper: build discussion prompt (shared by both backends)
# ======================================================================

def _build_discuss_prompt(
    expert_name: str,
    persona: str,
    question: str,
    posts_text: str,
) -> str:
    """Build the prompt that asks the expert to respond with JSON."""
    if _DISCUSS_PROMPT_TPL:
        return _DISCUSS_PROMPT_TPL.format(
            expert_name=expert_name,
            persona=persona,
            question=question,
            posts_text=posts_text,
        )
    return (
        f"你是论坛专家「{expert_name}」。{persona}\n\n"
        f"讨论主题: {question}\n\n"
        f"当前论坛内容:\n{posts_text}\n\n"
        "请以严格的 JSON 格式回复（不要包含 markdown 代码块标记，不要包含注释）:\n"
        "{\n"
        '  "reply_to": 2,\n'
        '  "content": "你的观点（200字以内，观点鲜明）",\n'
        '  "votes": [\n'
        '    {"post_id": 1, "direction": "up"}\n'
        "  ]\n"
        "}\n\n"
        "说明:\n"
        "- reply_to: 如果论坛中已有其他人的帖子，你**必须**选择一个帖子ID进行回复；只有在论坛为空时才填 null\n"
        "- content: 你的发言内容，要有独到见解，可以赞同、反驳或补充你所回复的帖子\n"
        '- votes: 对其他帖子的投票列表，direction 只能是 "up" 或 "down"。如果没有要投票的帖子，填空列表 []\n'
    )


def _format_posts(posts) -> str:
    """Format posts for display in the prompt."""
    lines = []
    for p in posts:
        prefix = f"  ↳ 回复#{p.reply_to}" if p.reply_to else "📌"
        lines.append(
            f"{prefix} [#{p.id}] {p.author} "
            f"(👍{p.upvotes} 👎{p.downvotes}): {p.content}"
        )
    return "\n".join(lines)


def _parse_expert_response(raw: str):
    """Strip markdown fences and parse JSON. Returns dict or None."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
    if raw.endswith("```"):
        raw = raw.rsplit("```", 1)[0]
    raw = raw.strip()
    return json.loads(raw)


async def _apply_response(
    result: dict,
    expert_name: str,
    forum: DiscussionForum,
    others: list,
):
    """Apply the parsed JSON response: publish post + cast votes."""
    reply_to = result.get("reply_to")
    if reply_to is None and others:
        reply_to = others[-1].id
        print(f"  [OASIS] 🔧 {expert_name} reply_to 为 null，自动设为 #{reply_to}")

    await forum.publish(
        author=expert_name,
        content=result.get("content", "（发言内容为空）"),
        reply_to=reply_to,
    )

    for v in result.get("votes", []):
        pid = v.get("post_id")
        direction = v.get("direction", "up")
        if pid is not None and direction in ("up", "down"):
            await forum.vote(expert_name, int(pid), direction)

    print(f"  [OASIS] ✅ {expert_name} 发言完成")


# ======================================================================
# Backend 1: ExpertAgent — direct LLM call (original, stateless)
# ======================================================================

class ExpertAgent:
    """
    A forum-resident expert agent (direct LLM backend).

    Each call is stateless: reads posts → single LLM call → publish + vote.
    """

    def __init__(self, name: str, persona: str, temperature: float = 0.7):
        self.name = name
        self.persona = persona
        self.llm = _get_llm(temperature)

    async def participate(self, forum: DiscussionForum):
        others = await forum.browse(viewer=self.name, exclude_self=True)
        posts_text = _format_posts(others) if others else "(还没有其他人发言，你来开启讨论吧)"
        prompt = _build_discuss_prompt(self.name, self.persona, forum.question, posts_text)

        try:
            resp = await self.llm.ainvoke([HumanMessage(content=prompt)])
            text = extract_text(resp.content)
            result = _parse_expert_response(text)
            await _apply_response(result, self.name, forum, others)
        except json.JSONDecodeError as e:
            print(f"  [OASIS] ⚠️ {self.name} JSON parse error: {e}")
            try:
                await forum.publish(author=self.name, content=extract_text(resp.content).strip()[:300])
            except Exception:
                pass
        except Exception as e:
            print(f"  [OASIS] ❌ {self.name} error: {e}")


# ======================================================================
# Backend 2: BotSessionExpert — calls mini_timebot /v1/chat/completions
# ======================================================================

class BotSessionExpert:
    """
    Expert backed by a mini_timebot session.

    Each expert gets a unique session_id derived from the topic_id, **owned by
    the requesting user** (thread_id = ``{user_id}#oasis_{topic_id}_{expert}``).
    This means the expert's conversation history is visible in the user's
    session list and is **not** auto-deleted after the discussion — the user
    can revisit or continue chatting with any expert later.

    Authentication uses ``INTERNAL_TOKEN:<user_id>`` (admin-level), so no
    user password is needed — OASIS acts as a trusted internal service.

    **Incremental context**: To avoid O(N²) token blowup, only NEW posts
    (since the last `participate` call) are sent each round.  The session's
    own history already contains earlier posts, so the LLM still has the
    full picture.
    """

    def __init__(
        self,
        name: str,
        persona: str,
        topic_id: str,
        user_id: str,
        temperature: float = 0.7,
        bot_base_url: str | None = None,
        enabled_tools: list[str] | None = None,
    ):
        self.name = name
        self.persona = persona
        self.topic_id = topic_id
        self.temperature = temperature

        port = os.getenv("PORT_AGENT", "51200")
        self._bot_url = (bot_base_url or f"http://127.0.0.1:{port}") + "/v1/chat/completions"

        # Auth: INTERNAL_TOKEN:<user_id> — admin-level, session owned by user
        self._user_id = user_id
        self._internal_token = os.getenv("INTERNAL_TOKEN", "")

        # Unique session_id per expert per topic
        safe_name = name.replace(" ", "_")
        self.session_id = f"oasis_{topic_id}_{safe_name}"

        self.enabled_tools = enabled_tools
        self._initialized = False
        self._seen_post_ids: set[int] = set()  # Track which posts we've already sent

    def _auth_header(self) -> dict:
        """Build auth header as INTERNAL_TOKEN:user_id (admin-level, no password needed)."""
        return {"Authorization": f"Bearer {self._internal_token}:{self._user_id}"}

    async def participate(self, forum: DiscussionForum):
        """
        Participate in one round of discussion via bot session.

        First call sends full context + persona instruction.
        Subsequent calls send only NEW posts (incremental delta).
        The bot session's checkpoint history retains earlier context.
        """
        others = await forum.browse(viewer=self.name, exclude_self=True)

        # Split into already-seen vs new posts
        new_posts = [p for p in others if p.id not in self._seen_post_ids]
        self._seen_post_ids.update(p.id for p in others)

        # Build OpenAI-compatible request
        messages = []
        if not self._initialized:
            # ── First round: full context ──
            posts_text = _format_posts(others) if others else "(还没有其他人发言，你来开启讨论吧)"
            prompt = _build_discuss_prompt(self.name, self.persona, forum.question, posts_text)

            messages.append({
                "role": "system",
                "content": (
                    f"你是论坛专家「{self.name}」。{self.persona}\n"
                    "在接下来的讨论中，你将收到论坛的新增内容，需要以 JSON 格式回复你的观点和投票。\n"
                    "你拥有工具调用能力，如需搜索资料、分析数据来支撑你的观点，可以使用可用的工具。\n"
                    "注意：后续轮次只会发送新增帖子，之前的帖子请参考你的对话记忆。"
                ),
            })
            messages.append({"role": "user", "content": prompt})
            self._initialized = True
        else:
            # ── Subsequent rounds: incremental delta only ──
            if new_posts:
                new_text = _format_posts(new_posts)
                prompt = (
                    f"【第 {forum.current_round} 轮讨论更新】\n"
                    f"以下是自你上次发言后的 {len(new_posts)} 条新帖子：\n\n"
                    f"{new_text}\n\n"
                    "请基于这些新观点以及你之前看到的讨论内容，以 JSON 格式回复：\n"
                    "{\n"
                    '  "reply_to": <某个帖子ID>,\n'
                    '  "content": "你的观点（200字以内）",\n'
                    '  "votes": [{"post_id": <ID>, "direction": "up或down"}]\n'
                    "}"
                )
            else:
                prompt = (
                    f"【第 {forum.current_round} 轮讨论更新】\n"
                    "本轮没有新的帖子。如果你有新的想法或补充，可以继续发言；"
                    "如果没有，回复一个空 content 即可。\n"
                    "{\n"
                    '  "reply_to": null,\n'
                    '  "content": "",\n'
                    '  "votes": []\n'
                    "}"
                )
            messages.append({"role": "user", "content": prompt})

        body: dict = {
            "model": "mini-timebot",
            "messages": messages,
            "stream": False,
            "session_id": self.session_id,
        }
        if self.enabled_tools is not None:
            body["enabled_tools"] = self.enabled_tools

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(timeout=120.0)) as client:
                resp = await client.post(
                    self._bot_url,
                    json=body,
                    headers=self._auth_header(),
                )

            if resp.status_code != 200:
                print(f"  [OASIS] ❌ {self.name} bot API error {resp.status_code}: {resp.text[:200]}")
                return

            data = resp.json()
            raw_content = data["choices"][0]["message"]["content"]
            result = _parse_expert_response(raw_content)
            await _apply_response(result, self.name, forum, others)

        except json.JSONDecodeError as e:
            print(f"  [OASIS] ⚠️ {self.name} JSON parse error: {e}")
            try:
                await forum.publish(author=self.name, content=raw_content.strip()[:300])
            except Exception:
                pass
        except Exception as e:
            print(f"  [OASIS] ❌ {self.name} error: {e}")


