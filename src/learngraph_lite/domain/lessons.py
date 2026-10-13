"""Declarative lesson package rules.

Lesson packages intentionally allow only Markdown plus a small set of fixed
component payloads. They never carry arbitrary HTML, scripts or executable code.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class ComponentKind(StrEnum):
    CHOICE_CARD = "choice_card"
    STEPPER = "stepper"
    COMPARISON_TABLE = "comparison_table"


@dataclass(frozen=True)
class LessonComponent:
    id: str
    kind: ComponentKind
    props: dict[str, Any]


@dataclass(frozen=True)
class LessonPackage:
    id: str
    goal_id: str
    node_id: str
    graph_content_revision: int
    markdown: str
    components: tuple[LessonComponent, ...]


@dataclass(frozen=True)
class LessonEvent:
    id: str
    package_id: str
    component_id: str
    action: str
    payload: dict[str, Any]


def build_lesson_package(
    *,
    package_id: str,
    goal_id: str,
    node_id: str,
    graph_content_revision: int,
    markdown: str,
    components: tuple[LessonComponent, ...],
) -> LessonPackage:
    if "<script" in markdown.casefold() or "<iframe" in markdown.casefold():
        raise ValueError("lesson markdown cannot contain raw executable HTML")
    if not markdown.strip():
        raise ValueError("lesson markdown is required")
    ids = [component.id for component in components]
    if len(ids) != len(set(ids)):
        raise ValueError("component ids must be unique")
    for component in components:
        validate_component(component)
    return LessonPackage(
        id=package_id,
        goal_id=goal_id,
        node_id=node_id,
        graph_content_revision=graph_content_revision,
        markdown=markdown.strip(),
        components=components,
    )


def validate_component(component: LessonComponent) -> None:
    if component.kind == ComponentKind.CHOICE_CARD:
        _require_keys(component.props, {"prompt", "options"})
        options = component.props["options"]
        if not isinstance(options, list) or len(options) < 2:
            raise ValueError("choice_card needs at least two options")
        _reject_executable_fields(component.props)
        return
    if component.kind == ComponentKind.STEPPER:
        _require_keys(component.props, {"steps"})
        steps = component.props["steps"]
        if not isinstance(steps, list) or not steps:
            raise ValueError("stepper needs steps")
        _reject_executable_fields(component.props)
        return
    if component.kind == ComponentKind.COMPARISON_TABLE:
        _require_keys(component.props, {"columns", "rows"})
        rows = component.props["rows"]
        if not isinstance(rows, list) or not rows:
            raise ValueError("comparison_table needs rows")
        _reject_executable_fields(component.props)
        return
    raise ValueError(f"unsupported component kind: {component.kind}")


def ack_event(package: LessonPackage, event: LessonEvent) -> LessonEvent:
    component = next((item for item in package.components if item.id == event.component_id), None)
    if component is None:
        raise ValueError("unknown component")
    if event.action not in {"select", "complete_step", "request_explanation"}:
        raise ValueError("unsupported lesson event action")
    _reject_executable_fields(event.payload)
    return event


def _require_keys(props: dict[str, Any], keys: set[str]) -> None:
    missing = keys - props.keys()
    if missing:
        raise ValueError(f"missing component props: {', '.join(sorted(missing))}")


def _reject_executable_fields(value: Any) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            lowered = str(key).casefold()
            if lowered.startswith("on") or lowered in {"script", "html", "dangerouslysetinnerhtml"}:
                raise ValueError("component payload cannot contain executable fields")
            _reject_executable_fields(nested)
    elif isinstance(value, list):
        for nested in value:
            _reject_executable_fields(nested)
