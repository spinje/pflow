"""stdout carries only machine output while user code runs (GH #652).

A code node's own thread and a subprocess it starts write to the process's
stdout directly — neither passes through the code node's capture. Every surface
whose stdout is read by a program must keep that output parseable and send the
stray text to stderr. Real subprocesses: the contract is about file descriptors,
which in-process runners (CliRunner, in-process MCP calls) never exercise.
"""

from __future__ import annotations

import json
import queue
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.e2e

# The thread print is unflushed on purpose: it sits in the (block-buffered) sys.stdout
# until the reservation ends, which must flush it to stderr, not to the restored stdout.
# The subprocess inherits stdout (the path under test) but not stdin: under `mcp serve` on
# Windows an inherited stdin — the JSON-RPC pipe the SDK is blocked reading — hangs the
# child until the next message arrives (#657).
STRAY_CODE = """\
import subprocess, sys, threading
print("CAPTURED")
worker = threading.Thread(target=lambda: print("THREAD-STRAY"))
worker.start()
worker.join()
subprocess.run([sys.executable, "-c", "print('SUBPROC-STRAY')"], stdin=subprocess.DEVNULL, check=True)
result: str = "done"
"""

STRAY_WORKFLOW = f"""\
# Stray stdout

## Steps

### stray

Writes to stdout from places the code node does not capture.

- type: code

```python code
{STRAY_CODE}```
"""


def _clean_env(env: dict[str, str]) -> dict[str, str]:
    # PYTEST_CURRENT_TEST short-circuits production logging/startup; see tests/CLAUDE.md #10.
    return {k: v for k, v in env.items() if k != "PYTEST_CURRENT_TEST"}


def _run_pflow(args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        [sys.executable, "-m", "pflow.cli", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=_clean_env(env),
        timeout=120,
    )


def _assert_strays_on_stderr(stderr: str) -> None:
    assert "THREAD-STRAY" in stderr
    assert "SUBPROC-STRAY" in stderr


@pytest.fixture
def stray_workflow(tmp_path: Path) -> Path:
    path = tmp_path / "stray.pflow.md"
    path.write_text(STRAY_WORKFLOW, encoding="utf-8")
    return path


def test_json_document_stays_parseable(stray_workflow: Path, prepared_subprocess_env: dict[str, str]) -> None:
    result = _run_pflow(["--output-format", "json", str(stray_workflow)], prepared_subprocess_env)

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["result"] == {"result": "done"}
    _assert_strays_on_stderr(result.stderr)


def test_text_result_piped_is_only_the_result(stray_workflow: Path, prepared_subprocess_env: dict[str, str]) -> None:
    result = _run_pflow([str(stray_workflow)], prepared_subprocess_env)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "done"
    _assert_strays_on_stderr(result.stderr)


def test_probe_json_stays_parseable(prepared_subprocess_env: dict[str, str]) -> None:
    result = _run_pflow(["probe", "code", f"code={STRAY_CODE}", "--output-format", "json"], prepared_subprocess_env)

    assert result.returncode == 0, result.stderr
    outputs = json.loads(result.stdout)["outputs"]
    assert outputs["result"] == "done"
    # The code node's own print is still captured per execution, not diverted.
    assert outputs["stdout"] == "CAPTURED\n"
    assert "CAPTURED" not in result.stderr
    _assert_strays_on_stderr(result.stderr)


def _drain(stream: Any, sink: queue.Queue[str]) -> None:
    for line in stream:
        sink.put(line)


def test_mcp_stdio_protocol_stays_json_rpc(stray_workflow: Path, prepared_subprocess_env: dict[str, str]) -> None:
    proc = subprocess.Popen(  # noqa: S603
        [sys.executable, "-m", "pflow.cli", "mcp", "serve"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        env=_clean_env(prepared_subprocess_env),
    )
    assert proc.stdin is not None
    stdout_lines: queue.Queue[str] = queue.Queue()
    stderr_lines: queue.Queue[str] = queue.Queue()
    readers = [
        threading.Thread(target=_drain, args=(proc.stdout, stdout_lines), daemon=True),
        threading.Thread(target=_drain, args=(proc.stderr, stderr_lines), daemon=True),
    ]
    for reader in readers:
        reader.start()

    messages = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "t", "version": "0"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "workflow_execute", "arguments": {"workflow": str(stray_workflow)}},
        },
    ]
    try:
        for message in messages:
            proc.stdin.write(json.dumps(message) + "\n")
        proc.stdin.flush()

        responses: dict[int, dict[str, Any]] = {}
        while 2 not in responses:
            line = stdout_lines.get(timeout=120)
            decoded = json.loads(line)  # every protocol line must be JSON-RPC
            if "id" in decoded:
                responses[decoded["id"]] = decoded
        proc.stdin.close()
        assert proc.wait(timeout=30) == 0
    finally:
        proc.kill()
    for reader in readers:
        reader.join(timeout=10)

    tool_text = responses[2]["result"]["content"][0]["text"]
    assert tool_text.startswith("✓"), tool_text
    for line in list(stdout_lines.queue):  # anything written after the response
        json.loads(line)
    _assert_strays_on_stderr("".join(stderr_lines.queue))
