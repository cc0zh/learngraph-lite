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


@dataclass(frozen=True)
class ClarificationQuestion:
    field: str
    question: str


def build_goal_draft(title: str, **fields: object) -> GoalDraft:
    assumptions: list[str] = []
    current_level = str(fields.get("current_level") or "")
    desired_outcome = str(fields.get("desired_outcome") or "")
    time_budget = fields.get("time_budget_minutes")
    if not current_level:
        assumptions.append("未说明当前水平，默认按有基础但未系统实践处理。")
    if not desired_outcome:
        assumptions.append("未说明期望产出，默认以能做出可解释的小型项目为目标。")
    if time_budget is None:
        assumptions.append("未说明时间预算，默认按四周学习计划拆分。")
    return GoalDraft(
        title=title.strip(),
        desired_outcome=desired_outcome.strip(),
        current_level=current_level.strip(),
        time_budget_minutes=int(time_budget) if time_budget is not None else None,
        constraints=str(fields.get("constraints") or "").strip(),
        document_ids=tuple(str(item) for item in fields.get("document_ids", ()) or ()),
        assumptions=tuple(assumptions),
    )


def clarification_questions(draft: GoalDraft, round_index: int) -> tuple[ClarificationQuestion, ...]:
    if round_index >= 2:
        return ()
    questions: list[ClarificationQuestion] = []
    if not draft.desired_outcome:
        questions.append(ClarificationQuestion("desired_outcome", "希望完成后能做出或解释什么？"))
    if not draft.current_level:
        questions.append(ClarificationQuestion("current_level", "你目前的基础到什么程度？"))
    if draft.time_budget_minutes is None:
        questions.append(ClarificationQuestion("time_budget_minutes", "这次学习大约可投入多少分钟？"))
    return tuple(questions[:3])


def confirm_goal(draft: GoalDraft) -> GoalDraft:
    if not draft.title:
        raise ValueError("goal title is required")
    if draft.time_budget_minutes is not None and draft.time_budget_minutes <= 0:
        raise ValueError("time budget must be positive")
    return replace(draft, confirmed=True)
