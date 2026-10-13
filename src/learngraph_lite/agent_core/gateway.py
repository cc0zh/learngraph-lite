"""One budget and usage ledger for all model calls in an execution."""

from __future__ import annotations

from .budget import Budget
from .models import ModelGateway, ModelResponse, TextMessage


class BudgetedModelGateway:
    def __init__(self, model: ModelGateway, budget: Budget):
        self._model = model
        self.budget = budget
        self.usage = budget.usage

    def complete(self, messages: tuple[TextMessage, ...], tools: tuple[dict, ...]) -> ModelResponse:
        self.budget.take_model_call()
        response = self._model.complete(messages, tools)
        for key, value in response.usage.items():
            self.usage[key] = self.usage.get(key, 0) + value
        self.budget.check_step(0)
        return response


def budgeted(model: ModelGateway, budget: Budget) -> BudgetedModelGateway:
    if isinstance(model, BudgetedModelGateway):
        if model.budget is not budget:
            raise ValueError("a budgeted gateway cannot switch execution budgets")
        return model
    return BudgetedModelGateway(model, budget)
