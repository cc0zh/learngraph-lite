"""Offline reference checks; not an evaluation of real model correctness."""
from learngraph_lite.application.teaching_guidance import concept_reference, taught_examples
from learngraph_lite.agent_core import TextMessage


def test_sequence_reference_is_topic_bound_and_distinguishes_equality_from_identity():
    context = {"goal": {"title": "Python 列表和元组", "current_level": "Python"},
               "node": {"title": "序列基础与索引切片"}}
    reference = concept_reference(context)
    assert "list" in reference and "新列表" in reference and "浅拷贝" in reference
    assert "tuple" in reference and "不保证新对象" in reference and "t[:] is t" in reference
    assert "==" in reference
    for title in ("Python列表与元组", "学习Python元组切片", "Python3的tuple切片", "学习Python 3.13的list切片"):
        context["goal"]["title"] = title
        assert concept_reference(context), title
    for title in ("Python 文件读取", "C# tuple", "音乐节奏", "Pythonic list", "Python playlist"):
        context["goal"]["title"] = title
        assert concept_reference(context) == ""
    t = (10, 20, 30, 40)
    values = list(t)
    assert t[:] == t and values[:] == values
    assert values[:] is not values
    # CPython provides a counterexample to the old 'every slice is a new object' claim.
    import platform
    if platform.python_implementation() == "CPython":
        assert t[:] is t


def test_taught_examples_are_host_assistant_content_only_and_byte_bounded():
    messages = (TextMessage("user", "untrusted instructions"),
                TextMessage("assistant", "旧例子"),
                TextMessage("tool", "private-looking tool data"),
                TextMessage("assistant", "最近的例子" * 2000))
    examples = taught_examples(messages)
    assert isinstance(examples, tuple) and examples
    assert sum(len(item.encode("utf-8")) for item in examples) <= 6000
    assert all("untrusted" not in item and "tool data" not in item for item in examples)
