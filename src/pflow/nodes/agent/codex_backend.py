"""OpenAI Codex CLI adapter for the unified agent node."""

from __future__ import annotations

import json
import logging
import math
import os
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from pflow.core.exceptions import PflowError
from pflow.nodes.agent.backend import AgentResult
from pflow.nodes.agent.schema_validation import CODEX_PARAMS, SHARED_PARAMS

logger = logging.getLogger(__name__)

_SANDBOX_MODES = {
    "read-only": "read-only",
    "workspace-write": "workspace-write",
    "full-access": "danger-full-access",
}
_APPROVAL_POLICIES = frozenset({"untrusted", "on-request", "never"})
_AUTH_ERROR_MARKERS = (
    "401",
    "authentication",
    "login required",
    "missing bearer",
    "not logged in",
    "unauthorized",
)
_BARE_TOML_KEY = re.compile(r"^[A-Za-z0-9_-]+$")
_LOGIN_STATUS_TIMEOUT_SECONDS = 10


class _AuthClass(Enum):
    ACCOUNT = "account"
    API_KEY = "api_key"
    UNSUPPORTED_CREDENTIAL = "unsupported_credential"
    LOGGED_OUT = "logged_out"
    UNKNOWN = "unknown"


class CodexNonRetriableError(PflowError):
    """Deterministic Codex setup/auth failure that batch retries cannot fix."""

    retriable = False


class CodexEventParseError(Exception):
    """The CLI emitted a non-JSON line despite running with ``--json``."""


class CodexProcessError(Exception):
    """Preserve the complete failed-process surface for actionable translation."""

    def __init__(
        self,
        *,
        argv: list[str],
        returncode: int,
        stdout: str,
        stderr: str,
        failure_messages: list[str] | None = None,
    ) -> None:
        self.argv = argv
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.failure_messages = failure_messages or []
        detail = "\n".join(part for part in [stderr.strip(), *self.failure_messages] if part)
        super().__init__(detail or f"codex exited with status {returncode}")


@dataclass
class _ParsedEvents:
    session_id: str | None = None
    usage: dict[str, int] = field(default_factory=dict)
    num_turns: int = 0
    tool_uses: list[dict[str, Any]] = field(default_factory=list)
    progress_events: list[dict[str, Any]] = field(default_factory=list)
    failure_messages: list[str] = field(default_factory=list)
    usage_available: bool = False


def _build_child_env(use_api_key: bool) -> dict[str, str]:
    """Copy the process environment and remove known API keys in safe mode."""
    env = os.environ.copy()
    if not use_api_key:
        env.pop("CODEX_API_KEY", None)
        env.pop("OPENAI_API_KEY", None)
    return env


def _classify_login_status(stdout: str, stderr: str) -> _AuthClass:
    """Classify recognized ``codex login status`` lines without retaining text."""
    recognized: set[_AuthClass] = set()
    for raw_line in (*stdout.splitlines(), *stderr.splitlines()):
        line = raw_line.strip()
        if line in {"Logged in using ChatGPT", "Logged in using access token"}:
            recognized.add(_AuthClass.ACCOUNT)
        elif line.startswith("Logged in using an API key - "):
            recognized.add(_AuthClass.API_KEY)
        elif line in {
            "Logged in using personal access token",
            "Logged in using Amazon Bedrock API key",
        }:
            recognized.add(_AuthClass.UNSUPPORTED_CREDENTIAL)
        elif line == "Not logged in":
            recognized.add(_AuthClass.LOGGED_OUT)
    if len(recognized) != 1:
        return _AuthClass.UNKNOWN
    return next(iter(recognized))


def _toml_key(value: str) -> str:
    return value if _BARE_TOML_KEY.fullmatch(value) else json.dumps(value, ensure_ascii=False)


def _toml_value(value: Any) -> str:
    """Serialize the TOML value portion of a Codex ``-c key=value`` override."""
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise TypeError("Codex config float values must be finite")
        return repr(value)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    if isinstance(value, dict):
        entries: list[str] = []
        for key, item in value.items():
            if not isinstance(key, str) or not key:
                raise TypeError("Codex config inline-table keys must be non-empty strings")
            entries.append(f"{_toml_key(key)} = {_toml_value(item)}")
        return "{ " + ", ".join(entries) + " }"
    raise TypeError(
        "Codex config values must be TOML-compatible strings, booleans, numbers, lists, or dicts; "
        f"got {type(value).__name__}"
    )


