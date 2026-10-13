"""Declarative lesson package rules.

Lesson packages intentionally allow only Markdown plus a small set of fixed
component payloads. They never carry arbitrary HTML, scripts or executable code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import re
from typing import Any


class ComponentKind(StrEnum):
    MARKDOWN = "markdown"
    QUIZ_CHOICE = "quiz_choice"
    # Read-only compatibility for persisted offline prototype packages.
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
    schema_version: int = 1
    version: int = 1
    title: str = "学习页"
    source_mode: str = "general"
    citation_ids: tuple[str, ...] = ()
    citation_map: dict[str, dict] = field(default_factory=dict)


@dataclass(frozen=True)
class LessonEvent:
    id: str
    package_id: str
    component_id: str
    action: str
    payload: dict[str, Any]
    package_version: int = 1


def build_lesson_package(
    *,
    package_id: str,
    goal_id: str,
    node_id: str,
    graph_content_revision: int,
    markdown: str,
    components: tuple[LessonComponent, ...],
    schema_version: int = 1,
    version: int = 1,
    title: str = "学习页",
    source_mode: str = "general",
    citation_ids: tuple[str, ...] = (),
    citation_map: dict[str, dict] | None = None,
) -> LessonPackage:
    _text(markdown, 16000)
    _text(title, 200)
    if schema_version != 1 or type(version) is not int or version < 1:
        raise ValueError("unsupported lesson schema or version")
    if type(graph_content_revision) is not int or graph_content_revision < 1:
        raise ValueError("invalid content revision")
    if len(components) > 19:
        raise ValueError("lesson supports at most 20 blocks including the chapter")
    ids = [component.id for component in components]
    if len(ids) != len(set(ids)) or "chapter" in ids:
        raise ValueError("component ids must be unique")
    for component in components:
        validate_component(component)
    citation_map = citation_map or {}
    used = set(citation_ids)
    texts = [title, markdown, *(str(component.props) for component in components)]
    mentioned = set(re.findall(r"\[(C[0-9]+)\]", "\n".join(texts)))
    if len(used) != len(citation_ids) or not used.issubset(citation_map) or not mentioned.issubset(used):
        raise ValueError("invalid lesson citation ids")
    if source_mode not in {"general", "documents"} or (source_mode == "documents" and not used):
        raise ValueError("invalid lesson source mode")
    if source_mode == "general" and (used or citation_map):
        raise ValueError("general lessons cannot contain document citations")
    return LessonPackage(
        id=package_id,
        goal_id=goal_id,
        node_id=node_id,
        graph_content_revision=graph_content_revision,
        markdown=markdown.strip(),
        components=components,
        schema_version=schema_version, version=version, title=title,
        source_mode=source_mode, citation_ids=citation_ids, citation_map=citation_map,
    )


def validate_component(component: LessonComponent) -> None:
    _text(component.id, 128)
    _reject_executable_fields(component.props)
    if component.kind == ComponentKind.MARKDOWN:
        _require_keys(component.props, {"text"})
        _text(component.props["text"], 4000)
        return
    if component.kind == ComponentKind.QUIZ_CHOICE:
        _require_keys(component.props, {"exercise_id"})
        _text(component.props["exercise_id"], 128)
        return
    if component.kind == ComponentKind.STEPPER:
        _require_keys(component.props, {"steps"})
        steps = component.props["steps"]
        if not isinstance(steps, list) or not 1 <= len(steps) <= 12:
            raise ValueError("stepper needs 1 to 12 steps")
        for step in steps:
            if not isinstance(step, dict):
                raise ValueError("step must contain title, description and fixed slots")
            _require_keys(step, {"title", "description", "slots"})
            _text(step["title"], 200)
            _text(step["description"], 2000)
            if not isinstance(step["slots"], dict) or set(step["slots"]) - {"text"}:
                raise ValueError("step supports only the fixed text slot")
            for value in step["slots"].values():
                _text(value, 2000)
        return
    if component.kind == ComponentKind.COMPARISON_TABLE:
        _require_keys(component.props, {"columns", "rows"})
        columns, rows = component.props["columns"], component.props["rows"]
        if not isinstance(columns, list) or not 1 <= len(columns) <= 6:
            raise ValueError("comparison_table needs 1 to 6 columns")
        if not isinstance(rows, list) or not 1 <= len(rows) <= 20:
            raise ValueError("comparison_table needs 1 to 20 rows")
        for column in columns:
            _text(column, 200)
        for row in rows:
            if not isinstance(row, list) or len(row) != len(columns):
                raise ValueError("table row width must match columns")
            for cell in row:
                _text(cell, 2000)
        return
    raise ValueError(f"unsupported component kind: {component.kind}")


def ack_event(package: LessonPackage, event: LessonEvent) -> LessonEvent:
    if event.package_id != package.id or event.package_version != package.version or package.schema_version != 1:
        raise ValueError("lesson version does not match")
    if event.component_id == "chapter":
        component = LessonComponent("chapter", ComponentKind.MARKDOWN, {"text": package.markdown})
    else:
        component = next((item for item in package.components if item.id == event.component_id), None)
    if component is None:
        raise ValueError("unknown component")
    _reject_executable_fields(event.payload)
    if event.action == "request_explanation":
        _require_keys(event.payload, set())
    elif event.action == "mark_read" and component.kind == ComponentKind.MARKDOWN:
        _require_keys(event.payload, set())
    elif event.action == "step_changed" and component.kind == ComponentKind.STEPPER:
        _require_keys(event.payload, {"step"})
        step = event.payload["step"]
        if type(step) is not int or not 0 <= step < len(component.props["steps"]):
            raise ValueError("step is outside the component")
    else:
        raise ValueError("unsupported lesson event action for this component")
    return event


def _require_keys(props: dict[str, Any], keys: set[str]) -> None:
    missing = keys - props.keys()
    if missing:
        raise ValueError(f"missing component props: {', '.join(sorted(missing))}")
    if props.keys() - keys:
        raise ValueError("unknown component or event fields")


def _text(value: Any, limit: int) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError("lesson text is missing or exceeds its limit")
    if re.search(r"<\s*[!/?a-zA-Z]|(?:javascript|vbscript|data)\s*:", value, re.IGNORECASE):
        raise ValueError("lesson text cannot contain executable HTML or dangerous URLs")


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
