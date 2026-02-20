"""
OASIS Forum - Discussion Engine

Manages the full lifecycle of a discussion:
  Round loop -> parallel expert participation -> consensus check -> summarize
"""

import asyncio
import os

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage

from oasis.forum import DiscussionForum
from oasis.experts import ExpertAgent, EXPERT_CONFIGS

# 加载总结 prompt 模板（模块级别，导入时执行一次）
_prompts_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "prompts")
_summary_tpl_path = os.path.join(_prompts_dir, "oasis_summary.txt")
try:
    with open(_summary_tpl_path, "r", encoding="utf-8") as f:
        _SUMMARY_PROMPT_TPL = f.read().strip()
    print("[prompts] ✅ oasis 已加载 oasis_summary.txt")
except FileNotFoundError:
    print(f"[prompts] ⚠️ 未找到 {_summary_tpl_path}，使用内置默认模板")
    _SUMMARY_PROMPT_TPL = ""


def _get_summarizer() -> ChatOpenAI:
    """Create a low-temperature LLM for reliable summarization."""
    api_key = os.getenv("LLM_API_KEY")
    if not api_key:
        raise ValueError("LLM_API_KEY not found in environment variables.")
    return ChatOpenAI(
        model=os.getenv("LLM_MODEL", "deepseek-chat"),
        base_url=os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1"),
        api_key=api_key,
        temperature=0.3,
        max_tokens=2048,
        timeout=60,
        max_retries=2,
    )


class DiscussionEngine:
    """
    Orchestrates one complete discussion session.
    
    Flow:
      1. For each round, all selected experts participate in parallel
      2. After each round, check if consensus is reached
      3. When done (consensus or max rounds), summarize top posts into conclusion
    """

    def __init__(self, forum: DiscussionForum, expert_tags: list[str] | None = None):
        self.forum = forum

        # Filter experts by tag; empty/None = all participate
        configs = EXPERT_CONFIGS
        if expert_tags:
            configs = [c for c in configs if c["tag"] in expert_tags]
        if not configs:
            configs = EXPERT_CONFIGS  # Fallback: use all if no match

        self.experts = [
            ExpertAgent(
                name=c["name"],
                persona=c["persona"],
                temperature=c["temperature"],
            )
            for c in configs
        ]
        self.summarizer = _get_summarizer()

    async def run(self):
        """Run the full discussion loop (called as a background task)."""
        self.forum.status = "discussing"
        print(
            f"[OASIS] 🏛️ Discussion started: {self.forum.topic_id} "
            f"({len(self.experts)} experts, max {self.forum.max_rounds} rounds)"
        )

        try:
            for round_num in range(self.forum.max_rounds):
                self.forum.current_round = round_num + 1
                print(f"[OASIS] 📢 Round {self.forum.current_round}/{self.forum.max_rounds}")

                # All experts participate in parallel
                await asyncio.gather(
                    *[expert.participate(self.forum) for expert in self.experts],
                    return_exceptions=True,
                )

                # Check consensus after round 2+
                if round_num >= 1 and await self._consensus_reached():
                    print(f"[OASIS] 🤝 Consensus reached at round {self.forum.current_round}")
                    break

            # Generate final conclusion
            self.forum.conclusion = await self._summarize()
            self.forum.status = "concluded"
            print(f"[OASIS] ✅ Discussion concluded: {self.forum.topic_id}")

        except Exception as e:
            print(f"[OASIS] ❌ Discussion error: {e}")
            self.forum.status = "error"
            self.forum.conclusion = f"讨论过程中出现错误: {str(e)}"

    async def _consensus_reached(self) -> bool:
        """Check if the top post has enough agreement to stop early."""
        top = await self.forum.get_top_posts(1)
        if not top:
            return False
        # Consensus = top post has >= 70% upvotes from all experts
        threshold = len(self.experts) * 0.7
        return top[0].upvotes >= threshold

    async def _summarize(self) -> str:
        """Summarize the top-voted posts into a final conclusion."""
        top_posts = await self.forum.get_top_posts(5)
        all_posts = await self.forum.browse()

        if not top_posts:
            return "讨论未产生有效观点。"

        posts_text = "\n".join([
            f"[👍{p.upvotes} 👎{p.downvotes}] {p.author}: {p.content}"
            for p in top_posts
        ])

        if _SUMMARY_PROMPT_TPL:
            prompt = _SUMMARY_PROMPT_TPL.format(
                question=self.forum.question,
                post_count=len(all_posts),
                round_count=self.forum.current_round,
                posts_text=posts_text,
            )
        else:
            prompt = (
                f"你是一个讨论总结专家。以下是关于「{self.forum.question}」的多专家讨论结果。\n\n"
                f"共 {len(all_posts)} 条帖子，经过 {self.forum.current_round} 轮讨论。\n\n"
                f"获得最高认可的观点:\n{posts_text}\n\n"
                "请综合以上高赞观点，给出一个全面、平衡、有结论性的最终回答（300字以内）。\n"
                "要求:\n"
                "1. 清晰概括各方核心观点\n"
                "2. 指出主要共识和分歧\n"
                "3. 给出明确的结论性建议\n"
            )

        try:
            resp = await self.summarizer.ainvoke([HumanMessage(content=prompt)])
            return resp.content
        except Exception as e:
            return f"总结生成失败: {str(e)}"