def _event_error_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("message", "error", "detail"):
            if value.get(key):
                return str(value[key])
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value) if value is not None else "Codex turn failed without error details"


class CodexBackend:
    """Run agent turns through the installed ``codex exec`` CLI."""

    default_model: str | None = None
    max_retries = 2

    def validate_params(self, params: dict[str, Any]) -> dict[str, Any]:
        invalid = sorted(set(params) - (SHARED_PARAMS | CODEX_PARAMS))
        if invalid:
            raise ValueError(f"{invalid[0]!r} is not valid for backend 'codex'")

        return {
            "approval_policy": self._validate_approval_policy(params.get("approval_policy")),
            "add_dir": self._validate_add_dirs(params.get("add_dir")),
            "profile": self._validate_profile(params.get("profile")),
            "config": self._validate_config(params.get("config")),
            "sandbox": self._validate_sandbox(params.get("sandbox")),
        }

    @staticmethod
    def _validate_approval_policy(value: Any) -> str | None:
        if value is not None and (not isinstance(value, str) or value not in _APPROVAL_POLICIES):
            choices = ", ".join(sorted(_APPROVAL_POLICIES))
            raise ValueError(f"approval_policy must be one of: {choices}; got {value!r}")
        return value

    @staticmethod
    def _validate_add_dirs(value: Any) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list) or any(not isinstance(path, str) or not path.strip() for path in value):
            raise TypeError("add_dir must be a list of non-empty directory strings")
        return value.copy()

    @staticmethod
    def _validate_profile(value: Any) -> str | None:
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise TypeError("profile must be a non-empty string")
        return value

    @staticmethod
    def _validate_config(value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise TypeError(f"config must be a dict, got {type(value).__name__}")
        config_values = value.copy()
        for key, item in config_values.items():
            if not isinstance(key, str) or not key.strip():
                raise TypeError("Codex config keys must be non-empty strings")
            _toml_value(item)
        return config_values

    @staticmethod
    def _validate_sandbox(value: Any) -> str:
        if value is None:
            return "workspace-write"
        if not isinstance(value, str) or value not in _SANDBOX_MODES:
            choices = ", ".join(_SANDBOX_MODES)
            raise ValueError(f"sandbox must be one of: {choices}; got {value!r}")
        return value

    def run(self, prompt: str, options: dict[str, Any]) -> AgentResult:
        use_api_key = bool(options.get("use_api_key"))
        env = _build_child_env(use_api_key)
        if not use_api_key:
            self._require_account_auth(options, env)

        with tempfile.TemporaryDirectory(prefix="pflow-codex-") as temp_dir:
            temp_path = Path(temp_dir)
            message_path = temp_path / "last-message.txt"
            schema_path: Path | None = None
            if options.get("output_schema") is not None:
                schema_path = temp_path / "output-schema.json"
                schema_path.write_text(
                    json.dumps(options["output_schema"], ensure_ascii=False),
                    encoding="utf-8",
                )

            argv = self._build_argv(prompt, options, message_path, schema_path)
            started = time.monotonic()
            completed = subprocess.run(  # noqa: S603 - fixed executable, argv list, never a shell
                argv,
                cwd=options["cwd"],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=options["timeout"],
                check=False,
                env=env,
            )
            duration_ms = round((time.monotonic() - started) * 1000)
            try:
                parsed = self._parse_events(completed.stdout)
            except CodexEventParseError as exc:
                if completed.returncode == 0:
                    raise
                raise CodexProcessError(
                    argv=argv,
                    returncode=completed.returncode,
                    stdout=completed.stdout,
                    stderr=completed.stderr,
                    failure_messages=[str(exc)],
                ) from exc

            if completed.returncode != 0 or parsed.failure_messages:
                raise CodexProcessError(
                    argv=argv,
                    returncode=completed.returncode,
                    stdout=completed.stdout,
                    stderr=completed.stderr,
                    failure_messages=parsed.failure_messages,
                )
            if options.get("resume") and not parsed.session_id:
                raise CodexProcessError(
                    argv=argv,
                    returncode=completed.returncode,
                    stdout=completed.stdout,
                    stderr=completed.stderr,
                    failure_messages=["Codex resume completed without a thread.started thread_id"],
                )

            if not message_path.exists():
                raise CodexProcessError(
                    argv=argv,
                    returncode=completed.returncode,
                    stdout=completed.stdout,
                    stderr=completed.stderr,
                    failure_messages=["Codex completed without writing --output-last-message"],
                )
            result_text = message_path.read_text(encoding="utf-8")
            structured_output: Any = None
            if schema_path is not None and result_text:
                try:
                    structured_output = json.loads(result_text)
                except json.JSONDecodeError:
                    # A successful turn with malformed structured text follows the
                    # shared schema soft-fail/retry path in AgentNode.
                    structured_output = None

            usage = parsed.usage
            input_tokens = usage.get("input_tokens", 0)
            cache_read = usage.get("cached_input_tokens", 0)
            output_tokens = usage.get("output_tokens", 0)
            metadata = {
                "input_tokens": input_tokens,
                "uncached_input_tokens": max(0, input_tokens - cache_read),
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": cache_read,
                "input_token_accounting": "total_includes_cache",
                "output_tokens": output_tokens,
                "reasoning_output_tokens": usage.get("reasoning_output_tokens", 0),
                "total_tokens": input_tokens + output_tokens,
                "cost_usd": None,
                "duration_ms": duration_ms,
                "num_turns": parsed.num_turns or 1,
                "session_id": parsed.session_id,
                "usage_available": parsed.usage_available,
            }
            return AgentResult(
                result_text=result_text,
                tool_uses=parsed.tool_uses,
                metadata=metadata,
                progress_events=parsed.progress_events,
                structured_output=structured_output,
            )

    @staticmethod
    def _require_account_auth(options: dict[str, Any], env: dict[str, str]) -> None:
        """Require recognized Codex account auth before a safe-mode model call."""
        completed: subprocess.CompletedProcess[str] | None = None
        try:
            completed = subprocess.run(
                ["codex", "login", "status"],  # noqa: S607 - fixed executable resolved from PATH
                cwd=options["cwd"],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=_LOGIN_STATUS_TIMEOUT_SECONDS,
                check=False,
                env=env,
            )
        except FileNotFoundError as exc:
            raise CodexNonRetriableError(
                "Codex CLI was not found on PATH. Install it with "
                "`npm install -g @openai/codex`, then authenticate with `codex login`."
            ) from exc
        except subprocess.TimeoutExpired:
            # Raise only after leaving the except block. ``TimeoutExpired`` can
            # retain partial stdout/stderr, so even ``raise ... from None``
            # inside the handler would leave secret-bearing data reachable via
            # ``__context__``.
            pass

        if completed is None:
            raise CodexNonRetriableError(
                "Codex authentication check timed out after 10 seconds. Run `codex login status` manually and retry."
            ) from None

        auth_class = _classify_login_status(completed.stdout, completed.stderr)
        if completed.returncode == 0 and auth_class is _AuthClass.ACCOUNT:
            return
        if auth_class is _AuthClass.API_KEY:
            raise CodexNonRetriableError(
                "Codex is logged in with API-key authentication, but `use_api_key` is false. "
                "Add `use_api_key: true` only if you intend API-key/provider billing, or run "
                "`codex login` for account authentication. Inspect the active mode with "
                "`codex login status`."
            )
        if auth_class is _AuthClass.UNSUPPORTED_CREDENTIAL:
            raise CodexNonRetriableError(
                "Codex is using an unsupported credential type for safe mode. Run `codex login` "
                "for account authentication, then verify it with `codex login status`."
            )
        if completed.returncode != 0 or auth_class is _AuthClass.LOGGED_OUT:
            raise CodexNonRetriableError(
                "Codex account authentication is unavailable. Run `codex login`, then verify "
                "the account login with `codex login status`."
            )
        raise CodexNonRetriableError(
            "Codex authentication status was not recognized. Inspect `codex login status` "
            "manually; use `codex login` to establish account authentication."
        )

    def _build_argv(
        self,
        prompt: str,
        options: dict[str, Any],
        message_path: Path,
        schema_path: Path | None,
    ) -> list[str]:
        argv = ["codex", "exec"]
        if options.get("profile"):
            # --profile belongs to the parent exec parser. The resume parser
            # rejects it when placed after the subcommand.
            argv.extend(["--profile", options["profile"]])

        is_resume = bool(options.get("resume"))
        if is_resume:
            argv.append("resume")

        self._append_output_options(argv, options, message_path, schema_path)
        self._append_config_options(argv, options)
        self._append_execution_scope(argv, options, is_resume)

        argv.append("--")
        if is_resume:
            argv.append(options["resume"])
        argv.append(prompt)
        return argv

    @staticmethod
    def _append_output_options(
        argv: list[str],
        options: dict[str, Any],
        message_path: Path,
        schema_path: Path | None,
    ) -> None:
        argv.extend([
            "--skip-git-repo-check",
            "--json",
            "--output-last-message",
            str(message_path),
        ])
        if options.get("model"):
            argv.extend(["--model", options["model"]])
        if schema_path is not None:
            argv.extend(["--output-schema", str(schema_path)])

    def _append_execution_scope(self, argv: list[str], options: dict[str, Any], is_resume: bool) -> None:
        if is_resume:
            self._append_config(argv, "sandbox_mode", _SANDBOX_MODES[options["sandbox"]])
            return
        argv.extend(["--sandbox", _SANDBOX_MODES[options["sandbox"]], "--cd", options["cwd"]])
        for path in options.get("add_dir", []):
            argv.extend(["--add-dir", path])

    def _append_config_options(self, argv: list[str], options: dict[str, Any]) -> None:
        for key, value in options.get("config", {}).items():
            self._append_config(argv, key, value)
        if options.get("approval_policy") is not None:
            self._append_config(argv, "approval_policy", options["approval_policy"])
        if options.get("system_prompt"):
            self._append_config(argv, "developer_instructions", options["system_prompt"])
        if not options.get("use_api_key"):
            self._append_config(argv, "model_provider", "openai")

    @staticmethod
    def _append_config(argv: list[str], key: str, value: Any) -> None:
        argv.extend(["--config", f"{key}={_toml_value(value)}"])

    @staticmethod
    def _parse_events(stdout: str) -> _ParsedEvents:
        parsed = _ParsedEvents()
        usage_totals = {
            "input_tokens": 0,
            "cached_input_tokens": 0,
            "output_tokens": 0,
            "reasoning_output_tokens": 0,
        }

        for line_number, raw_line in enumerate(stdout.splitlines(), start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise CodexEventParseError(f"Invalid Codex JSONL event on line {line_number}: {exc.msg}") from exc
            if not isinstance(event, dict):
                raise CodexEventParseError(f"Invalid Codex JSONL event on line {line_number}: expected an object")

            CodexBackend._consume_event(event, parsed, usage_totals)

        parsed.usage = usage_totals
        return parsed

    @staticmethod
    def _consume_event(event: dict[str, Any], parsed: _ParsedEvents, usage_totals: dict[str, int]) -> None:
        event_type = event.get("type")
        if event_type == "thread.started":
            CodexBackend._consume_thread_started(event, parsed)
        elif event_type == "turn.started":
            parsed.progress_events.append({"type": "turn_started"})
        elif event_type == "turn.completed":
            CodexBackend._consume_turn_completed(event, parsed, usage_totals)
        elif event_type == "item.completed":
            CodexBackend._consume_item_completed(event, parsed)
        elif event_type == "turn.failed":
            parsed.failure_messages.append(_event_error_text(event.get("error")))
        elif event_type == "error":
            parsed.failure_messages.append(_event_error_text(event.get("message", event.get("error"))))

    @staticmethod
    def _consume_thread_started(event: dict[str, Any], parsed: _ParsedEvents) -> None:
        thread_id = event.get("thread_id")
        if isinstance(thread_id, str) and thread_id:
            parsed.session_id = thread_id
            parsed.progress_events.append({"type": "thread_started", "thread_id": thread_id})

    @staticmethod
    def _consume_turn_completed(event: dict[str, Any], parsed: _ParsedEvents, usage_totals: dict[str, int]) -> None:
        parsed.num_turns += 1
        usage = event.get("usage")
        if isinstance(usage, dict):
            parsed.usage_available = True
            for key in usage_totals:
                value = usage.get(key, 0)
                if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                    usage_totals[key] += value
        parsed.progress_events.append({"type": "completion", "turns": parsed.num_turns})

    @staticmethod
    def _consume_item_completed(event: dict[str, Any], parsed: _ParsedEvents) -> None:
        item = event.get("item")
        if not isinstance(item, dict) or item.get("type") != "command_execution":
            return
        command = str(item.get("command") or "command")
        output = str(item.get("aggregated_output") or "")
        parsed.tool_uses.append({
            "name": command,
            "input": output[:500],
            "exit_code": item.get("exit_code"),
            "status": item.get("status"),
        })
        parsed.progress_events.append({
            "type": "tool_use",
            "tool": command,
            "input_preview": output[:200],
        })

    def continuation_options(self, previous: AgentResult, options: dict[str, Any]) -> dict[str, Any] | None:
        session_id = previous.metadata.get("session_id")
        if not session_id:
            return None
        continuation = options.copy()
        continuation["resume"] = session_id
        return continuation

    def translate_error(self, exc: Exception, options: dict[str, Any]) -> Exception:
        if isinstance(exc, CodexNonRetriableError):
            return exc
        logger.error("Codex execution failed: %s", exc, exc_info=exc)
        if isinstance(exc, FileNotFoundError):
            return CodexNonRetriableError(
                "Codex CLI was not found on PATH. Install it with "
                "`npm install -g @openai/codex`, then authenticate with `codex login`."
            )
        if isinstance(exc, subprocess.TimeoutExpired):
            return ValueError(
                f"Codex execution timed out after {options.get('timeout', 300)} seconds. "
                "Increase timeout or split the task into smaller steps."
            )

        error_text = str(exc)
        if isinstance(exc, CodexProcessError):
            error_text = "\n".join(
                part for part in [exc.stderr.strip(), exc.stdout.strip(), *exc.failure_messages] if part
            ) or str(exc)
        if any(marker in error_text.lower() for marker in _AUTH_ERROR_MARKERS):
            if options.get("use_api_key"):
                return CodexNonRetriableError(
                    "Codex authentication failed while API-key/provider billing is permitted "
                    "(`use_api_key: true`). Check `OPENAI_API_KEY`, `CODEX_API_KEY`, and any "
                    "configured profile/provider credentials. To use account authentication "
                    "instead, remove `use_api_key: true`, run `codex login`, and verify with "
                    f"`codex login status`.\nOriginal error: {error_text}"
                )
            return CodexNonRetriableError(
                f"Codex authentication failed. Run `codex login` and retry.\nOriginal error: {error_text}"
            )
        if isinstance(exc, CodexProcessError):
            return ValueError(f"Codex CLI failed with exit code {exc.returncode}.\nError output: {error_text}")
        if isinstance(exc, CodexEventParseError):
            return ValueError(f"Codex CLI returned invalid --json output: {exc}")
        return ValueError(f"Codex execution failed after {self.max_retries} attempts: {exc}")

    def build_warning_context(self, options: dict[str, Any], result: AgentResult) -> dict[str, Any]:
        output_schema = options.get("output_schema") or {}
        properties = output_schema.get("properties") if isinstance(output_schema, dict) else None
        return {
            "node_type": "agent",
            "backend": "codex",
            "backend_display": "Codex CLI",
            "backend_error_details": "Codex CLI event/error details",
            "schema_properties": list(properties) if isinstance(properties, dict) else [],
            "schema_required": output_schema.get("required") if isinstance(output_schema, dict) else None,
            "result_preview": result.result_text[:500],
            "session_id": result.metadata.get("session_id"),
            "codex_error": result.error_text,
        }
