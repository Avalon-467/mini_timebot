"""
OASIS Forum - Discussion Scheduler

Parses YAML schedule definitions and yields execution steps
that control the order in which experts speak.

Schedule YAML format:
  version: 1
  repeat: true          # true = 每轮重复整个 plan; false = plan 只执行一次
  plan:
    # 指定专家发言（按名称匹配）
    - expert: "批判专家"

    # 多个专家同时并行发言
    - parallel:
        - expert: "创意专家"
        - expert: "数据分析师"

    # 手动注入一条帖子（不经过 LLM）
    - manual:
        author: "主持人"
        content: "请大家聚焦到可行性方面讨论"
        reply_to: null

    # 所有专家并行（等同于不用 schedule 的默认行为）
    - all_experts: true

Execution modes:
  repeat: true  -> plan 在每轮重复执行，max_rounds 控制总轮数
  repeat: false -> plan 中的步骤顺序执行一次即结束（忽略 max_rounds）

If no schedule is provided, the engine falls back to the default
"all experts in parallel each round" behavior.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import yaml


class StepType(str, Enum):
    """Types of schedule steps."""
    EXPERT = "expert"           # Single expert speaks (sequential)
    PARALLEL = "parallel"       # Multiple experts speak in parallel
    ALL = "all_experts"         # All experts speak in parallel
    MANUAL = "manual"           # Inject a post manually (no LLM)


@dataclass
class ScheduleStep:
    """A single step in the discussion schedule."""
    step_type: StepType
    expert_names: list[str] = field(default_factory=list)   # for EXPERT / PARALLEL
    manual_author: str = ""                                  # for MANUAL
    manual_content: str = ""                                 # for MANUAL
    manual_reply_to: Optional[int] = None                    # for MANUAL


@dataclass
class Schedule:
    """Parsed schedule with steps and config."""
    steps: list[ScheduleStep]
    repeat: bool = False  # True = repeat plan each round; False = run once


def parse_schedule(yaml_content: str) -> Schedule:
    """
    Parse a YAML schedule string into a Schedule object.

    Raises ValueError on invalid format.
    """
    data = yaml.safe_load(yaml_content)
    if not isinstance(data, dict) or "plan" not in data:
        raise ValueError("Schedule YAML must contain a 'plan' key")

    plan = data["plan"]
    if not isinstance(plan, list):
        raise ValueError("'plan' must be a list of steps")

    repeat = bool(data.get("repeat", False))

    steps: list[ScheduleStep] = []
    for i, item in enumerate(plan):
        if not isinstance(item, dict):
            raise ValueError(f"Step {i}: must be a dict, got {type(item).__name__}")

        if "expert" in item:
            steps.append(ScheduleStep(
                step_type=StepType.EXPERT,
                expert_names=[str(item["expert"])],
            ))

        elif "parallel" in item:
            names = []
            for sub in item["parallel"]:
                if isinstance(sub, dict) and "expert" in sub:
                    names.append(str(sub["expert"]))
                elif isinstance(sub, str):
                    names.append(sub)
                else:
                    raise ValueError(f"Step {i}: parallel entries must have 'expert' key")
            if not names:
                raise ValueError(f"Step {i}: parallel list is empty")
            steps.append(ScheduleStep(
                step_type=StepType.PARALLEL,
                expert_names=names,
            ))

        elif "all_experts" in item:
            steps.append(ScheduleStep(step_type=StepType.ALL))

        elif "manual" in item:
            m = item["manual"]
            if not isinstance(m, dict) or "content" not in m:
                raise ValueError(f"Step {i}: manual must have 'content'")
            steps.append(ScheduleStep(
                step_type=StepType.MANUAL,
                manual_author=str(m.get("author", "主持人")),
                manual_content=str(m["content"]),
                manual_reply_to=m.get("reply_to"),
            ))

        else:
            raise ValueError(f"Step {i}: unknown step type, keys={list(item.keys())}")

    return Schedule(steps=steps, repeat=repeat)


def load_schedule_file(path: str) -> Schedule:
    """Load and parse a schedule from a YAML file path."""
    with open(path, "r", encoding="utf-8") as f:
        return parse_schedule(f.read())
