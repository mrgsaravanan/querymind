from __future__ import annotations

from .base import LLMError, transient_retry


class OpenAIProvider:
    def __init__(self, model: str, temperature: float, max_tokens: int, api_key: str, client=None):
        self.model, self.temperature, self.max_tokens = model, temperature, max_tokens
        if client is None:
            if not api_key:
                raise LLMError("OPENAI_API_KEY is not set")
            import openai
            client = openai.OpenAI(api_key=api_key)
        self._client = client

    @transient_retry
    def _call(self, system: str, user: str, max_tokens: int):
        return self._client.chat.completions.create(
            model=self.model, temperature=self.temperature, max_tokens=max_tokens,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])

    def complete(self, system: str, user: str, *, max_tokens: int | None = None) -> str:
        try:
            resp = self._call(system, user, max_tokens or self.max_tokens)
        except Exception as e:  # noqa: BLE001
            raise LLMError(f"OpenAI call failed: {type(e).__name__}") from e
        return resp.choices[0].message.content or ""
