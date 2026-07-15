"""OpenAI Codex CLI adapter for the unified agent node."""

from __future__ import annotations

import json
import logging
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from contextlib import suppress
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from pflow.core.exceptions import PflowError
from pflow.core.litellm_runtime import estimate_completion_cost_usd
from pflow.nodes.agent.backend import AgentResult
from pflow.nodes.agent.exceptions import AgentValidationError
from pflow.nodes.agent.schema_validation import (
    CODEX_PARAMS,
    SHARED_PARAMS,
    is_compiler_source_line_sidecar,
    validate_codex_add_dirs,
    validate_codex_approval_policy,
    validate_codex_profile,
    validate_codex_sandbox,
)

logger = logging.getLogger(__name__)

_SANDBOX_MODES = {
    "read-only": "read-only",
    "workspace-write": "workspace-write",
    "full-access": "danger-full-access",
}
_AUTH_FAILURE_PATTERN = re.compile(
    r"(?:\b401\s+unauthorized\b|\bhttp(?: status)?\s*[:=]?\s*401\b|"
    r"\bapi_error_status\s*[:=\[]\s*401\b|\bmissing bearer\b|"
    r"\blogin required\b|\bnot logged in\b|\binvalid api key\b|"
    r"\bauthentication failed\b)",
    re.IGNORECASE,
)
_BARE_TOML_KEY = re.compile(r"^[A-Za-z0-9_-]+$")
_LOGIN_STATUS_TIMEOUT_SECONDS = 10
_PROCESS_DRAIN_TIMEOUT_SECONDS = 1
_PROCESS_POLL_INTERVAL_SECONDS = 0.1
_WINDOWS_TASKKILL_TIMEOUT_SECONDS = 5
_IS_WINDOWS = sys.platform == "win32"


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


class CodexModelTimeoutError(PflowError):
    """Secret-safe timeout from a Codex model process."""

    def __init__(self, timeout_seconds: int) -> None:
        self.timeout_seconds = timeout_seconds
        super().__init__(f"Codex execution timed out after {timeout_seconds} seconds")


class CodexProcessCancelledError(PflowError):
    """Internal signal that a parallel batch cancelled this Codex process."""

    cancelled = True
    retriable = False

    def __init__(self) -> None:
        super().__init__("Codex execution cancelled by the batch executor")


