"""LLM provider abstraction. Model, provider and temperature come from config, never from stage logic."""
from __future__ import annotations

import json
import re
from typing import Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel, ValidationError
from tenacity import retry, stop_after_attempt, wait_exponential

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    """Provider call failed (after transient retries)."""


class LLMOutputError(ValueError):
    """The model replied, but not with valid structured output."""


@runtime_checkable
class LLMProvider(Protocol):
    """Anything that can turn (system, user) into text. Implementations carry their own model settings."""

    model: str
    temperature: float
    max_tokens: int

    def complete(self, system: str, user: str, *, max_tokens: int | None = None) -> str: ...


def transient_retry(fn):
    """Retry provider calls on transient failures (network, 429/5xx) with short exponential backoff."""
    return retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.5, max=4), reraise=True)(fn)


_FENCE = re.compile(r"^```[a-zA-Z]*\s*\n?(.*?)\n?```\s*$", re.DOTALL)


def strip_code_fences(text: str) -> str:
    """Remove a surrounding markdown code fence, if any."""
    text = text.strip()
    m = _FENCE.match(text)
    return m.group(1).strip() if m else text


def extract_json(text: str) -> dict:
    """Parse a JSON object from model output, tolerating fences and surrounding prose."""
    text = strip_code_fences(text)
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise LLMOutputError("No JSON object found in model output")
        try:
            obj = json.loads(text[start : end + 1])
        except json.JSONDecodeError as e:
            raise LLMOutputError(f"Invalid JSON in model output: {e}") from e
    if not isinstance(obj, dict):
        raise LLMOutputError("Expected a JSON object")
    return obj


def complete_structured(llm: LLMProvider, system: str, user: str, model: type[T], *, max_tokens: int | None = None) -> T:
    """Call the LLM and validate its JSON reply against a Pydantic model. Raises LLMOutputError on bad output."""
    raw = llm.complete(system, user, max_tokens=max_tokens)
    try:
        return model.model_validate(extract_json(raw))
    except ValidationError as e:
        raise LLMOutputError(f"Output failed schema validation: {e.error_count()} error(s)") from e
