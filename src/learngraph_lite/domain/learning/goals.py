"""Pure goal drafting and confirmation rules."""

from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class GoalDraft:
    title: str
    desired_outcome: str = ""
    current_level: str = ""
    time_budget_minutes: int | None = None
    constraints: str = ""
    document_ids: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    confirmed: bool = False
    skipped_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class ClarificationQuestion:
    field: str
    question: str


def build_goal_draft(title: str, **fields: object) -> GoalDraft:
    assumptions: list[str] = []
    current_level = str(fields.get("current_level") or "").strip()
    desired_outcome = str(fields.get("desired_outcome") or "").strip()
    time_budget = fields.get("time_budget_minutes")
    skipped = fields.get("skipped_fields", ())
    labels = {"desired_outcome": "期望成果", "current_level": "当前基础", "time_budget_minutes": "时间预算"}
    if (not isinstance(skipped, (tuple, list)) or any(type(name) is not str or name not in labels for name in skipped)
            or len(set(skipped)) != len(skipped)):
        raise ValueError("skipped_fields must contain unique supported goal fields")
    supplied = {"desired_outcome": bool(desired_outcome), "current_level": bool(current_level),
                "time_budget_minutes": time_budget is not None}
    skipped = tuple(name for name in skipped if not supplied[name])
    for name in skipped:
        assumptions.append(f"用户已主动跳过{labels[name]}，保留跳过记录；未提供的信息仍未确定。")
    if not current_level:
        assumptions.append("未说明当前基础，不假设已具备相关能力；从入门与基础验证开始规划。")
    else:
        assumptions.append("当前基础来自用户自述，尚未验证；不能当作已验证能力，需要通过实践或测验确认。")
    if not desired_outcome:
        assumptions.append("未说明期望成果，默认以理解核心概念、完成适合主题的练习并解释结果为通用学习目标。")
    if time_budget is None:
        assumptions.append("未说明时间预算，仅用总投入 240 分钟作为规划参考；时间预算字段仍为空，不代表用户承诺或日历周期。")
    return GoalDraft(
        title=title.strip(),
        desired_outcome=desired_outcome.strip(),
        current_level=current_level.strip(),
        time_budget_minutes=int(time_budget) if time_budget is not None else None,
        constraints=str(fields.get("constraints") or "").strip(),
        document_ids=tuple(str(item) for item in fields.get("document_ids", ()) or ()),
        assumptions=tuple(assumptions),
        skipped_fields=tuple(skipped),
    )


def clarification_questions(draft: GoalDraft, round_index: int) -> tuple[ClarificationQuestion, ...]:
    if round_index >= 2:
        return ()
    questions: list[ClarificationQuestion] = []
    if not draft.desired_outcome and "desired_outcome" not in draft.skipped_fields:
        questions.append(ClarificationQuestion("desired_outcome", "希望完成后能做出或解释什么？"))
    if not draft.current_level and "current_level" not in draft.skipped_fields:
        questions.append(ClarificationQuestion("current_level", "你目前的基础到什么程度？"))
    if draft.time_budget_minutes is None and "time_budget_minutes" not in draft.skipped_fields:
        questions.append(ClarificationQuestion("time_budget_minutes", "这次学习大约可投入多少分钟？"))
    return tuple(questions[:3])


def confirm_goal(draft: GoalDraft) -> GoalDraft:
    if not draft.title:
        raise ValueError("goal title is required")
    if draft.time_budget_minutes is not None and draft.time_budget_minutes <= 0:
        raise ValueError("time budget must be positive")
    return replace(draft, confirmed=True)
