import json
import subprocess

import pytest

from app.config import Settings
from app.llm import create_llm
from app.llm.base import LLMError, LLMProvider
from app.llm.claude_cli_provider import ClaudeCliProvider
from app.schemas.admin import ModelConfig


def done(result="hello", is_error=False, status=None, code=0):
    out = json.dumps({"result": result, "is_error": is_error, "api_error_status": status})
    return subprocess.CompletedProcess([], code, stdout=out, stderr="")


class Runner:
    def __init__(self, *outcomes):
        self.outcomes, self.calls = list(outcomes), []

    def __call__(self, cmd, **kw):
        self.calls.append((cmd, kw))
        o = self.outcomes.pop(0) if len(self.outcomes) > 1 else self.outcomes[0]
        if isinstance(o, Exception):
            raise o
        return o


def make(runner, **kw):
    return ClaudeCliProvider("sonnet", 0.0, 512, "claude", runner=runner, **kw)


def test_command_is_locked_down_and_prompt_goes_via_stdin(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-not-leak")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "tok")
    r = Runner(done("the answer"))
    p = make(r)
    assert isinstance(p, LLMProvider) and p.complete("SYS PROMPT", "user question with 'quotes' & $(rm -rf /)") == "the answer"
    cmd, kw = r.calls[0]
    assert cmd[:2] == ["claude", "-p"] and cmd[cmd.index("--model") + 1] == "sonnet"
    assert cmd[cmd.index("--system-prompt") + 1] == "SYS PROMPT"
    assert cmd[cmd.index("--tools") + 1] == ""                       # no tools: injection cannot run anything
    for flag in ("--no-session-persistence", "--strict-mcp-config", "--disable-slash-commands"):
        assert flag in cmd
    assert cmd[cmd.index("--setting-sources") + 1] == ""             # no user hooks/memory/CLAUDE.md
    assert "user question" not in " ".join(cmd) and kw["input"].startswith("user question")   # user text only on stdin
    assert "ANTHROPIC_API_KEY" not in kw["env"] and "ANTHROPIC_AUTH_TOKEN" not in kw["env"]     # never bill the API
    assert kw["cwd"] != "." and kw["timeout"] == 120.0


def test_cli_error_becomes_safe_llm_error():
    p = make(Runner(done("There's an issue with the selected model (secret detail)", True, 404)))
    with pytest.raises(LLMError) as e:
        p.complete("s", "u")
    assert "404" in str(e.value) and "secret detail" not in str(e.value)


def test_login_hint_on_auth_failure():
    with pytest.raises(LLMError, match="claude login"):
        make(Runner(done("Invalid API key · Please run /login", True, 401))).complete("s", "u")


def test_unparseable_output_and_nonzero_exit():
    bad = subprocess.CompletedProcess([], 1, stdout="not json", stderr="boom")
    with pytest.raises(LLMError, match="unexpected response"):
        make(Runner(bad)).complete("s", "u")
    with pytest.raises(LLMError):
        make(Runner(done("x", False, None, code=2))).complete("s", "u")


def test_timeout_retries_once_then_fails():
    t = subprocess.TimeoutExpired("claude", 1)
    r = Runner(t, done("recovered"))
    assert make(r).complete("s", "u") == "recovered" and len(r.calls) == 2
    r2 = Runner(t)
    with pytest.raises(LLMError, match="timed out"):
        make(r2).complete("s", "u")
    assert len(r2.calls) == 2


def test_spawn_failure_is_llm_error():
    with pytest.raises(LLMError):
        make(Runner(FileNotFoundError("claude"))).complete("s", "u")


def test_missing_cli_and_factory_routing(monkeypatch):
    with pytest.raises(LLMError, match="not found"):
        ClaudeCliProvider("sonnet", 0, 1, "definitely-not-a-real-binary-xyz")
    st = Settings(claude_cli_path="definitely-not-a-real-binary-xyz")
    with pytest.raises(LLMError, match="not found"):
        create_llm(ModelConfig(provider="claude_cli", model="sonnet"), st)
    import shutil
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/" + name)
    assert create_llm(ModelConfig(provider="claude_cli", model="sonnet"), Settings()).model == "sonnet"


def test_config_accepts_claude_cli_provider(admin_sessions, settings):
    from app.services.config_manager import ConfigManager
    cm = ConfigManager(admin_sessions, settings)
    assert cm.update(ModelConfig(provider="claude_cli", model="sonnet")).provider == "claude_cli"
