"""Contract tests for the ``codex exec`` agent backend."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

import pflow.nodes.agent.codex_backend as codex_module
from pflow.nodes.agent.agent_node import AgentNode
from pflow.nodes.agent.backend import AgentResult
from pflow.nodes.agent.codex_backend import (
    CodexBackend,
    CodexEventParseError,
    CodexNonRetriableError,
    CodexProcessError,
    _AuthClass,
    _build_child_env,
    _classify_login_status,
    _toml_value,
)
from pflow.runtime.workflow_trace import WorkflowTraceCollector

THREAD_ID = "019f5bba-9c03-7220-88ac-4c8cc0e63e1d"
SUCCESS_JSONL = "\n".join([
    f'{{"type":"thread.started","thread_id":"{THREAD_ID}"}}',
    '{"type":"turn.started"}',
    '{"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"hi"}}',
    '{"type":"turn.completed","usage":{"input_tokens":14653,"cached_input_tokens":9984,'
    '"output_tokens":5,"reasoning_output_tokens":2}}',
])


def _options(tmp_path: Path, **overrides: Any) -> dict[str, Any]:
    options: dict[str, Any] = {
        "backend": "codex",
        "cwd": str(tmp_path),
        "model": None,
        "output_schema": None,
        "resume": None,
        "timeout": 30,
        "system_prompt": "",
        "schema_retries": 1,
        "use_api_key": False,
        "approval_policy": None,
        "add_dir": [],
        "profile": None,
        "config": {},
        "sandbox": "workspace-write",
    }
    options.update(overrides)
    return options


def _install_fake_run(
    monkeypatch: pytest.MonkeyPatch,
    *,
    stdout: str = SUCCESS_JSONL,
    stderr: str = "",
    returncode: int = 0,
    messages: list[str] | None = None,
    status_stdout: str = "",
    status_stderr: str = "Logged in using ChatGPT",
    status_returncode: int = 0,
    status_exception: Exception | None = None,
) -> list[tuple[list[str], dict[str, Any]]]:
    calls: list[tuple[list[str], dict[str, Any]]] = []
    queued_messages = list(messages or ["hello from codex"])

    def fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append((argv, kwargs))
        if argv == ["codex", "login", "status"]:
            if status_exception is not None:
                raise status_exception
            return subprocess.CompletedProcess(
                argv,
                status_returncode,
                stdout=status_stdout,
                stderr=status_stderr,
            )
        message_path = Path(argv[argv.index("--output-last-message") + 1])
        message = queued_messages.pop(0) if queued_messages else "hello from codex"
        message_path.write_text(message, encoding="utf-8")
        return subprocess.CompletedProcess(argv, returncode, stdout=stdout, stderr=stderr)

    monkeypatch.setattr(codex_module.subprocess, "run", fake_run)
    return calls


def _model_calls(calls: list[tuple[list[str], dict[str, Any]]]) -> list[tuple[list[str], dict[str, Any]]]:
    return [call for call in calls if call[0][:2] == ["codex", "exec"]]


def _status_calls(calls: list[tuple[list[str], dict[str, Any]]]) -> list[tuple[list[str], dict[str, Any]]]:
    return [call for call in calls if call[0] == ["codex", "login", "status"]]


class TestCodexParamValidation:
    def test_accepts_shared_inputs_and_applies_backend_defaults(self) -> None:
        prepared = CodexBackend().validate_params({
            "backend": "codex",
            "prompt": "test",
            "inputs": {"x": 1},
            "use_api_key": True,
        })

        assert prepared == {
            "approval_policy": None,
            "add_dir": [],
            "profile": None,
            "config": {},
            "sandbox": "workspace-write",
        }

    def test_agent_node_prepares_shared_use_api_key_default(self, tmp_path: Path) -> None:
        node = AgentNode()
        node.set_params({"backend": "codex", "prompt": "test", "cwd": str(tmp_path)})

        prepared = node.prep({})

        assert prepared["use_api_key"] is False

    def test_rejects_claude_only_param_before_cli_availability(self) -> None:
        with pytest.raises(ValueError, match="'max_turns' is not valid for backend 'codex'"):
            CodexBackend().validate_params({"backend": "codex", "prompt": "test", "max_turns": 2})

    @pytest.mark.parametrize("value", ["on-failure", "always", 1, {"granular": {}}])
    def test_rejects_unsupported_approval_policy(self, value: Any) -> None:
        with pytest.raises(ValueError, match="approval_policy must be one of"):
            CodexBackend().validate_params({"backend": "codex", "prompt": "test", "approval_policy": value})

    @pytest.mark.parametrize("value", ["danger-full-access", "readonly", {}, None])
    def test_rejects_invalid_explicit_sandbox(self, value: Any) -> None:
        params = {"backend": "codex", "prompt": "test", "sandbox": value}
        if value is None:
            # Explicit null resolves to the documented backend default.
            assert CodexBackend().validate_params(params)["sandbox"] == "workspace-write"
        else:
            with pytest.raises(ValueError, match="sandbox must be one of"):
                CodexBackend().validate_params(params)

    @pytest.mark.parametrize(
        ("params", "error"),
        [
            ({"add_dir": "tmp"}, "add_dir must be a list"),
            ({"add_dir": [""]}, "add_dir must be a list"),
            ({"profile": ""}, "profile must be a non-empty string"),
            ({"config": []}, "config must be a dict"),
            ({"config": {"value": None}}, "Codex config values must be TOML-compatible"),
        ],
    )
    def test_rejects_invalid_backend_param_shapes(self, params: dict[str, Any], error: str) -> None:
        with pytest.raises((TypeError, ValueError), match=error):
            CodexBackend().validate_params({"backend": "codex", "prompt": "test", **params})

    def test_toml_serializer_handles_nested_cli_values_without_shell_quoting(self) -> None:
        assert _toml_value('line 1\n"quoted"') == '"line 1\\n\\"quoted\\""'
        assert _toml_value(True) == "true"
        assert _toml_value(["a", False, 3]) == '["a", false, 3]'
        assert _toml_value({"plain": "x", "spaced key": [1, 2]}) == ('{ plain = "x", "spaced key" = [1, 2] }')


class TestCodexArgvAndParsing:
    def test_initial_run_builds_full_argv_and_normalizes_usage(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        extra_a = tmp_path / "extra-a"
        extra_b = tmp_path / "extra-b"
        calls = _install_fake_run(monkeypatch)
        options = _options(
            tmp_path,
            model="gpt-test-codex",
            sandbox="full-access",
            add_dir=[str(extra_a), str(extra_b)],
            approval_policy="never",
            profile="ci",
            config={
                "feature.enabled": True,
                "items": ["a", 2],
                "nested": {"mode": "fast"},
                "approval_policy": "untrusted",
                "developer_instructions": "config fallback",
                "model_provider": "custom-provider",
            },
            system_prompt='Be strict.\nReturn "only" the answer.',
        )

        result = CodexBackend().run("Say hi", options)

        assert [call[0] for call in calls] == [["codex", "login", "status"], _model_calls(calls)[0][0]]
        argv, kwargs = _model_calls(calls)[0]
        assert argv[:5] == ["codex", "exec", "--profile", "ci", "--skip-git-repo-check"]
        assert argv[-2:] == ["--", "Say hi"]
        assert argv[argv.index("--model") + 1] == "gpt-test-codex"
        assert argv[argv.index("--sandbox") + 1] == "danger-full-access"
        assert argv[argv.index("--cd") + 1] == str(tmp_path)
        assert [argv[index + 1] for index, item in enumerate(argv) if item == "--add-dir"] == [
            str(extra_a),
            str(extra_b),
        ]
        config_values = [argv[index + 1] for index, item in enumerate(argv) if item == "--config"]
        assert config_values == [
            "feature.enabled=true",
            'items=["a", 2]',
            'nested={ mode = "fast" }',
            'approval_policy="untrusted"',
            'developer_instructions="config fallback"',
            'model_provider="custom-provider"',
            'approval_policy="never"',
            'developer_instructions="Be strict.\\nReturn \\"only\\" the answer."',
            'model_provider="openai"',
        ]
        assert kwargs["cwd"] == str(tmp_path)
        assert kwargs["stdin"] is subprocess.DEVNULL
        assert kwargs["capture_output"] is True
        assert kwargs["text"] is True
        assert kwargs["encoding"] == "utf-8"
        assert kwargs["timeout"] == 30
        assert kwargs["check"] is False
        assert kwargs["env"] is _status_calls(calls)[0][1]["env"]
        assert result.result_text == "hello from codex"
        assert result.metadata == {
            "input_tokens": 14653,
            "uncached_input_tokens": 4669,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 9984,
            "input_token_accounting": "total_includes_cache",
            "output_tokens": 5,
            "reasoning_output_tokens": 2,
            "total_tokens": 14658,
            "cost_usd": None,
            "duration_ms": result.metadata["duration_ms"],
            "num_turns": 1,
            "session_id": THREAD_ID,
            "usage_available": True,
        }
        assert isinstance(result.metadata["duration_ms"], int)
        provider_values = [value for value in config_values if value.startswith("model_provider=")]
        assert provider_values[-1] == 'model_provider="openai"'

    def test_schema_file_is_written_and_final_message_is_the_only_result_source(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        schema = {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]}
        inspected_schema: list[dict[str, Any]] = []

        def fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            if argv == ["codex", "login", "status"]:
                return subprocess.CompletedProcess(argv, 0, stdout="", stderr="Logged in using ChatGPT")
            schema_path = Path(argv[argv.index("--output-schema") + 1])
            inspected_schema.append(__import__("json").loads(schema_path.read_text(encoding="utf-8")))
            message_path = Path(argv[argv.index("--output-last-message") + 1])
            message_path.write_text('{"answer":"from-file"}', encoding="utf-8")
            stdout = SUCCESS_JSONL.replace('"text":"hi"', '"text":"wrong-jsonl-message"')
            return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")

        monkeypatch.setattr(codex_module.subprocess, "run", fake_run)

        result = CodexBackend().run("Return JSON", _options(tmp_path, output_schema=schema))

        assert inspected_schema == [schema]
        assert result.result_text == '{"answer":"from-file"}'
        assert result.structured_output == {"answer": "from-file"}

    def test_resume_uses_parent_profile_and_resume_specific_flags(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        calls = _install_fake_run(monkeypatch)
        options = _options(
            tmp_path,
            resume=THREAD_ID,
            profile="team",
            sandbox="workspace-write",
            add_dir=[str(tmp_path / "extra")],
            system_prompt="Continue carefully",
            config={"model_provider": "custom-provider"},
        )

        CodexBackend().run("Continue", options)

        argv = _model_calls(calls)[0][0]
        assert argv[:5] == ["codex", "exec", "--profile", "team", "resume"]
        assert argv[-3:] == ["--", THREAD_ID, "Continue"]
        assert "--sandbox" not in argv
        assert "--cd" not in argv
        assert "--add-dir" not in argv
        config_values = [argv[index + 1] for index, item in enumerate(argv) if item == "--config"]
        assert config_values == [
            'model_provider="custom-provider"',
            'developer_instructions="Continue carefully"',
            'model_provider="openai"',
            'sandbox_mode="workspace-write"',
        ]
        provider_values = [value for value in config_values if value.startswith("model_provider=")]
        assert provider_values[-1] == 'model_provider="openai"'

    def test_resume_without_thread_started_fails_instead_of_inventing_id(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        stdout = "\n".join(SUCCESS_JSONL.splitlines()[1:])
        _install_fake_run(monkeypatch, stdout=stdout)

        with pytest.raises(CodexProcessError, match=r"without a thread\.started thread_id"):
            CodexBackend().run("Continue", _options(tmp_path, resume=THREAD_ID))

    def test_parser_aggregates_turns_usage_and_command_items(self) -> None:
        stdout = "\n".join([
            f'{{"type":"thread.started","thread_id":"{THREAD_ID}"}}',
            '{"type":"item.completed","item":{"type":"command_execution","command":"echo hi",'
            '"aggregated_output":"hi\\n","exit_code":0,"status":"completed"}}',
            '{"type":"turn.completed","usage":{"input_tokens":10,"cached_input_tokens":4,'
            '"output_tokens":2,"reasoning_output_tokens":1}}',
            '{"type":"turn.completed","usage":{"input_tokens":20,"cached_input_tokens":6,'
            '"output_tokens":3,"reasoning_output_tokens":2}}',
        ])

        parsed = CodexBackend._parse_events(stdout)

        assert parsed.num_turns == 2
        assert parsed.usage == {
            "input_tokens": 30,
            "cached_input_tokens": 10,
            "output_tokens": 5,
            "reasoning_output_tokens": 3,
        }
        assert parsed.tool_uses == [{"name": "echo hi", "input": "hi\n", "exit_code": 0, "status": "completed"}]

    def test_missing_usage_events_still_records_one_agent_turn(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _install_fake_run(monkeypatch, stdout=f'{{"type":"thread.started","thread_id":"{THREAD_ID}"}}')

        result = CodexBackend().run("test", _options(tmp_path))

        assert result.metadata["num_turns"] == 1
        assert result.metadata["usage_available"] is False
        assert result.metadata["input_tokens"] == 0

    def test_missing_last_message_file_is_an_execution_failure(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        def fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            if argv == ["codex", "login", "status"]:
                return subprocess.CompletedProcess(argv, 0, stdout="", stderr="Logged in using ChatGPT")
            return subprocess.CompletedProcess(argv, 0, stdout=SUCCESS_JSONL, stderr="")

        monkeypatch.setattr(codex_module.subprocess, "run", fake_run)

        with pytest.raises(CodexProcessError, match="without writing --output-last-message"):
            CodexBackend().run("test", _options(tmp_path))

    @pytest.mark.parametrize("stdout", ["not json", "[]"])
    def test_parser_rejects_malformed_jsonl(self, stdout: str) -> None:
        with pytest.raises(CodexEventParseError, match="Invalid Codex JSONL event on line 1"):
            CodexBackend._parse_events(stdout)

    @pytest.mark.parametrize(
        "failure_event",
        [
            '{"type":"turn.failed","error":{"message":"schema rejected"}}',
            '{"type":"error","message":"transport failed"}',
        ],
    )
    def test_failure_event_raises_even_when_process_exit_is_zero(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, failure_event: str
    ) -> None:
        _install_fake_run(monkeypatch, stdout=failure_event)

        with pytest.raises(CodexProcessError, match=r"schema rejected|transport failed"):
            CodexBackend().run("test", _options(tmp_path))


class TestCodexAccountAuthGuard:
    def test_child_env_is_copied_and_sanitized_only_in_safe_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "openai-secret")
        monkeypatch.setenv("CODEX_API_KEY", "codex-secret")
        monkeypatch.setenv("KEEP_ME", "visible")

        safe_env = _build_child_env(False)
        opted_in_env = _build_child_env(True)

        assert "OPENAI_API_KEY" not in safe_env
        assert "CODEX_API_KEY" not in safe_env
        assert safe_env["KEEP_ME"] == "visible"
        assert opted_in_env["OPENAI_API_KEY"] == "openai-secret"
        assert opted_in_env["CODEX_API_KEY"] == "codex-secret"
        assert os.environ["OPENAI_API_KEY"] == "openai-secret"
        assert os.environ["CODEX_API_KEY"] == "codex-secret"

    @pytest.mark.parametrize(
        ("stdout", "stderr", "expected"),
        [
            ("Logged in using ChatGPT\n", "", _AuthClass.ACCOUNT),
            ("", "warning: ignored\nLogged in using access token\n", _AuthClass.ACCOUNT),
            ("", "Logged in using an API key - sk-...abcd\n", _AuthClass.API_KEY),
            ("Logged in using personal access token", "", _AuthClass.UNSUPPORTED_CREDENTIAL),
            ("Logged in using Amazon Bedrock API key", "", _AuthClass.UNSUPPORTED_CREDENTIAL),
            ("Not logged in", "", _AuthClass.LOGGED_OUT),
            ("warning only", "", _AuthClass.UNKNOWN),
            ("Logged in using ChatGPT", "Not logged in", _AuthClass.UNKNOWN),
        ],
    )
    def test_login_status_classification(self, stdout: str, stderr: str, expected: _AuthClass) -> None:
        assert _classify_login_status(stdout, stderr) is expected

    def test_safe_mode_reuses_one_sanitized_env_without_mutating_parent(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "openai-secret")
        monkeypatch.setenv("CODEX_API_KEY", "codex-secret")
        calls = _install_fake_run(monkeypatch, status_stderr="warning: config\nLogged in using ChatGPT\n")

        result = CodexBackend().run("Say hi", _options(tmp_path))

        assert result.result_text == "hello from codex"
        assert len(_status_calls(calls)) == 1
        assert len(_model_calls(calls)) == 1
        status_env = _status_calls(calls)[0][1]["env"]
        model_env = _model_calls(calls)[0][1]["env"]
        assert status_env is model_env
        assert "OPENAI_API_KEY" not in status_env
        assert "CODEX_API_KEY" not in status_env
        assert os.environ["OPENAI_API_KEY"] == "openai-secret"
        assert os.environ["CODEX_API_KEY"] == "codex-secret"
        assert _status_calls(calls)[0][1] == {
            "cwd": str(tmp_path),
            "stdin": subprocess.DEVNULL,
            "capture_output": True,
            "text": True,
            "encoding": "utf-8",
            "timeout": 10,
            "check": False,
            "env": status_env,
        }

    @pytest.mark.parametrize(
        ("status_stdout", "status_stderr"),
        [
            ("Logged in using ChatGPT", ""),
            ("Logged in using access token", "warning: harmless"),
        ],
    )
    def test_account_status_on_stdout_is_accepted(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        status_stdout: str,
        status_stderr: str,
    ) -> None:
        calls = _install_fake_run(
            monkeypatch,
            status_stdout=status_stdout,
            status_stderr=status_stderr,
        )

        CodexBackend().run("test", _options(tmp_path))

        assert len(_model_calls(calls)) == 1

    @pytest.mark.parametrize(
        ("status_stdout", "status_stderr", "status_returncode", "expected"),
        [
            ("", "Logged in using an API key - sk-...SECRET-SUFFIX", 0, "use_api_key: true"),
            ("Logged in using personal access token", "", 0, "unsupported credential"),
            ("Logged in using Amazon Bedrock API key", "", 0, "unsupported credential"),
            ("Not logged in", "", 1, "codex login"),
            ("", "warning only", 0, "not recognized"),
            ("Logged in using future auth", "", 0, "not recognized"),
            ("Logged in using ChatGPT", "Not logged in", 0, "not recognized"),
        ],
    )
    def test_safe_mode_fails_closed_without_leaking_status_text(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        status_stdout: str,
        status_stderr: str,
        status_returncode: int,
        expected: str,
    ) -> None:
        calls = _install_fake_run(
            monkeypatch,
            status_stdout=status_stdout,
            status_stderr=status_stderr,
            status_returncode=status_returncode,
        )

        with pytest.raises(CodexNonRetriableError) as exc_info:
            CodexBackend().run("test", _options(tmp_path))

        message = str(exc_info.value)
        assert exc_info.value.retriable is False
        assert expected in message
        assert "SECRET-SUFFIX" not in message
        assert status_stdout not in message or not status_stdout
        assert status_stderr not in message or not status_stderr
        assert len(_status_calls(calls)) == 1
        assert _model_calls(calls) == []

    def test_opt_in_skips_status_preserves_keys_and_provider_configuration(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "openai-secret")
        monkeypatch.setenv("CODEX_API_KEY", "codex-secret")
        calls = _install_fake_run(monkeypatch)

        CodexBackend().run(
            "test",
            _options(
                tmp_path,
                use_api_key=True,
                config={"model_provider": "custom-provider"},
            ),
        )

        assert _status_calls(calls) == []
        assert len(_model_calls(calls)) == 1
        argv, kwargs = _model_calls(calls)[0]
        assert kwargs["env"]["OPENAI_API_KEY"] == "openai-secret"
        assert kwargs["env"]["CODEX_API_KEY"] == "codex-secret"
        provider_values = [argv[index + 1] for index, item in enumerate(argv) if item == "--config"]
        assert [value for value in provider_values if value.startswith("model_provider=")] == [
            'model_provider="custom-provider"'
        ]

    @pytest.mark.parametrize(
        ("status_exception", "expected"),
        [
            (FileNotFoundError("codex"), "Codex CLI was not found"),
            (
                subprocess.TimeoutExpired(["codex", "login", "status"], 10),
                "authentication check timed out",
            ),
        ],
    )
    def test_status_launch_failures_are_non_retriable(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        status_exception: Exception,
        expected: str,
    ) -> None:
        calls = _install_fake_run(monkeypatch, status_exception=status_exception)

        with pytest.raises(CodexNonRetriableError, match=expected) as exc_info:
            CodexBackend().run("test", _options(tmp_path))

        assert exc_info.value.retriable is False
        assert len(_status_calls(calls)) == 1
        assert _model_calls(calls) == []

    def test_status_timeout_does_not_retain_partial_secret_output(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        secret = "sk-timeout-output-must-not-leak"  # noqa: S105 - redaction sentinel
        timeout = subprocess.TimeoutExpired(
            ["codex", "login", "status"],
            10,
            output=f"warning\n{secret}",
            stderr=f"Logged in using an API key - {secret}",
        )
        _install_fake_run(monkeypatch, status_exception=timeout)

        with pytest.raises(CodexNonRetriableError) as exc_info:
            CodexBackend().run("test", _options(tmp_path))

        error = exc_info.value
        assert secret not in str(error)
        assert error.__cause__ is None
        assert error.__context__ is None


class TestCodexAgentLifecycle:
    def test_real_agent_node_stores_text_usage_session_and_reasoning(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _install_fake_run(monkeypatch)
        node = AgentNode()
        node.set_params({"backend": "codex", "prompt": "Say hi", "cwd": str(tmp_path), "timeout": 30})
        shared: dict[str, Any] = {}

        action = node.run(shared)

        assert action == "default"
        assert shared["result"] == "hello from codex"
        assert shared["llm_usage"] == {
            "model": None,
            "input_tokens": 14653,
            "uncached_input_tokens": 4669,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 9984,
            "input_token_accounting": "total_includes_cache",
            "output_tokens": 5,
            "reasoning_output_tokens": 2,
            "total_tokens": 14658,
            "cost_usd": None,
            "duration_ms": shared["llm_usage"]["duration_ms"],
            "num_turns": 1,
            "session_id": THREAD_ID,
        }

    def test_structured_output_success_runs_through_agent_node(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _install_fake_run(monkeypatch, messages=['{"answer":"yes"}'])
        node = AgentNode()
        node.set_params({
            "backend": "codex",
            "prompt": "Answer",
            "cwd": str(tmp_path),
            "timeout": 30,
            "output_schema": {
                "type": "object",
                "properties": {"answer": {"type": "string"}},
                "required": ["answer"],
            },
        })
        shared: dict[str, Any] = {}

        assert node.run(shared) == "default"
        assert shared["result"] == {"answer": "yes"}
        assert "_schema_error" not in shared

    def test_malformed_structured_output_retries_by_thread_then_soft_fails(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        calls = _install_fake_run(monkeypatch, messages=["not json", "still not json"])
        node = AgentNode()
        node.node_id = "review"
        node.set_params({
            "backend": "codex",
            "prompt": "Answer",
            "cwd": str(tmp_path),
            "timeout": 30,
            "output_schema": {
                "type": "object",
                "properties": {"answer": {"type": "string"}},
                "required": ["answer"],
            },
        })
        shared: dict[str, Any] = {}

        assert node.run(shared) == "default"
        assert [call[0][:2] for call in calls] == [
            ["codex", "login"],
            ["codex", "exec"],
            ["codex", "login"],
            ["codex", "exec"],
        ]
        assert "resume" in _model_calls(calls)[1][0]
        assert shared["result"] == "still not json"
        assert shared["__warnings__"]["review"]["kind"] == "agent.schema_not_satisfied_after_retries"
        assert len(shared["llm_usage"]["retries"]) == 1
        aggregated = WorkflowTraceCollector.aggregate_llm_usage_with_retries(shared["llm_usage"])
        assert aggregated["reasoning_output_tokens"] == 4
        assert aggregated["input_tokens"] == 29306

    def test_missing_thread_prevents_schema_retry_and_soft_fails(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        stdout = "\n".join(SUCCESS_JSONL.splitlines()[1:])
        calls = _install_fake_run(monkeypatch, stdout=stdout, messages=["not json"])
        node = AgentNode()
        node.node_id = "review"
        node.set_params({
            "backend": "codex",
            "prompt": "Answer",
            "cwd": str(tmp_path),
            "timeout": 30,
            "output_schema": {"type": "object", "properties": {"answer": {"type": "string"}}},
        })
        shared: dict[str, Any] = {}

        assert node.run(shared) == "default"
        assert len(_status_calls(calls)) == 1
        assert len(_model_calls(calls)) == 1
        assert shared["result"] == "not json"
        assert shared["__warnings__"]["review"]["kind"] == "agent.schema_not_satisfied"

    def test_failed_second_preflight_keeps_first_result_without_resume_exec(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        calls: list[tuple[list[str], dict[str, Any]]] = []
        status_count = 0

        def fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            nonlocal status_count
            calls.append((argv, kwargs))
            if argv == ["codex", "login", "status"]:
                status_count += 1
                stderr = (
                    "Logged in using ChatGPT" if status_count == 1 else "Logged in using an API key - sk-...DO-NOT-LEAK"
                )
                return subprocess.CompletedProcess(argv, 0, stdout="", stderr=stderr)
            message_path = Path(argv[argv.index("--output-last-message") + 1])
            message_path.write_text("not json", encoding="utf-8")
            return subprocess.CompletedProcess(argv, 0, stdout=SUCCESS_JSONL, stderr="")

        monkeypatch.setattr(codex_module.subprocess, "run", fake_run)
        node = AgentNode()
        node.node_id = "review"
        node.set_params({
            "backend": "codex",
            "prompt": "Answer",
            "cwd": str(tmp_path),
            "timeout": 30,
            "output_schema": {
                "type": "object",
                "properties": {"answer": {"type": "string"}},
                "required": ["answer"],
            },
        })
        shared: dict[str, Any] = {}

        assert node.run(shared) == "default"
        assert [call[0][:2] for call in calls] == [
            ["codex", "login"],
            ["codex", "exec"],
            ["codex", "login"],
        ]
        assert shared["result"] == "not json"
        assert shared["__warnings__"]["review"]["kind"] == "agent.schema_not_satisfied_after_retries"
        assert "DO-NOT-LEAK" not in shared["_schema_error"]
        assert "retries" not in shared["llm_usage"]


class TestCodexErrors:
    def test_missing_cli_translation_is_actionable_and_non_retriable(self, tmp_path: Path) -> None:
        translated = CodexBackend().translate_error(FileNotFoundError("codex"), _options(tmp_path))

        assert isinstance(translated, CodexNonRetriableError)
        assert translated.retriable is False
        assert "npm install -g @openai/codex" in str(translated)
        assert "codex login" in str(translated)

    def test_auth_translation_is_actionable_and_non_retriable(self, tmp_path: Path) -> None:
        exc = CodexProcessError(
            argv=["codex"],
            returncode=1,
            stdout="",
            stderr="401 Unauthorized: login required",
        )

        translated = CodexBackend().translate_error(exc, _options(tmp_path))

        assert isinstance(translated, CodexNonRetriableError)
        assert translated.retriable is False
        assert "codex login" in str(translated)

    def test_auth_translation_in_opt_in_mode_names_effective_credentials(self, tmp_path: Path) -> None:
        exc = CodexProcessError(
            argv=["codex"],
            returncode=1,
            stdout="",
            stderr="401 Unauthorized",
        )

        translated = CodexBackend().translate_error(exc, _options(tmp_path, use_api_key=True))

        assert isinstance(translated, CodexNonRetriableError)
        assert translated.retriable is False
        message = str(translated)
        assert "API-key/provider billing is permitted" in message
        assert "OPENAI_API_KEY" in message
        assert "CODEX_API_KEY" in message
        assert "profile/provider credentials" in message
        assert "remove `use_api_key: true`" in message
        assert "codex login status" in message

    def test_agent_fallback_raises_backend_translation(self, tmp_path: Path) -> None:
        node = AgentNode()
        node.set_params({"backend": "codex", "prompt": "test", "cwd": str(tmp_path)})
        prepared = node.prep({})

        with pytest.raises(CodexNonRetriableError, match="Codex CLI was not found"):
            node.exec_fallback(prepared, FileNotFoundError("codex"))

    def test_agent_node_preserves_preflight_non_retriable_error_without_retry(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        calls = _install_fake_run(
            monkeypatch,
            status_stderr="Logged in using an API key - sk-...DO-NOT-LEAK",
        )
        node = AgentNode()
        node.wait = 0
        node.set_params({"backend": "codex", "prompt": "test", "cwd": str(tmp_path)})

        with pytest.raises(CodexNonRetriableError, match="use_api_key") as exc_info:
            node.run({})

        assert exc_info.value.retriable is False
        assert "DO-NOT-LEAK" not in str(exc_info.value)
        assert len(_status_calls(calls)) == 1
        assert _model_calls(calls) == []

    def test_nonzero_exit_preserves_stderr(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        _install_fake_run(monkeypatch, returncode=2, stderr="bad config")

        with pytest.raises(CodexProcessError) as exc_info:
            CodexBackend().run("test", _options(tmp_path))

        translated = CodexBackend().translate_error(exc_info.value, _options(tmp_path))
        assert isinstance(translated, ValueError)
        assert "exit code 2" in str(translated)
        assert "bad config" in str(translated)

    def test_nonzero_exit_preserves_stderr_when_stdout_is_not_json(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _install_fake_run(monkeypatch, stdout="plain failure", returncode=2, stderr="login required")

        with pytest.raises(CodexProcessError) as exc_info:
            CodexBackend().run("test", _options(tmp_path))

        translated = CodexBackend().translate_error(exc_info.value, _options(tmp_path))
        assert isinstance(translated, CodexNonRetriableError)
        assert "codex login" in str(translated)

    def test_timeout_translation_names_configured_limit(self, tmp_path: Path) -> None:
        exc = subprocess.TimeoutExpired(["codex"], 45)

        translated = CodexBackend().translate_error(exc, _options(tmp_path, timeout=45))

        assert isinstance(translated, ValueError)
        assert "timed out after 45 seconds" in str(translated)

    def test_continuation_requires_session_id(self, tmp_path: Path) -> None:
        backend = CodexBackend()
        options = _options(tmp_path)

        assert backend.continuation_options(AgentResult(), options) is None
        continuation = backend.continuation_options(AgentResult(metadata={"session_id": THREAD_ID}), options)
        assert continuation is not None
        assert continuation["resume"] == THREAD_ID


@pytest.mark.e2e
@pytest.mark.skipif(shutil.which("codex") is None, reason="Codex CLI is not installed")
def test_real_codex_cli_smoke(tmp_path: Path) -> None:
    """Paid real-surface smoke: subscription auth, JSONL, final file, and usage."""
    backend = CodexBackend()
    options = _options(tmp_path, timeout=150, sandbox="read-only")

    result = backend.run("Reply with ONLY the text PFLOW_CODEX_OK.", options)

    assert result.result_text.strip() == "PFLOW_CODEX_OK"
    assert result.metadata["session_id"]
    assert result.metadata["num_turns"] >= 1
    assert result.metadata["input_tokens"] > 0
