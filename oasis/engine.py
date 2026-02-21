"""
OASIS Forum - Discussion Engine

Manages the full lifecycle of a discussion:
  Round loop -> scheduled/parallel expert participation -> consensus check -> summarize

Supports two modes:
  1. Default: all experts participate in parallel each round (original behavior)
  2. Scheduled: follow a YAML schedule that defines speaking order per step
"""

import asyncio
import os

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage

from oasis.forum import DiscussionForum
from oasis.experts import ExpertAgent, BotSessionExpert, EXPERT_CONFIGS, get_all_experts
from oasis.scheduler import Schedule, ScheduleStep, StepType, parse_schedule, load_schedule_file

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
    base_url = os.getenv("LLM_BASE_URL", "https://api.deepseek.com").strip()
    # ChatOpenAI 需要 /v1 路径
    openai_base = base_url.rstrip("/") + "/v1"
    return ChatOpenAI(
        model=os.getenv("LLM_MODEL", "deepseek-chat"),
        base_url=openai_base,
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
      1. If schedule is provided, execute steps in defined order
      2. Otherwise, all selected experts participate in parallel each round
      3. After each round, check if consensus is reached
      4. When done (consensus or max rounds), summarize top posts into conclusion
    """

    def __init__(
        self,
        forum: DiscussionForum,
        expert_tags: list[str] | None = None,
        schedule: Schedule | None = None,
        schedule_yaml: str | None = None,
        schedule_file: str | None = None,
        use_bot_session: bool = False,
        bot_base_url: str | None = None,
        bot_enabled_tools: list[str] | None = None,
        user_id: str = "anonymous",
    ):
        self.forum = forum
        self.use_bot_session = use_bot_session

        # Merge public + user custom experts, then filter by tag
        all_configs = get_all_experts(user_id)
        configs = all_configs
        if expert_tags:
            configs = [c for c in all_configs if c["tag"] in expert_tags]
        if not configs:
            configs = all_configs  # Fallback: use all if no match

        if use_bot_session:
            # Backend 2: each expert = a bot session owned by the requesting user
            self.experts: list[ExpertAgent | BotSessionExpert] = [
                BotSessionExpert(
                    name=c["name"],
                    persona=c["persona"],
                    topic_id=forum.topic_id,
                    user_id=user_id,
                    temperature=c["temperature"],
                    bot_base_url=bot_base_url,
                    enabled_tools=bot_enabled_tools,
                )
                for c in configs
            ]
        else:
            # Backend 1: direct LLM (original)
            self.experts = [
                ExpertAgent(
                    name=c["name"],
                    persona=c["persona"],
                    temperature=c["temperature"],
                )
                for c in configs
            ]

        # Build name -> Expert lookup
        self._expert_map: dict[str, ExpertAgent | BotSessionExpert] = {
            e.name: e for e in self.experts
        }

        self.summarizer = _get_summarizer()

        # Load schedule (priority: direct object > yaml string > file path)
        self.schedule: Schedule | None = None
        if schedule:
            self.schedule = schedule
        elif schedule_yaml:
            self.schedule = parse_schedule(schedule_yaml)
        elif schedule_file:
            self.schedule = load_schedule_file(schedule_file)

    def _resolve_experts(self, names: list[str]) -> list[ExpertAgent]:
        """Resolve expert names to ExpertAgent objects. Skip unknown names."""
        resolved = []
        for name in names:
            agent = self._expert_map.get(name)
            if agent:
                resolved.append(agent)
            else:
                print(f"  [OASIS] ⚠️ Schedule references unknown expert: '{name}', skipping")
        return resolved

    async def run(self):
        """Run the full discussion loop (called as a background task)."""
        self.forum.status = "discussing"

        backend = "bot_session" if self.use_bot_session else "direct_llm"
        mode = "scheduled" if self.schedule else "parallel"
        print(
            f"[OASIS] 🏛️ Discussion started: {self.forum.topic_id} "
            f"({len(self.experts)} experts, max {self.forum.max_rounds} rounds, "
            f"mode={mode}, backend={backend})"
        )

        try:
            if self.schedule:
                await self._run_scheduled()
            else:
                await self._run_parallel()

            # Generate final conclusion
            self.forum.conclusion = await self._summarize()
            self.forum.status = "concluded"
            print(f"[OASIS] ✅ Discussion concluded: {self.forum.topic_id}")

        except Exception as e:
            print(f"[OASIS] ❌ Discussion error: {e}")
            self.forum.status = "error"
            self.forum.conclusion = f"讨论过程中出现错误: {str(e)}"

    async def _run_parallel(self):
        """Original behavior: all experts in parallel each round."""
        for round_num in range(self.forum.max_rounds):
            self.forum.current_round = round_num + 1
            print(f"[OASIS] 📢 Round {self.forum.current_round}/{self.forum.max_rounds}")

            await asyncio.gather(
                *[expert.participate(self.forum) for expert in self.experts],
                return_exceptions=True,
            )

            if round_num >= 1 and await self._consensus_reached():
                print(f"[OASIS] 🤝 Consensus reached at round {self.forum.current_round}")
                break

    async def _run_scheduled(self):
        """
        Execute the schedule.

        Two modes controlled by schedule.repeat:
          repeat=true  -> Each round executes the full plan, up to max_rounds.
          repeat=false -> All steps execute once sequentially; each step = 1 round.
        """
        steps = self.schedule.steps

        if self.schedule.repeat:
            # ── repeat mode: plan 每轮重复 ──
            for round_num in range(self.forum.max_rounds):
                self.forum.current_round = round_num + 1
                print(f"[OASIS] 📢 Round {self.forum.current_round}/{self.forum.max_rounds}")

                for step in steps:
                    await self._execute_step(step)

                if round_num >= 1 and await self._consensus_reached():
                    print(f"[OASIS] 🤝 Consensus reached at round {self.forum.current_round}")
                    break
        else:
            # ── once mode: 步骤顺序执行一次，每步算一轮 ──
            for step_idx, step in enumerate(steps):
                self.forum.current_round = step_idx + 1
                self.forum.max_rounds = len(steps)  # 让前端显示正确的总轮数
                print(f"[OASIS] 📢 Step {step_idx + 1}/{len(steps)}")

                await self._execute_step(step)

                if step_idx >= 1 and await self._consensus_reached():
                    print(f"[OASIS] 🤝 Consensus reached at step {step_idx + 1}")
                    break

    async def _execute_step(self, step: ScheduleStep):
        """Execute a single schedule step."""
        if step.step_type == StepType.MANUAL:
            print(f"  [OASIS] 📝 Manual post by {step.manual_author}")
            await self.forum.publish(
                author=step.manual_author,
                content=step.manual_content,
                reply_to=step.manual_reply_to,
            )

        elif step.step_type == StepType.ALL:
            print(f"  [OASIS] 👥 All experts speak")
            await asyncio.gather(
                *[expert.participate(self.forum) for expert in self.experts],
                return_exceptions=True,
            )

        elif step.step_type == StepType.EXPERT:
            agents = self._resolve_experts(step.expert_names)
            if agents:
                print(f"  [OASIS] 🎤 {agents[0].name} speaks")
                await agents[0].participate(self.forum)

        elif step.step_type == StepType.PARALLEL:
            agents = self._resolve_experts(step.expert_names)
            if agents:
                names = ", ".join(a.name for a in agents)
                print(f"  [OASIS] 🎤 Parallel: {names}")
                await asyncio.gather(
                    *[agent.participate(self.forum) for agent in agents],
                    return_exceptions=True,
                )

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
