from __future__ import annotations

from .base import LLMError, transient_retry


class AnthropicProvider:
    def __init__(self, model: str, temperature: float, max_tokens: int, api_key: str, client=None):
        self.model, self.temperature, self.max_tokens = model, temperature, max_tokens
        if client is None:
            if not api_key:
                raise LLMError("ANTHROPIC_API_KEY is not set")
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
        self._client = client

    @transient_retry
    def _call(self, system: str, user: str, max_tokens: int):
        return self._client.messages.create(model=self.model, max_tokens=max_tokens, temperature=self.temperature,
                                            system=system, messages=[{"role": "user", "content": user}])

    def complete(self, system: str, user: str, *, max_tokens: int | None = None) -> str:
        try:
            resp = self._call(system, user, max_tokens or self.max_tokens)
        except Exception as e:  # noqa: BLE001 - surface a uniform error type
            raise LLMError(f"Anthropic call failed: {type(e).__name__}") from e
        return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
