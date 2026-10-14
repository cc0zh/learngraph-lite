"""One budget and usage ledger for all model calls in an execution."""

from __future__ import annotations

from .budget import Budget
from .models import ModelGateway, ModelResponse, TextMessage
from .context import fit_context


class BudgetedModelGateway:
    def __init__(self, model: ModelGateway, budget: Budget):
        self._model = model
        self.budget = budget
        self.usage = budget.usage

    def complete(self, messages: tuple[TextMessage, ...], tools: tuple[dict, ...]) -> ModelResponse:
        messages = fit_context(messages, tools, self.budget.max_input_tokens)
        self.budget.take_model_call()
        response = self._model.complete(messages, tools)
        for key, value in response.usage.items():
            self.usage[key] = self.usage.get(key, 0) + value
        self.budget.check_step(0)
        return response

    def stream_complete(self, messages, tools, on_delta) -> ModelResponse:
        messages = fit_context(messages, tools, self.budget.max_input_tokens)
        stream = getattr(self._model, "stream_complete", None)
        if stream is None:
            return self.complete(messages, tools)
        self.budget.take_model_call()

        def checked_delta(text):
            self.budget.check_step(0)
            on_delta(text)

        response = stream(messages, tools, checked_delta)
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
