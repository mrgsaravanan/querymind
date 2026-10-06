"""Test doubles."""
from __future__ import annotations


class FakeLLM:
    """Returns queued responses in order (last one repeats) and records every prompt it sees."""

    model = "fake"
    temperature = 0.0
    max_tokens = 512

    def __init__(self, *responses: str):
        self.responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str, *, max_tokens: int | None = None) -> str:
        self.calls.append((system, user))
        return self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]


class ScriptedLLM:
    """Routes by pipeline role (detected from the system prompt) and records which roles were called.

    roles: classifier / generator / formatter -> response or list of responses (last one repeats).
    """

    model = "scripted"
    temperature = 0.0
    max_tokens = 512

    def __init__(self, classifier=None, generator=None, formatter="Summary."):
        self.queues = {"classifier": self._q(classifier), "generator": self._q(generator), "formatter": self._q(formatter)}
        self.calls: list[tuple[str, str, str]] = []  # (role, system, user)

    @staticmethod
    def _q(v):
        return list(v) if isinstance(v, (list, tuple)) else [v]

    @staticmethod
    def role_of(system: str) -> str:
        if "classify business questions" in system:
            return "classifier"
        if "converts business questions into SQL" in system:
            return "generator"
        return "formatter"

    def complete(self, system: str, user: str, *, max_tokens: int | None = None) -> str:
        role = self.role_of(system)
        self.calls.append((role, system, user))
        q = self.queues[role]
        if q[0] is None:
            raise AssertionError(f"unexpected {role} call")
        return q.pop(0) if len(q) > 1 else q[0]

    def roles(self) -> list[str]:
        return [c[0] for c in self.calls]
