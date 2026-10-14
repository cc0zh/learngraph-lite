"""Conservative context accounting; remove old user turns as complete groups."""

import json
from dataclasses import asdict

from .budget import BudgetExceeded
from .models import TextMessage


def fit_context(messages: tuple[TextMessage, ...], tools: tuple[dict, ...], limit: int) -> tuple[TextMessage, ...]:
    # UTF-8 bytes / 3 is an estimate, not a provider tokenizer. Keep a safety margin.
    def estimate(items):
        value = json.dumps([asdict(m) for m in items], ensure_ascii=False) + json.dumps(tools, ensure_ascii=False)
        return (len(value.encode("utf-8")) + 2) // 3

    result = list(messages)
    while estimate(result) > limit:
        users = [i for i, m in enumerate(result) if m.role == "user"]
        # First user is required business context; last is the current task.
        if len(users) <= 2:
            raise BudgetExceeded("context budget exhausted")
        del result[users[1]:users[2]]
    return tuple(result)
