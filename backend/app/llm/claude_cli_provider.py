"""Claude via the user's Claude subscription (Pro/Max), using the official ``claude`` CLI in headless mode.

No API key is needed: the CLI is authenticated through ``claude login`` (claude.ai account). This is the supported way
to use a subscription from your own program; the subscription's OAuth token must not be used directly with the API SDK.

Safety/behaviour notes
- Tools are disabled (``--tools ""``), MCP servers and user settings/hooks/memory are not loaded, and the CLI runs in an
  empty temp directory, so a prompt injection cannot make it read files or run commands.
- ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN are stripped from the child's environment so it can never silently bill the API.
- The CLI exposes no temperature or max-token flag, so those settings do not apply to this provider.
- Each call starts a CLI process (~2-4 s overhead). Fine for interactive use; expect a full evaluation run to take minutes.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
from typing import Callable

from .base import LLMError

log = logging.getLogger(__name__)

_STRIP_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN")
Runner = Callable[..., subprocess.CompletedProcess]


class ClaudeCliProvider:
    def __init__(self, model: str, temperature: float, max_tokens: int, cli_path: str = "claude",
                 timeout_seconds: float = 120.0, runner: Runner | None = None):
        self.model, self.temperature, self.max_tokens = model, temperature, max_tokens  # temperature/max_tokens: not applicable
        self._timeout = timeout_seconds
        self._run = runner or subprocess.run
        resolved = shutil.which(cli_path) if runner is None else cli_path
        if not resolved:
            raise LLMError(f"Claude CLI '{cli_path}' not found. Install Claude Code and run `claude login`, "
                           "or set CLAUDE_CLI_PATH.")
        self._cli = resolved

    def _command(self, system: str) -> list[str]:
        return [self._cli, "-p", "--output-format", "json", "--model", self.model, "--system-prompt", system,
                "--tools", "", "--no-session-persistence", "--setting-sources", "", "--strict-mcp-config",
                "--disable-slash-commands"]

    def _call(self, system: str, user: str) -> subprocess.CompletedProcess:
        env = {k: v for k, v in os.environ.items() if k not in _STRIP_ENV}
        with tempfile.TemporaryDirectory(prefix="querymind_cli_") as cwd:
            return self._run(self._command(system), input=user, capture_output=True, text=True, env=env, cwd=cwd,
                             timeout=self._timeout)

    def complete(self, system: str, user: str, *, max_tokens: int | None = None) -> str:
        proc = None
        for attempt in (1, 2):  # one retry, only for timeouts / spawn failures
            try:
                proc = self._call(system, user)
                break
            except subprocess.TimeoutExpired:
                log.warning("claude CLI timed out after %.0fs (attempt %d)", self._timeout, attempt)
                if attempt == 2:
                    raise LLMError("Claude CLI timed out") from None
            except OSError as e:
                raise LLMError(f"Could not run the Claude CLI: {type(e).__name__}") from e
        assert proc is not None
        try:
            data = json.loads(proc.stdout)
        except (json.JSONDecodeError, TypeError):
            log.error("claude CLI exit=%s, unparseable output; stderr=%.300s", proc.returncode, proc.stderr)
            raise LLMError("Claude CLI returned an unexpected response (is it logged in? try `claude auth status`)") from None
        if proc.returncode != 0 or data.get("is_error"):
            detail = str(data.get("result", ""))[:300]
            log.error("claude CLI error: status=%s %s", data.get("api_error_status"), detail)
            hint = " Run `claude login`." if data.get("api_error_status") in (401, 403) or "login" in detail.lower() else ""
            raise LLMError(f"Claude CLI call failed (status {data.get('api_error_status')}).{hint}")
        return str(data.get("result", ""))
