from __future__ import annotations

import httpx

from .base import LLMError, transient_retry


class OllamaProvider:
    def __init__(self, model: str, temperature: float, max_tokens: int, base_url: str, client: httpx.Client | None = None):
        self.model, self.temperature, self.max_tokens = model, temperature, max_tokens
        self._base = base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=120)

    @transient_retry
    def _call(self, system: str, user: str, max_tokens: int) -> dict:
        r = self._client.post(f"{self._base}/api/chat", json={
            "model": self.model, "stream": False,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "options": {"temperature": self.temperature, "num_predict": max_tokens}})
        r.raise_for_status()
        return r.json()

    def complete(self, system: str, user: str, *, max_tokens: int | None = None) -> str:
        try:
            return self._call(system, user, max_tokens or self.max_tokens)["message"]["content"]
        except Exception as e:  # noqa: BLE001
            raise LLMError(f"Ollama call failed: {type(e).__name__}") from e
