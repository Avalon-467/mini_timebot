"""
OASIS Forum - Expert Agent definitions

Each expert has a distinct persona and participates in forum discussions
by reading others' posts, publishing their own views, and voting.
"""

import json
import os
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage

from oasis.forum import DiscussionForum


# --- 加载 prompt 和专家配置（模块级别，导入时执行一次） ---
_prompts_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "prompts")

# 加载专家配置
_experts_json_path = os.path.join(_prompts_dir, "oasis_experts.json")
try:
    with open(_experts_json_path, "r", encoding="utf-8") as f:
        EXPERT_CONFIGS = json.load(f)
    print(f"[prompts] ✅ oasis 已加载 oasis_experts.json ({len(EXPERT_CONFIGS)} 位专家)")
except FileNotFoundError:
    print(f"[prompts] ⚠️ 未找到 {_experts_json_path}，使用内置默认配置")
    EXPERT_CONFIGS = [
        {"name": "创意专家", "tag": "creative", "persona": "你是一个乐观的创新者，善于发现机遇和非常规解决方案。你喜欢挑战传统观念，提出大胆且具有前瞻性的想法。", "temperature": 0.9},
        {"name": "批判专家", "tag": "critical", "persona": "你是一个严谨的批判性思考者，善于发现风险、漏洞和逻辑谬误。你会指出方案中的潜在问题，确保讨论不会忽视重要细节。", "temperature": 0.3},
        {"name": "数据分析师", "tag": "data", "persona": "你是一个数据驱动的分析师，只相信数据和事实。你用数字、案例和逻辑推导来支撑你的观点。", "temperature": 0.5},
        {"name": "综合顾问", "tag": "synthesis", "persona": "你善于综合不同观点，寻找平衡方案，关注实际可操作性。你会识别各方共识，提出兼顾多方利益的务实建议。", "temperature": 0.5},
    ]

# 加载讨论 prompt 模板
_discuss_tpl_path = os.path.join(_prompts_dir, "oasis_expert_discuss.txt")
try:
    with open(_discuss_tpl_path, "r", encoding="utf-8") as f:
        _DISCUSS_PROMPT_TPL = f.read().strip()
    print("[prompts] ✅ oasis 已加载 oasis_expert_discuss.txt")
except FileNotFoundError:
    print(f"[prompts] ⚠️ 未找到 {_discuss_tpl_path}，使用内置默认模板")
    _DISCUSS_PROMPT_TPL = ""


def _get_llm(temperature: float = 0.7) -> ChatOpenAI:
    """Create an LLM instance (reuses the same env config as main agent)."""
    api_key = os.getenv("LLM_API_KEY")
    if not api_key:
        raise ValueError("LLM_API_KEY not found in environment variables.")
    return ChatOpenAI(
        model=os.getenv("LLM_MODEL", "deepseek-chat"),
        base_url=os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1"),
        api_key=api_key,
        temperature=temperature,
        max_tokens=1024,
        timeout=60,
        max_retries=2,
    )


class ExpertAgent:
    """
    A forum-resident expert agent.
    
    Each round it: reads others' posts -> forms opinion -> publishes -> votes.
    """

    def __init__(self, name: str, persona: str, temperature: float = 0.7):
        self.name = name
        self.persona = persona
        self.llm = _get_llm(temperature)

    async def participate(self, forum: DiscussionForum):
        """
        Participate in one round of discussion:
        1. Browse other experts' posts
        2. Think and compose a response
        3. Publish the post (optionally as a reply)
        4. Vote on others' posts
        """
        others = await forum.browse(viewer=self.name, exclude_self=True)
        posts_text = self._format_posts(others) if others else "(还没有其他人发言，你来开启讨论吧)"

        if _DISCUSS_PROMPT_TPL:
            prompt = _DISCUSS_PROMPT_TPL.format(
                expert_name=self.name,
                persona=self.persona,
                question=forum.question,
                posts_text=posts_text,
            )
        else:
            prompt = (
                f"你是论坛专家「{self.name}」。{self.persona}\n\n"
                f"讨论主题: {forum.question}\n\n"
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

        try:
            resp = await self.llm.ainvoke([HumanMessage(content=prompt)])
            raw = resp.content.strip()
            # Strip possible markdown code fences
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1]
            if raw.endswith("```"):
                raw = raw.rsplit("```", 1)[0]
            raw = raw.strip()

            result = json.loads(raw)

            # 后处理：如果论坛已有帖子但 LLM 返回 reply_to=null，自动推断回复对象
            reply_to = result.get("reply_to")
            if reply_to is None and others:
                # 选择最近一个其他人的帖子作为回复对象
                reply_to = others[-1].id
                print(f"  [OASIS] 🔧 {self.name} reply_to 为 null，自动设为 #{reply_to}")

            # Publish the post
            await forum.publish(
                author=self.name,
                content=result.get("content", "（发言内容为空）"),
                reply_to=reply_to,
            )

            # Vote on others' posts
            for v in result.get("votes", []):
                pid = v.get("post_id")
                direction = v.get("direction", "up")
                if pid is not None and direction in ("up", "down"):
                    await forum.vote(self.name, int(pid), direction)

            print(f"  [OASIS] ✅ {self.name} 发言完成")

        except json.JSONDecodeError as e:
            print(f"  [OASIS] ⚠️ {self.name} JSON parse error: {e}")
            # Still publish a raw post if JSON parsing fails
            try:
                raw_content = resp.content.strip()[:300]
                await forum.publish(author=self.name, content=raw_content)
            except Exception:
                pass
        except Exception as e:
            print(f"  [OASIS] ❌ {self.name} error: {e}")

    def _format_posts(self, posts) -> str:
        """Format posts for display in the prompt."""
        lines = []
        for p in posts:
            prefix = f"  ↳ 回复#{p.reply_to}" if p.reply_to else "📌"
            lines.append(
                f"{prefix} [#{p.id}] {p.author} "
                f"(👍{p.upvotes} 👎{p.downvotes}): {p.content}"
            )
        return "\n".join(lines)
