"""Provider factory: builds an LLM client from the *current* Model Config (hot-reloaded per request)."""
from __future__ import annotations

from app.config import Settings
from app.schemas.admin import ModelConfig

from .base import LLMError, LLMProvider


def create_llm(cfg: ModelConfig, settings: Settings) -> LLMProvider:
    if cfg.provider == "anthropic":
        from .anthropic_provider import AnthropicProvider
        return AnthropicProvider(cfg.model, cfg.temperature, cfg.max_tokens, settings.anthropic_api_key)
    if cfg.provider == "openai":
        from .openai_provider import OpenAIProvider
        return OpenAIProvider(cfg.model, cfg.temperature, cfg.max_tokens, settings.openai_api_key)
    if cfg.provider == "claude_cli":
        from .claude_cli_provider import ClaudeCliProvider
        return ClaudeCliProvider(cfg.model, cfg.temperature, cfg.max_tokens, settings.claude_cli_path, settings.claude_cli_timeout)
    if cfg.provider == "ollama":
        from .ollama_provider import OllamaProvider
        return OllamaProvider(cfg.model, cfg.temperature, cfg.max_tokens, settings.ollama_base_url)
    raise LLMError(f"Unknown provider {cfg.provider!r}")
