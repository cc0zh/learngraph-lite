"""Small, host-authored teaching references and bounded worked-example context."""
from __future__ import annotations

import re

from learngraph_lite.agent_core import TextMessage


def concept_reference(context: dict) -> str:
    topic = " ".join(str(section.get(key, "")) for section, keys in (
        (context.get("goal", {}), ("title", "desired_outcome")),
        (context.get("node", {}), ("title", "learning_outcome", "explanation")),
    ) for key in keys)
    python_topic = re.search(r"(?<![A-Za-z0-9_])python(?:\s*3(?:\.\d+)*)?(?![A-Za-z0-9_])", topic, re.I)
    sequence_topic = re.search(r"元组|列表|(?<![A-Za-z0-9_])(?:tuple|list)(?![A-Za-z0-9_])", topic, re.I)
    if not python_topic or not sequence_topic:
        return ""
    # Python reference: https://docs.python.org/3/library/stdtypes.html#immutable-sequence-types
    return ("Python 内置序列参考：list 切片产生新列表，是浅拷贝，嵌套可变对象仍可能共享。"
            "tuple 切片不保证新对象；普通 tuple 的完整切片 t[:] is t 在 CPython 中可为 True，"
            "不要宣称所有切片都复制对象，也不要许诺所有 Python 实现都复用身份。"
            "内容比较使用 ==，is 只比较身份。元组不可变是浅层约束，元素中的列表仍可修改。")


def taught_examples(messages: tuple[TextMessage, ...]) -> tuple[str, ...]:
    """Most recent assistant text only; never tool payloads or private generator replies."""
    remaining = 6000
    examples = []
    for message in reversed(messages):
        if message.role != "assistant" or not message.content:
            continue
        text = message.content.encode("utf-8")[-remaining:].decode("utf-8", errors="ignore")
        if text:
            examples.append(text)
            remaining -= len(text.encode("utf-8"))
        if remaining < 4:
            break
    return tuple(reversed(examples))