class CodexProcessError(Exception):
    """Preserve failed-process evidence behind a secret-safe string surface."""

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
        super().__init__(f"Codex CLI failed with exit code {returncode}")


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
            raise AgentValidationError("Codex config float values must be finite")
        return repr(value)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    if isinstance(value, dict):
        entries: list[str] = []
        for key, item in value.items():
            if not isinstance(key, str) or not key:
                raise AgentValidationError("Codex config inline-table keys must be non-empty strings")
            entries.append(f"{_toml_key(key)} = {_toml_value(item)}")
        return "{ " + ", ".join(entries) + " }"
    raise AgentValidationError(
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


# JSON Schema keywords that hold nested subschemas, grouped by container shape.
_SCHEMA_MAP_KEYWORDS = ("properties", "$defs", "definitions", "patternProperties")
_SCHEMA_LIST_KEYWORDS = ("allOf", "anyOf", "oneOf", "prefixItems")
_SCHEMA_NODE_KEYWORDS = ("items", "additionalItems", "not", "if", "then", "else", "contains")


def _recurse_into_subschemas(node: dict[str, Any]) -> None:
    """Strictify every nested subschema a JSON Schema node holds, in place."""
    for keyword in _SCHEMA_MAP_KEYWORDS:
        subschemas = node.get(keyword)
        if isinstance(subschemas, dict):
            node[keyword] = {name: _strictify_schema(value) for name, value in subschemas.items()}
    for keyword in _SCHEMA_LIST_KEYWORDS:
        subschemas = node.get(keyword)
        if isinstance(subschemas, list):
            node[keyword] = [_strictify_schema(value) for value in subschemas]
    for keyword in _SCHEMA_NODE_KEYWORDS:
        if keyword in node:
            node[keyword] = _strictify_schema(node[keyword])


def _strictify_schema(schema: Any) -> Any:
    """Return a deep copy of ``schema`` satisfying OpenAI strict structured-output rules.

    Codex's ``--output-schema`` forwards the schema to OpenAI's strict
    ``response_format``, which rejects any object schema that does not set
    ``additionalProperties: false`` and list *every* property in ``required``.
    Claude's SDK applies equivalent normalization internally, so this keeps the
    shared ``output_schema`` parameter behaving identically on both backends.

    Previously-optional properties become always-emitted rather than nullable, so
    the model's output still validates against the caller's *original* schema in
    ``AgentNode`` (a nullable value would fail that post-validation instead). The
    caller's schema dict is never mutated.
    """
    if isinstance(schema, list):
        return [_strictify_schema(item) for item in schema]
    if not isinstance(schema, dict):
        return schema

    result = dict(schema)
    _recurse_into_subschemas(result)
    properties = result.get("properties")
    if result.get("type") == "object" or isinstance(properties, dict):
        result["additionalProperties"] = False
        if isinstance(properties, dict):
            result["required"] = list(properties.keys())
    return result


_MAX_FAILURE_DETAIL_CHARS = 500


def _parse_provider_error(raw: str) -> tuple[str, str] | None:
    """Return ``(code, message)`` from a *structured* provider-error payload, else ``None``.

    A Codex ``turn.failed``/``error`` event carries the model API's error as a JSON
    object with an ``error`` sub-object (``{"error": {"code": ..., "message": ...}}``),
    sometimes nested as a JSON string under ``message``. Only that structured shape is
    parsed. Free text, raw stdout/stderr, and tool ``aggregated_output`` are NOT
    structured provider errors and return ``None`` — they are never surfaced, preserving
    the secret-safe boundary the auth path already enforces upstream.
    """
    text = raw.strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    nested = payload.get("message")
    if isinstance(nested, str):
        inner = _parse_provider_error(nested)
        if inner is not None:
            return inner
    error = payload.get("error")
    if not isinstance(error, dict):
        return None
    code = str(error.get("code") or error.get("type") or "").strip()
    message = str(error.get("message") or "").strip()
    if not code and not message:
        return None
    return code, message


def _readable_failure_detail(messages: list[str]) -> str:
    """Summarize Codex turn failures from their *structured* provider-error payloads only.

    Surfaces ``code: message`` for real API/protocol failures (e.g. ``invalid_json_schema``,
    ``rate_limit_exceeded``) so a caller can fix the workflow, while ignoring any
    unstructured failure text. The ``error`` and ``turn.failed`` events carry the same
    payload, so identical entries are de-duplicated. Returns ``""`` when nothing
    structured is present.
    """
    parts: list[str] = []
    for raw in messages:
        parsed = _parse_provider_error(raw)
        if parsed is None:
            continue
        code, message = parsed
        detail = f"{code}: {message}" if code and message else (code or message)
        if detail:
            parts.append(detail)
    combined = "; ".join(dict.fromkeys(parts))
    if len(combined) > _MAX_FAILURE_DETAIL_CHARS:
        combined = combined[:_MAX_FAILURE_DETAIL_CHARS].rstrip() + "…"
    return combined


def _terminate_windows_process_tree(pid: int) -> None:
    """Best-effort termination of a Codex process and all descendants on Windows."""
    taskkill_path = shutil.which("taskkill") or r"C:\Windows\System32\taskkill.exe"
    try:
        completed = subprocess.run(  # noqa: S603 - resolved system utility, argv list, never a shell
            [taskkill_path, "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=_WINDOWS_TASKKILL_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return
    if completed.returncode != 0:
        logger.debug("taskkill failed while terminating Codex process tree", extra={"pid": pid})


class _WindowsKillJob:
    """A Windows Job Object configured to kill assigned processes on close."""

    def __init__(self, handle: Any) -> None:
        self.handle = handle

    def close(self) -> bool:
        if self.handle is None:
            return True
        try:
            import ctypes

            closed = bool(ctypes.windll.kernel32.CloseHandle(self.handle))  # type: ignore[attr-defined, unused-ignore]
        except (AttributeError, OSError):
            closed = False
        self.handle = None
        return closed


def _create_windows_kill_job(proc: subprocess.Popen[str]) -> _WindowsKillJob | None:
    """Assign ``proc`` to a kill-on-close Job Object, falling back safely."""
    if not _IS_WINDOWS:
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class _BasicLimitInformation(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class _IoCounters(ctypes.Structure):
            _fields_ = [
                (name, ctypes.c_ulonglong)
                for name in (
                    "ReadOperationCount",
                    "WriteOperationCount",
                    "OtherOperationCount",
                    "ReadTransferCount",
                    "WriteTransferCount",
                    "OtherTransferCount",
                )
            ]

        class _ExtendedLimitInformation(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", _BasicLimitInformation),
                ("IoInfo", _IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined, unused-ignore]
        create_job = kernel32.CreateJobObjectW
        create_job.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
        create_job.restype = wintypes.HANDLE
        set_information = kernel32.SetInformationJobObject
        set_information.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
        set_information.restype = wintypes.BOOL
        assign_process = kernel32.AssignProcessToJobObject
        assign_process.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        assign_process.restype = wintypes.BOOL

        handle = create_job(None, None)
        if not handle:
            return None
        job = _WindowsKillJob(handle)
        information = _ExtendedLimitInformation()
        information.BasicLimitInformation.LimitFlags = 0x00002000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        configured = set_information(
            handle,
            9,  # JobObjectExtendedLimitInformation
            ctypes.byref(information),
            ctypes.sizeof(information),
        )
        process_handle = getattr(proc, "_handle", None)
        assigned = process_handle is not None and assign_process(handle, process_handle)
        if not configured or not assigned:
            job.close()
            return None
        return job
    except (AttributeError, OSError, TypeError, ValueError):
        return None


def _terminate_codex_process_tree(proc: subprocess.Popen[str], windows_job: _WindowsKillJob | None = None) -> None:
    """Forcefully stop the Codex process tree after timeout or interruption."""
    if _IS_WINDOWS:
        if windows_job is None or not windows_job.close():
            _terminate_windows_process_tree(proc.pid)
    else:
        killpg = getattr(os, "killpg", None)
        if killpg is not None:
            with suppress(OSError):
                # start_new_session=True makes the process PID its group ID. Use
                # that known ID directly: the CLI itself may already have exited
                # while a descendant still holds stdout/stderr pipes open.
                killpg(proc.pid, getattr(signal, "SIGKILL", signal.SIGTERM))
    with suppress(OSError):
        proc.kill()


def _run_codex_process(
    argv: list[str],
    *,
    cwd: str,
    timeout: int,
    env: dict[str, str],
    cancel_event: Any | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run one Codex model process and clean up its descendants on abort.

    ``subprocess.run(timeout=...)`` kills only the direct CLI process. Codex may
    launch command/tool descendants that inherit stdout or stderr, so they can
    survive a timeout and keep pipe draining blocked. Giving the CLI its own
    process group and owning ``communicate`` lets pflow terminate the whole tree.
    """
    platform_kwargs: dict[str, Any]
    if _IS_WINDOWS:
        platform_kwargs = {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}
    else:
        platform_kwargs = {"start_new_session": True}

    proc = subprocess.Popen(  # noqa: S603 - fixed executable, argv list, never a shell
        argv,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        env=env,
        **platform_kwargs,
    )
    windows_job = _create_windows_kill_job(proc)
    timeout_error: CodexModelTimeoutError | None = None
    try:
        if cancel_event is None:
            stdout, stderr = proc.communicate(timeout=timeout)
        else:
            stdout, stderr = _communicate_with_cancellation(proc, argv, timeout, cancel_event, windows_job)
    except subprocess.TimeoutExpired:
        _terminate_codex_process_tree(proc, windows_job)
        with suppress(OSError, subprocess.TimeoutExpired):
            proc.communicate(timeout=_PROCESS_DRAIN_TIMEOUT_SECONDS)
        timeout_error = CodexModelTimeoutError(timeout)
    except (KeyboardInterrupt, SystemExit):
        _terminate_codex_process_tree(proc, windows_job)
        with suppress(OSError, subprocess.TimeoutExpired):
            proc.communicate(timeout=_PROCESS_DRAIN_TIMEOUT_SECONDS)
        raise
    finally:
        if windows_job is not None:
            windows_job.close()
    if timeout_error is not None:
        raise timeout_error from None
    return subprocess.CompletedProcess(argv, proc.returncode, stdout=stdout, stderr=stderr)


def _communicate_with_cancellation(
    proc: subprocess.Popen[str],
    argv: list[str],
    timeout: int,
    cancel_event: Any,
    windows_job: _WindowsKillJob | None,
) -> tuple[str, str]:
    """Poll a model process so batch cancellation can stop its process tree."""
    deadline = time.monotonic() + timeout
    while True:
        if cancel_event.is_set():
            _terminate_codex_process_tree(proc, windows_job)
            with suppress(OSError, subprocess.TimeoutExpired):
                proc.communicate(timeout=_PROCESS_DRAIN_TIMEOUT_SECONDS)
            raise CodexProcessCancelledError from None
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired(argv, timeout)
        try:
            return proc.communicate(timeout=min(_PROCESS_POLL_INTERVAL_SECONDS, remaining))
        except subprocess.TimeoutExpired:
            continue


class CodexBackend:
    """Run agent turns through the installed ``codex exec`` CLI."""

    default_model: str | None = None
    max_retries = 2

    def validate_params(self, params: dict[str, Any]) -> dict[str, Any]:
        authored_params = {key for key in params if not is_compiler_source_line_sidecar(key, params)}
        invalid = sorted(authored_params - (SHARED_PARAMS | CODEX_PARAMS))
        if invalid:
            raise AgentValidationError(f"{invalid[0]!r} is not valid for backend 'codex'")

        return {
            "approval_policy": validate_codex_approval_policy(params.get("approval_policy")),
            "add_dir": validate_codex_add_dirs(params.get("add_dir")),
            "profile": validate_codex_profile(params.get("profile")),
            "config": self._validate_config(params.get("config")),
            "sandbox": validate_codex_sandbox(params.get("sandbox")),
        }

    @staticmethod
    def _validate_config(value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise AgentValidationError(f"config must be a dict, got {type(value).__name__}")
        config_values = value.copy()
        for key, item in config_values.items():
            if not isinstance(key, str) or not key.strip():
                raise AgentValidationError("Codex config keys must be non-empty strings")
            _toml_value(item)
        return config_values

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
                    json.dumps(_strictify_schema(options["output_schema"]), ensure_ascii=False),
                    encoding="utf-8",
                )

            argv = self._build_argv(prompt, options, message_path, schema_path)
            started = time.monotonic()
            completed = _run_codex_process(
                argv,
                cwd=options["cwd"],
                timeout=options["timeout"],
                env=env,
                cancel_event=options.get("_cancel_event"),
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
            api_equivalent_cost_usd = self._estimate_api_equivalent_cost(parsed, options.get("model"))
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
                "api_equivalent_cost_usd": api_equivalent_cost_usd,
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
    def _estimate_api_equivalent_cost(parsed: _ParsedEvents, model: Any) -> float | None:
        """Estimate API pricing only when Codex emitted usage telemetry."""
        if not parsed.usage_available:
            return None
        return estimate_completion_cost_usd(
            model=model,
            input_tokens=parsed.usage.get("input_tokens", 0),
            output_tokens=parsed.usage.get("output_tokens", 0),
            cache_read_input_tokens=parsed.usage.get("cached_input_tokens", 0),
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
        if isinstance(exc, CodexProcessCancelledError):
            return exc
        if isinstance(exc, FileNotFoundError):
            return CodexNonRetriableError(
                "Codex CLI was not found on PATH. Install it with "
                "`npm install -g @openai/codex`, then authenticate with `codex login`."
            )
        if isinstance(exc, (CodexModelTimeoutError, subprocess.TimeoutExpired)):
            return ValueError(
                f"Codex execution timed out after {options.get('timeout', 300)} seconds. "
                "Increase timeout or split the task into smaller steps."
            )

        logger.error(
            "Codex execution failed",
            extra={
                "exception_type": type(exc).__name__,
                "returncode": exc.returncode if isinstance(exc, CodexProcessError) else None,
            },
        )
        if isinstance(exc, CodexProcessError) and self._is_auth_failure(exc):
            if options.get("use_api_key"):
                return CodexNonRetriableError(
                    "Codex authentication failed while API-key/provider billing is permitted "
                    "(`use_api_key: true`). Check `OPENAI_API_KEY`, `CODEX_API_KEY`, and any "
                    "configured profile/provider credentials. To use account authentication "
                    "instead, remove `use_api_key: true`, run `codex login`, and verify with "
                    "`codex login status`."
                )
            return CodexNonRetriableError("Codex authentication failed. Run `codex login` and retry.")
        if isinstance(exc, CodexProcessError):
            detail = _readable_failure_detail(exc.failure_messages)
            if detail:
                return ValueError(f"Codex CLI failed with exit code {exc.returncode}. Codex reported: {detail}")
            return ValueError(
                f"Codex CLI failed with exit code {exc.returncode}. "
                "Run the same Codex command directly to inspect provider diagnostics."
            )
        if isinstance(exc, CodexEventParseError):
            return ValueError(f"Codex CLI returned invalid --json output: {exc}")
        return ValueError(f"Codex execution failed after {self.max_retries} attempts ({type(exc).__name__}).")

    @staticmethod
    def _is_auth_failure(exc: CodexProcessError) -> bool:
        """Classify auth only from process diagnostics, never JSONL item output."""
        return any(_AUTH_FAILURE_PATTERN.search(text) for text in (exc.stderr, *exc.failure_messages) if text)

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
