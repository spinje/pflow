"""Tests for ``pflow ui`` — the Starlette server, its endpoints, and the CLI.

Covers the three ``/api/graph`` failure arms (H2: 400 missing param, 422
resolution/validation failure, 500 build/render bug → never a 200-with-empty-
graph), the catalog endpoint, the ``uv tool install 'pflow-cli[ui]'`` hint when the extra
is absent (H4), and the lazy-import boundary that keeps the base CLI loading
without the web stack.

Implementation: src/pflow/ui/server.py, src/pflow/cli/commands/ui.py
"""

from __future__ import annotations

import asyncio
import datetime
import json
import socket
import sys
from pathlib import Path
from unittest.mock import patch
from urllib.parse import unquote

import pytest
from click.testing import CliRunner
from starlette.testclient import TestClient

from pflow.cli.commands.ui import ui_cmd
from pflow.core.workflow.manager import WorkflowManager
from pflow.runtime.workflow_trace import format_trace_filename
from pflow.ui.server import _json, create_app
from tests.shared.markdown_utils import ir_to_markdown, write_workflow_file


def _local(*args: object, **kwargs: object) -> TestClient:
    """A TestClient with a loopback Host — the ``_LoopbackOnly`` guard 403s TestClient's default
    ``testserver`` Host (a real browser/CLI on the loopback server always sends a loopback Host)."""
    kwargs.setdefault("base_url", "http://127.0.0.1")
    return TestClient(*args, **kwargs)  # type: ignore[arg-type]


_VALID_IR = {
    "nodes": [
        {"id": "greet", "type": "shell", "params": {"command": "echo hello"}},
        {"id": "done", "type": "shell", "params": {"command": "echo done"}},
    ],
    "edges": [{"from": "greet", "to": "done"}],
}


def _save_workflow(name: str, *, description: str | None = None) -> None:
    """Materialize a saved workflow in the (isolated) registry directory."""
    manager = WorkflowManager()
    wf_dir = manager.workflows_dir / name
    wf_dir.mkdir(parents=True, exist_ok=True)
    write_workflow_file(_VALID_IR, wf_dir / f"{name}.pflow.md", title=name, description=description)


class TestCatalogEndpoint:
    def test_empty_catalog_returns_json_list(self) -> None:
        """A clean registry yields an empty JSON array (200)."""
        client = _local(create_app())
        response = client.get("/api/catalog")
        assert response.status_code == 200
        assert response.json() == []

    def test_catalog_lists_saved_workflows_without_ir(self) -> None:
        """A saved workflow appears with name/description/path and no ``ir``."""
        _save_workflow("demo", description="A demo workflow")
        client = _local(create_app())
        response = client.get("/api/catalog")

        assert response.status_code == 200
        items = response.json()
        assert len(items) == 1
        entry = items[0]
        assert entry["name"] == "demo"
        assert entry["description"] == "A demo workflow"
        assert entry["path"].endswith("demo.pflow.md")
        assert "ir" not in entry


class TestGraphEndpoint:
    def test_valid_workflow_returns_react_flow_payload(self, tmp_path: Path) -> None:
        """A valid workflow renders to a JSON payload with nodes/edges/groups."""
        workflow_path = tmp_path / "wf.pflow.md"
        write_workflow_file(_VALID_IR, workflow_path)

        client = _local(create_app())
        response = client.get("/api/graph", params={"workflow": str(workflow_path)})

        assert response.status_code == 200
        payload = response.json()
        assert set(payload) >= {"nodes", "edges", "groups"}
        # The two shell nodes survive into the contract.
        node_kinds = {n["kind"] for n in payload["nodes"]}
        assert "shell" in node_kinds
        # Every edge endpoint resolves to an emitted node id (contract integrity).
        node_ids = {n["id"] for n in payload["nodes"]}
        for edge in payload["edges"]:
            assert edge["source"] in node_ids
            assert edge["target"] in node_ids
        # The registry's declared output types ride the payload, scoped to the
        # kinds present (the frontend's last type fallback on output rows).
        assert payload["kind_output_types"]["shell"]["stdout"] == "str"
        assert set(payload["kind_output_types"]) <= node_kinds

    def test_missing_workflow_param_is_400(self) -> None:
        """No ``workflow`` query param → 400 with a structured error body."""
        client = _local(create_app())
        response = client.get("/api/graph")
        assert response.status_code == 400
        assert response.json()["errors"][0]["message"]

    def test_invalid_workflow_is_422_not_500(self, tmp_path: Path) -> None:
        """A workflow that fails validation → 422 with diagnostics, never a 500."""
        bad_ir = {"nodes": [{"id": "bad", "type": "nonexistent_type_xyz", "params": {}}], "edges": []}
        workflow_path = tmp_path / "invalid.pflow.md"
        write_workflow_file(bad_ir, workflow_path)

        client = _local(create_app())
        response = client.get("/api/graph", params={"workflow": str(workflow_path)})

        assert response.status_code == 422
        errors = response.json()["errors"]
        assert errors and all("message" in e for e in errors)

    def test_nonexistent_workflow_is_422(self) -> None:
        """An unresolvable workflow reference → 422 (resolution failure)."""
        client = _local(create_app())
        response = client.get("/api/graph", params={"workflow": "no-such-workflow-xyz"})
        assert response.status_code == 422
        assert response.json()["errors"]

    def test_unexpected_pipeline_exception_is_loud_500(self, tmp_path: Path) -> None:
        """An unexpected (non-validation) pipeline exception is a loud 500.

        Patches ``resolve_validate_build`` wholesale to raise a ``RuntimeError`` —
        a stand-in for a producer bug (e.g. a build/render fault on already-
        validated IR). The endpoint catches only ``WorkflowGraphValidationError``
        (→ 422); anything else must propagate to a loud 500, never a
        200-with-empty-graph. With ``raise_server_exceptions=False`` the client
        observes that 500 rather than re-raising.
        """
        workflow_path = tmp_path / "wf.pflow.md"
        write_workflow_file(_VALID_IR, workflow_path)

        client = _local(create_app(), raise_server_exceptions=False)
        with patch(
            "pflow.ui.server.resolve_validate_build",
            side_effect=RuntimeError("simulated builder bug"),
        ):
            response = client.get("/api/graph", params={"workflow": str(workflow_path)})

        assert response.status_code == 500


class TestSourceEndpoint:
    def test_valid_workflow_returns_source_files_with_root_after_inputs(self, tmp_path: Path) -> None:
        """A valid workflow returns its source text and root despite input nodes.

        Regression guard: GraphModel input nodes are top-level and sourceless, so
        deriving ``root`` from the first top-level node would return ``None`` for
        common workflows with ``## Inputs``.
        """
        workflow_ir = {
            "inputs": {"name": {"description": "Name to greet.", "type": "string"}},
            "nodes": [
                {
                    "id": "greet",
                    "type": "shell",
                    "params": {"command": "echo ${name}"},
                }
            ],
            "outputs": {"greeting": {"description": "Greeting text.", "source": "${greet.stdout}"}},
        }
        workflow_path = tmp_path / "with-inputs.pflow.md"
        write_workflow_file(workflow_ir, workflow_path)

        client = _local(create_app())
        response = client.get("/api/source", params={"workflow": str(workflow_path)})

        assert response.status_code == 200
        payload = response.json()
        expected_root = str(workflow_path.resolve())
        assert payload["root"] == expected_root
        assert payload["files"] == {expected_root: workflow_path.read_text(encoding="utf-8")}

    def test_valid_sub_workflow_returns_parent_and_child_sources_only(self, tmp_path: Path) -> None:
        """Nested workflow source is inlined; unrelated files are absent."""
        child_path = tmp_path / "child.pflow.md"
        write_workflow_file(
            {
                "nodes": [{"id": "child-step", "type": "shell", "params": {"command": "echo child"}}],
                "outputs": {"child_out": {"description": "Child output.", "source": "${child-step.stdout}"}},
            },
            child_path,
            title="Child",
        )
        parent_path = tmp_path / "parent.pflow.md"
        write_workflow_file(
            {
                "nodes": [
                    {
                        "id": "call-child",
                        "type": "workflow",
                        "params": {"workflow": f"./{child_path.name}"},
                    }
                ],
                "outputs": {"result": {"description": "Parent output.", "source": "${call-child.child_out}"}},
            },
            parent_path,
            title="Parent",
        )
        unrelated_path = tmp_path / "unrelated.pflow.md"
        unrelated_path.write_text("# Unrelated\n", encoding="utf-8")

        client = _local(create_app())
        response = client.get("/api/source", params={"workflow": str(parent_path)})

        assert response.status_code == 200
        payload = response.json()
        parent_key = str(parent_path.resolve())
        child_key = str(child_path.resolve())
        assert payload["root"] == parent_key
        assert payload["files"] == {
            child_key: child_path.read_text(encoding="utf-8"),
            parent_key: parent_path.read_text(encoding="utf-8"),
        }
        assert str(unrelated_path.resolve()) not in payload["files"]

    def test_unreadable_child_source_file_is_skipped_not_500(self, tmp_path: Path) -> None:
        """A child file that becomes unreadable after graph build is skipped.

        The producer arm of the skip contract: ``source()`` catches
        OSError/UnicodeDecodeError per file (logger.warning) so one vanished
        child never 500s the request or drops the readable parent. Patching
        ``pflow.ui.server.Path`` (the read loop's seam) simulates the
        between-resolve-and-read vanish — resolution itself still reads the
        real child file via graph_service, so the workflow builds fine.
        """
        child_path = tmp_path / "child.pflow.md"
        write_workflow_file(
            {
                "nodes": [{"id": "child-step", "type": "shell", "params": {"command": "echo child"}}],
                "outputs": {"child_out": {"description": "Child output.", "source": "${child-step.stdout}"}},
            },
            child_path,
            title="Child",
        )
        parent_path = tmp_path / "parent.pflow.md"
        write_workflow_file(
            {
                "nodes": [
                    {
                        "id": "call-child",
                        "type": "workflow",
                        "params": {"workflow": f"./{child_path.name}"},
                    }
                ],
                "outputs": {"result": {"description": "Parent output.", "source": "${call-child.child_out}"}},
            },
            parent_path,
            title="Parent",
        )
        parent_key = str(parent_path.resolve())
        child_key = str(child_path.resolve())

        class _UnreadablePath:
            def read_text(self, *args: object, **kwargs: object) -> str:
                raise OSError("simulated: file vanished after graph build")

        def _fake_path(arg: object) -> object:
            return _UnreadablePath() if str(arg) == child_key else Path(str(arg))

        client = _local(create_app())
        with patch("pflow.ui.server.Path", _fake_path):
            response = client.get("/api/source", params={"workflow": str(parent_path)})

        assert response.status_code == 200
        payload = response.json()
        assert payload["root"] == parent_key
        assert payload["files"] == {parent_key: parent_path.read_text(encoding="utf-8")}
        assert child_key not in payload["files"]

    def test_missing_workflow_param_is_400(self) -> None:
        """No ``workflow`` query param → 400 with a structured error body."""
        client = _local(create_app())
        response = client.get("/api/source")
        assert response.status_code == 400
        assert response.json()["errors"][0]["message"]

    def test_invalid_workflow_is_422_not_500(self, tmp_path: Path) -> None:
        """A workflow that fails validation → 422 with diagnostics, never a 500."""
        bad_ir = {"nodes": [{"id": "bad", "type": "nonexistent_type_xyz", "params": {}}], "edges": []}
        workflow_path = tmp_path / "invalid.pflow.md"
        write_workflow_file(bad_ir, workflow_path)

        client = _local(create_app())
        response = client.get("/api/source", params={"workflow": str(workflow_path)})

        assert response.status_code == 422
        errors = response.json()["errors"]
        assert errors and all("message" in e for e in errors)

    def test_unexpected_pipeline_exception_is_loud_500(self, tmp_path: Path) -> None:
        """An unexpected (non-validation) pipeline exception is a loud 500."""
        workflow_path = tmp_path / "wf.pflow.md"
        write_workflow_file(_VALID_IR, workflow_path)

        client = _local(create_app(), raise_server_exceptions=False)
        with patch(
            "pflow.ui.server.resolve_validate_build",
            side_effect=RuntimeError("simulated source builder bug"),
        ):
            response = client.get("/api/source", params={"workflow": str(workflow_path)})

        assert response.status_code == 500

    def test_inline_content_workflow_returns_empty_source_map(self) -> None:
        """Inline markdown has no file path, so source refs carry no file."""
        workflow = ir_to_markdown(
            {"nodes": [{"id": "inline", "type": "shell", "params": {"command": "echo inline"}}]},
            title="Inline",
        )

        client = _local(create_app())
        response = client.get("/api/source", params={"workflow": workflow})

        assert response.status_code == 200
        assert response.json() == {"root": None, "files": {}}


class TestVersionEndpoint:
    """``/api/version`` — the cheap change-fingerprint the frontend polls.

    Contract: always ``200`` with a ``fingerprint`` (except ``400`` on a missing
    param), the fingerprint MOVES when a source file changes, and a mid-edit
    INVALID workflow still yields a ``200`` (entry-file fallback) so the client's
    poll loop never breaks.
    """

    def test_valid_workflow_returns_a_fingerprint(self, tmp_path: Path) -> None:
        workflow_path = tmp_path / "wf.pflow.md"
        write_workflow_file(_VALID_IR, workflow_path)

        client = _local(create_app())
        response = client.get("/api/version", params={"workflow": str(workflow_path)})

        assert response.status_code == 200
        fingerprint = response.json()["fingerprint"]
        assert isinstance(fingerprint, str) and fingerprint

    def test_fingerprint_is_stable_across_identical_reads(self, tmp_path: Path) -> None:
        workflow_path = tmp_path / "wf.pflow.md"
        write_workflow_file(_VALID_IR, workflow_path)

        client = _local(create_app())
        first = client.get("/api/version", params={"workflow": str(workflow_path)}).json()["fingerprint"]
        second = client.get("/api/version", params={"workflow": str(workflow_path)}).json()["fingerprint"]
        assert first == second

    def test_fingerprint_changes_when_the_source_file_changes(self, tmp_path: Path) -> None:
        """An edit (here: a forced mtime bump) moves the fingerprint — the whole
        point: it is what triggers the client's in-place re-fetch."""
        import os

        workflow_path = tmp_path / "wf.pflow.md"
        write_workflow_file(_VALID_IR, workflow_path)

        client = _local(create_app())
        before = client.get("/api/version", params={"workflow": str(workflow_path)}).json()["fingerprint"]

        # Force a distinct mtime (deterministic across fast test runs).
        stat = workflow_path.stat()
        os.utime(workflow_path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))

        after = client.get("/api/version", params={"workflow": str(workflow_path)}).json()["fingerprint"]
        assert before != after

    def test_missing_workflow_param_is_400(self) -> None:
        client = _local(create_app())
        response = client.get("/api/version")
        assert response.status_code == 400
        assert response.json()["errors"][0]["message"]

    def test_invalid_workflow_still_returns_200_so_the_poll_survives(self, tmp_path: Path) -> None:
        """A mid-edit invalid workflow must NOT error the poll. The entry file's
        mtime still rides the fingerprint, so the triggered ``/api/graph``
        re-fetch (not this endpoint) surfaces the 422 and recovers on the fix."""
        bad_ir = {"nodes": [{"id": "bad", "type": "nonexistent_type_xyz", "params": {}}], "edges": []}
        workflow_path = tmp_path / "invalid.pflow.md"
        write_workflow_file(bad_ir, workflow_path)

        client = _local(create_app())
        response = client.get("/api/version", params={"workflow": str(workflow_path)})

        assert response.status_code == 200
        assert response.json()["fingerprint"]

    def test_parse_broken_file_tracks_its_literal_path_so_edits_while_broken_are_seen(self, tmp_path: Path) -> None:
        """A PARSE error makes even resolution fail — but the agent is editing a
        real file. The literal-path fallback tracks it, so an edit-while-broken
        still moves the fingerprint (the fix is then noticed immediately)."""
        workflow_path = tmp_path / "broken.pflow.md"
        # Missing the required node description → a parse error (resolution fails,
        # not just validation).
        workflow_path.write_text("# Broken\n\n## Steps\n\n### greet\n\n```shell\necho hi\n```\n", encoding="utf-8")

        client = _local(create_app())
        before = client.get("/api/version", params={"workflow": str(workflow_path)}).json()["fingerprint"]

        import os

        stat = workflow_path.stat()
        os.utime(workflow_path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))

        after = client.get("/api/version", params={"workflow": str(workflow_path)}).json()["fingerprint"]
        assert before != after

    def test_deleted_workflow_returns_200_constant_so_the_poll_survives(self) -> None:
        """If even resolution fails (the file is gone), the fingerprint is a
        stable constant — the poll keeps running until the file returns."""
        client = _local(create_app())
        response = client.get("/api/version", params={"workflow": "no-such-workflow-xyz"})
        assert response.status_code == 200
        assert response.json()["fingerprint"]

    def test_saved_NAME_opened_workflow_tracks_edits_while_parse_broken(self) -> None:
        """A workflow opened by saved NAME (the catalog default) whose file is
        PARSE-broken still tracks edits: resolution fails, but the name resolves
        to its entry path directly, so the fingerprint moves on a save. Without
        this, a name-opened workflow froze the fingerprint while broken."""
        _save_workflow("demo")
        path = Path(WorkflowManager().get_path("demo"))
        # Corrupt the saved file into a PARSE error (missing the node description).
        path.write_text("# Demo\n\n## Steps\n\n### greet\n\n```shell\necho hi\n```\n", encoding="utf-8")

        client = _local(create_app())
        before = client.get("/api/version", params={"workflow": "demo"}).json()["fingerprint"]

        import os

        stat = path.stat()
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))

        after = client.get("/api/version", params={"workflow": "demo"}).json()["fingerprint"]
        assert before != after  # the broken-while-editing save moved the fingerprint

    def test_build_stage_failure_returns_200_not_500(self, tmp_path: Path) -> None:
        """A producer bug on validated IR makes ``/api/graph`` a loud 500 — but
        ``/api/version`` must NEVER 500 (it would break the poll). It falls
        through to the entry-file fallback and returns 200 with a fingerprint."""
        workflow_path = tmp_path / "wf.pflow.md"
        write_workflow_file(_VALID_IR, workflow_path)

        client = _local(create_app(), raise_server_exceptions=False)
        with patch("pflow.ui.server.resolve_validate_build", side_effect=RuntimeError("boom")):
            response = client.get("/api/version", params={"workflow": str(workflow_path)})

        assert response.status_code == 200
        assert response.json()["fingerprint"]


class TestJsonSerialization:
    def test_exotic_param_values_are_stringified_not_500(self) -> None:
        """The JSON seam tolerates non-JSON-native values via ``default=str``.

        Load-bearing H2 guard: param values inlined from ``.pflow.md`` can be
        non-JSON-native (a YAML-native date, etc.). The server must stringify
        them, never 500. A refactor to a plain ``JSONResponse`` (no
        ``default=str``) would silently reintroduce the 500 — this pins it.
        """
        response = _json({"nodes": [{"value": datetime.date(2026, 6, 8)}]})
        assert response.status_code == 200
        body = json.loads(response.body)
        assert body["nodes"][0]["value"] == "2026-06-08"


class TestFrontendFallback:
    def test_root_without_bundle_returns_503_hint(self, tmp_path: Path) -> None:
        """With no built bundle, non-API paths return a clear 503 (not a crash).

        Points the server at an empty static dir so the assertion is independent
        of whether the developer has run ``make ui-build`` locally — the real
        bundle is gitignored but DOES exist on disk after a Phase-4 build.
        """
        with patch("pflow.ui.server._STATIC_DIR", tmp_path):
            client = _local(create_app())
            response = client.get("/")
        assert response.status_code == 503
        assert "make ui-build" in response.text

    def test_built_bundle_is_served_and_api_is_not_shadowed(self, tmp_path: Path) -> None:
        """With a bundle present, ``/`` serves index.html, assets resolve, and the
        API routes still win (they are registered before the static mount)."""
        (tmp_path / "assets").mkdir()
        (tmp_path / "index.html").write_text("<!doctype html><div id=root></div>", encoding="utf-8")
        (tmp_path / "assets" / "app.js").write_text("console.log('hi')", encoding="utf-8")

        with patch("pflow.ui.server._STATIC_DIR", tmp_path):
            client = _local(create_app())
            root = client.get("/")
            asset = client.get("/assets/app.js")
            api = client.get("/api/catalog")

        assert root.status_code == 200
        assert "id=root" in root.text
        assert asset.status_code == 200
        # /api/* not shadowed: a 200 serving the catalog JSON, NOT index.html.
        assert api.status_code == 200
        assert api.json() == []  # isolated empty registry — proves real catalog content

    def test_index_html_revalidates_but_hashed_assets_may_cache(self, tmp_path: Path) -> None:
        """index.html sends Cache-Control: no-cache; hashed assets do not.

        Without it, browsers heuristically reuse a stale index.html whose asset
        URLs point at the PREVIOUS build — a mixed old/new bundle after every
        rebuild (the recurring stale-canvas debugging trap).
        """
        (tmp_path / "assets").mkdir()
        (tmp_path / "index.html").write_text("<!doctype html><div id=root></div>", encoding="utf-8")
        (tmp_path / "assets" / "app-CAFE1234.js").write_text("console.log('hi')", encoding="utf-8")

        with patch("pflow.ui.server._STATIC_DIR", tmp_path):
            client = _local(create_app())
            root = client.get("/")
            asset = client.get("/assets/app-CAFE1234.js")

        assert root.headers.get("cache-control") == "no-cache"
        assert asset.headers.get("cache-control") != "no-cache"


class TestBrowserOpen:
    def test_waits_then_opens_when_the_server_becomes_ready(self) -> None:
        """The core fix: don't open on a guess — open when the port is listening.

        Binds a port but delays ``listen()``; the poller must NOT open while the
        port refuses connections, and must open promptly once it accepts.
        """
        import threading
        import time

        from pflow.cli.commands.ui import _open_browser_when_ready

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        opened = threading.Event()
        try:
            with patch("webbrowser.open", side_effect=lambda _url: opened.set()):
                poller = threading.Thread(
                    target=_open_browser_when_ready,
                    args=("127.0.0.1", port, "http://late"),
                    kwargs={"timeout": 5},
                )
                poller.start()
                time.sleep(0.3)
                assert not opened.is_set(), "opened before the server was listening"
                sock.listen(1)  # server becomes ready
                assert opened.wait(timeout=3), "browser never opened after the port came up"
                poller.join(timeout=3)
        finally:
            sock.close()

    def test_opens_after_timeout_when_nothing_ever_listens(self) -> None:
        """Safety net: a never-ready server still opens (never silently skips)."""
        from pflow.cli.commands.ui import _open_browser_when_ready

        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.bind(("127.0.0.1", 0))
        dead_port = probe.getsockname()[1]
        probe.close()  # nothing listens here now
        with patch("webbrowser.open") as mock_open:
            _open_browser_when_ready("127.0.0.1", dead_port, "http://x", timeout=0.4)
        mock_open.assert_called_once_with("http://x")


class TestUiCommand:
    def test_missing_extra_prints_install_hint(self) -> None:
        """When uvicorn is unimportable, the command prints the [ui] hint and exits 1."""
        runner = CliRunner()
        # A ``None`` entry in sys.modules forces ``import uvicorn`` to raise
        # ImportError — simulating a base install without the [ui] extra.
        with patch.dict(sys.modules, {"uvicorn": None}):
            result = runner.invoke(ui_cmd, [])
        assert result.exit_code == 1
        assert "pflow-cli[ui]" in result.output

    def test_serves_without_opening_browser(self, tmp_path: Path) -> None:
        """``--no-open`` starts the server without a browser; the uvicorn server is run.

        ``Server.run`` blocks forever, so it is stubbed — the test asserts the command wires host/port
        through to the uvicorn ``Config`` and never schedules a browser open. (Host/port moved from
        ``uvicorn.run(host=, port=)`` to ``uvicorn.Config(host=, port=)`` when the command switched to a
        Server instance to install the graceful-shutdown hook — Task 173.)
        """
        import uvicorn

        workflow_path = tmp_path / "wf.pflow.md"
        write_workflow_file(_VALID_IR, workflow_path)

        runner = CliRunner()
        with (
            patch("pflow.cli.commands.ui._port_available", return_value=True),
            patch("uvicorn.Server.run") as mock_run,
            patch("uvicorn.Config", wraps=uvicorn.Config) as mock_config,
            patch("webbrowser.open") as mock_open,
        ):
            result = runner.invoke(ui_cmd, [str(workflow_path), "--no-open", "--port", "9123"])

        assert result.exit_code == 0, result.output
        mock_run.assert_called_once()
        assert mock_config.call_args.kwargs["port"] == 9123
        assert mock_config.call_args.kwargs["host"] == "127.0.0.1"
        mock_open.assert_not_called()

    def test_default_path_wires_the_readiness_thread(self, tmp_path: Path) -> None:
        """Without --no-open, the command starts the readiness poller (not a timer).

        Guards against the helper being tested-but-unwired: a regression that
        drops the open path would still pass the --no-open test above. Patches
        ``threading.Thread`` so the assertion is deterministic (no thread timing).
        """
        workflow_path = tmp_path / "wf.pflow.md"
        write_workflow_file(_VALID_IR, workflow_path)

        from pflow.cli.commands import ui as ui_mod

        captured: dict[str, object] = {}

        class _FakeThread:
            def __init__(self, *, target=None, args=(), daemon=None):  # type: ignore[no-untyped-def]
                captured.update(target=target, args=args, daemon=daemon)

            def start(self) -> None:
                captured["started"] = True

        runner = CliRunner()
        with (
            patch("pflow.cli.commands.ui._port_available", return_value=True),
            patch("uvicorn.Server.run"),
            patch("threading.Thread", _FakeThread),
        ):
            result = runner.invoke(ui_cmd, [str(workflow_path), "--port", "9124"])

        assert result.exit_code == 0, result.output
        assert captured.get("target") is ui_mod._open_browser_when_ready
        assert captured.get("started") is True
        assert captured.get("daemon") is True
        host, port, url = captured["args"]  # type: ignore[misc]
        assert (host, port) == ("127.0.0.1", 9124)
        assert url.startswith("http://127.0.0.1:9124/?workflow=")

    def test_port_in_use_by_foreign_process_prints_actionable_hint(self) -> None:
        """An occupied port held by a NON-pflow process → exit 1 with an actionable hint.

        Regression guard: uvicorn swallows the bind OSError and sys.exit(1)s with
        only its own log line, so the command pre-flights the bind to own the
        message. ``_probe_health`` is patched to ``None`` (not a pflow viewer) so
        the reuse branch is skipped — and so the real probe doesn't stall on the
        bound-but-non-HTTP socket. ``uvicorn.run`` is stubbed as a hang safety net.
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        port = sock.getsockname()[1]
        try:
            runner = CliRunner()
            with (
                patch("pflow.cli.commands.ui._probe_health", return_value=None),
                patch("uvicorn.Server.run") as mock_run,
            ):
                result = runner.invoke(ui_cmd, ["--no-open", "--port", str(port)])
        finally:
            sock.close()

        assert result.exit_code == 1
        assert "already in use" in result.output
        assert "--port" in result.output
        mock_run.assert_not_called()

    def test_port_in_use_by_pflow_viewer_reuses_it(self, tmp_path: Path) -> None:
        """An occupied port held by a pflow viewer → reuse: open a tab, exit 0, no new server.

        ``pflow ui <wf>`` becomes idempotent. ``_port_available`` is False (occupied)
        and ``_probe_health`` confirms a pflow viewer, so the command opens a browser
        tab against the running server and exits 0 without starting uvicorn.
        """
        workflow_path = tmp_path / "wf.pflow.md"
        write_workflow_file(_VALID_IR, workflow_path)

        runner = CliRunner()
        with (
            patch("pflow.cli.commands.ui._port_available", return_value=False),
            patch("pflow.cli.commands.ui._probe_health", return_value={"service": "pflow-ui"}),
            patch("uvicorn.Server.run") as mock_run,
            patch("webbrowser.open") as mock_open,
        ):
            result = runner.invoke(ui_cmd, [str(workflow_path), "--port", "9131"])

        assert result.exit_code == 0, result.output
        assert "opened a view" in result.output  # a tab WAS opened (no --no-open)
        mock_run.assert_not_called()
        mock_open.assert_called_once()
        assert "9131" in mock_open.call_args.args[0]

    def test_port_in_use_by_pflow_viewer_honors_no_open(self, tmp_path: Path) -> None:
        """Reuse path respects ``--no-open``: open nothing, and the message says so."""
        workflow_path = tmp_path / "wf.pflow.md"
        write_workflow_file(_VALID_IR, workflow_path)

        runner = CliRunner()
        with (
            patch("pflow.cli.commands.ui._port_available", return_value=False),
            patch("pflow.cli.commands.ui._probe_health", return_value={"service": "pflow-ui"}),
            patch("uvicorn.Server.run") as mock_run,
            patch("webbrowser.open") as mock_open,
        ):
            result = runner.invoke(ui_cmd, [str(workflow_path), "--no-open", "--port", "9132"])

        assert result.exit_code == 0, result.output
        # The message must NOT falsely claim a view was opened under --no-open.
        assert "view available" in result.output
        assert "opened a view" not in result.output
        mock_run.assert_not_called()
        mock_open.assert_not_called()

    def test_reuse_resolves_a_relative_workflow_path_to_absolute(self) -> None:
        """The already-running server may have a different cwd, so the reuse URL must
        carry an ABSOLUTE path — a relative one would resolve against the server's cwd
        and open the wrong/missing workflow."""
        runner = CliRunner()
        with runner.isolated_filesystem():
            Path("wf.pflow.md").write_text(
                "# x\n\n## Steps\n\n### a\n\nDo a thing now.\n\n- type: shell\n- command: echo hi\n", encoding="utf-8"
            )
            expected_workflow = Path("wf.pflow.md").resolve()
            with (
                patch("pflow.cli.commands.ui._port_available", return_value=False),
                patch("pflow.cli.commands.ui._probe_health", return_value={"service": "pflow-ui"}),
                patch("uvicorn.Server.run"),
                patch("webbrowser.open") as mock_open,
            ):
                result = runner.invoke(ui_cmd, ["wf.pflow.md", "--port", "9135"])

        assert result.exit_code == 0, result.output
        encoded_workflow = mock_open.call_args.args[0].split("workflow=")[1]
        assert Path(unquote(encoded_workflow)) == expected_workflow


class TestServeUrl:
    """``_serve_url`` — the shared browser-URL builder for fresh-start AND reuse paths."""

    def test_includes_workflow_and_freezes_watch_when_no_auto_update(self) -> None:
        from pflow.cli.commands.ui import _serve_url

        url = _serve_url(8765, "wf", True)
        assert "workflow=wf" in url
        assert "watch=0" in url  # --no-auto-update must survive the reuse path (parity guard)

    def test_includes_workflow_without_watch_when_auto_update_on(self) -> None:
        from pflow.cli.commands.ui import _serve_url

        url = _serve_url(8765, "wf", False)
        assert "workflow=wf" in url
        assert "watch" not in url

    def test_bare_url_when_no_workflow(self) -> None:
        from pflow.cli.commands.ui import _serve_url

        assert _serve_url(8765, None, False) == "http://127.0.0.1:8765/"


class TestProbeHealth:
    """``_probe_health`` — the non-failing GET probe (returns body or None, never exits)."""

    def test_returns_body_for_a_pflow_viewer(self) -> None:
        import httpx

        from pflow.cli.commands.ui import _probe_health

        # A real httpx.get() always sets .request (raise_for_status needs it).
        request = httpx.Request("GET", "http://127.0.0.1:8765/api/health")
        response = httpx.Response(200, json={"service": "pflow-ui", "windows": 2}, request=request)
        with patch("pflow.cli.commands.ui.httpx.get", return_value=response):
            assert _probe_health(8765) == {"service": "pflow-ui", "windows": 2}

    def test_returns_none_for_a_non_pflow_json_body(self) -> None:
        import httpx

        from pflow.cli.commands.ui import _probe_health

        request = httpx.Request("GET", "http://127.0.0.1:8765/api/health")
        response = httpx.Response(200, json={"some": "other-server"}, request=request)
        with patch("pflow.cli.commands.ui.httpx.get", return_value=response):
            assert _probe_health(8765) is None

    def test_returns_none_on_transport_error(self) -> None:
        import httpx

        from pflow.cli.commands.ui import _probe_health

        with patch("pflow.cli.commands.ui.httpx.get", side_effect=httpx.ConnectError("refused")):
            assert _probe_health(8765) is None


class TestFocusOpen:
    def test_polls_health_then_delivers_once(self) -> None:
        """``focus --open`` polls the cheap /api/health for windows>0, then sends focus ONCE.

        Replaces the old loop that re-POSTed the build-triggering ``focus`` each tick
        (~60 graph builds). Now: one initial probe-POST + cheap health polls until a
        window registers + one final delivery = 2 ``_point_request`` calls total.
        """
        initial = {"resolved": {"matched": 1, "address": "greet"}, "sent_to": 0, "windows": [], "workflow_key": "k"}
        delivered = {
            "resolved": {"matched": 1, "address": "greet"},
            "sent_to": 1,
            "windows": [{"visibility": "visible"}],
            "workflow_key": "k",
        }
        runner = CliRunner()
        with (
            patch("pflow.cli.commands.ui._point_request", side_effect=[initial, delivered]) as mock_point,
            patch(
                "pflow.cli.commands.ui._probe_health",
                side_effect=[{"service": "pflow-ui", "windows": 0}, {"service": "pflow-ui", "windows": 1}],
            ) as mock_probe,
            patch("webbrowser.open") as mock_open,
            patch("time.sleep"),
        ):
            result = runner.invoke(ui_cmd, ["focus", "wf", "greet", "--open", "--port", "9133"])

        assert result.exit_code == 0, result.output
        assert mock_point.call_count == 2  # initial POST + ONE delivery (not ~60 re-POSTs)
        assert mock_probe.call_count == 2  # cheap polls until windows>0
        mock_open.assert_called_once()

    def test_open_timeout_still_delivers_once_for_accurate_status(self) -> None:
        """If no window ever connects, the final delivery still runs so ``timed_out``
        reflects a real send (not a stale pre-open payload) — and an edge re-send stays
        unconditional. The window-never-connects case ⇒ exit 1 + the 'didn't connect' note."""
        initial = {"resolved": {"matched": 1, "address": "greet"}, "sent_to": 0, "windows": [], "workflow_key": "k"}
        still_empty = {"resolved": {"matched": 1, "address": "greet"}, "sent_to": 0, "windows": [], "workflow_key": "k"}
        runner = CliRunner()

        # monotonic: start, then a value past the deadline so the poll loop exits immediately.
        with (
            patch("pflow.cli.commands.ui._point_request", side_effect=[initial, still_empty]) as mock_point,
            patch("pflow.cli.commands.ui._probe_health", return_value={"service": "pflow-ui", "windows": 0}),
            patch("webbrowser.open"),
            patch("time.sleep"),
            patch("time.monotonic", side_effect=[0.0, 100.0, 100.0]),
        ):
            result = runner.invoke(ui_cmd, ["focus", "wf", "greet", "--open", "--port", "9134"])

        assert result.exit_code == 1
        assert "didn't connect" in result.output
        assert mock_point.call_count == 2  # initial + one final delivery even on timeout


def test_hub_shutdown_ends_streams_with_a_sentinel():
    """Clean `pflow ui` Ctrl+C (Task 173): on shutdown the hub marks every Viewer inactive and wakes its
    blocked queue with the shutdown sentinel, so each SSE generator RETURNS instead of being force-cancelled
    by uvicorn (which logs a CancelledError per stream). Verifies the mechanism the wrapped handle_exit drives."""

    async def scenario() -> None:
        from pflow.ui.server import _SHUTDOWN_SENTINEL, _Hub

        hub = _Hub()
        a = hub.register("wfA", "visible")
        b = hub.register("wfB", "visible", run_id="r1")
        hub.shutdown()
        assert a.active is False and b.active is False, "every Viewer is marked inactive"
        assert a.queue.get_nowait() is _SHUTDOWN_SENTINEL, "each stream is woken with the sentinel"
        assert b.queue.get_nowait() is _SHUTDOWN_SENTINEL

    asyncio.run(scenario())


class TestRunsEndpoint:
    """``GET /api/runs`` — the Task 173 D6 run-list data layer (over the shared ``scan_traces``)."""

    @staticmethod
    def _write_trace(
        debug: Path,
        name: str,
        wf_path: str,
        *,
        complete: bool,
        final_status: str = "success",
        only_node: str | None = None,
        execution_id: str = "x",
        resumed_from: str | None = None,
    ) -> None:
        # Synthetic, but the CONSUMED keys mirror the producer: meta ← workflow_trace.py `_meta_fields`,
        # run.complete.final_status ← `_aggregates`. If the producer renames those, this stays green while
        # /api/runs breaks — the node.start/event join keys are pinned against a real collector in
        # tests/test_runtime/test_emit_time_trace.py (tests/CLAUDE.md pitfall #19).
        meta: dict = {
            "kind": "meta",
            "pflow_trace": "jsonl/1",
            "workflow_path": wf_path,
            "workflow_name": "WF",
            "start_time": "2026-01-01T00:00:00",
            "execution_id": execution_id,
        }
        if only_node is not None:
            meta["only_node"] = only_node
        if resumed_from is not None:
            meta["resumed_from"] = resumed_from
        lines: list[dict] = [
            meta,
            {"kind": "node.start", "node_id": "a", "id": 0, "ancestor_path": [], "port": None, "status": "running"},
        ]
        if complete:
            lines.append({
                "kind": "event",
                "node_id": "a",
                "id": 0,
                "ancestor_path": [],
                "port": None,
                "status": "success",
            })
            lines.append({"kind": "run.complete", "final_status": final_status, "nodes_executed": 1})
        (debug / name).write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")

    @pytest.mark.skipif(sys.platform == "win32", reason="exact liveness needs fcntl (Unix)")
    def test_lists_runs_with_exact_liveness(self, tmp_path, monkeypatch) -> None:
        """`live` is EXACT (the advisory-lock probe), not an mtime guess: a finished run → live False; an
        incomplete trace with NO live writer (leftover/crashed) → live False; an incomplete trace whose
        writer holds the lock → live True. Also checks the raw-fact fields."""
        import fcntl

        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        debug = tmp_path / ".pflow" / "debug"
        debug.mkdir(parents=True)
        wf = str(tmp_path / "wf.pflow.md")
        self._write_trace(
            debug, "workflow-trace-aaa-wf-20260101-000000-000001.json", wf, complete=True, execution_id="done"
        )
        self._write_trace(
            debug, "workflow-trace-aaa-wf-20260101-000000-000002.json", wf, complete=False, execution_id="crashed"
        )
        self._write_trace(
            debug, "workflow-trace-aaa-wf-20260101-000000-000003.json", wf, complete=False, execution_id="live"
        )
        live_path = debug / "workflow-trace-aaa-wf-20260101-000000-000003.json"

        with open(live_path, encoding="utf-8") as writer:
            fcntl.flock(writer.fileno(), fcntl.LOCK_EX)  # simulate the producer holding its trace open
            body = _local(create_app()).get("/api/runs").json()
        by_id = {r["run_id"]: r for r in body}
        assert set(by_id) == {"done", "crashed", "live"}
        assert by_id["done"]["complete"] is True and by_id["done"]["final_status"] == "success"
        assert by_id["done"]["live"] is False  # a finished run is never "live"
        assert by_id["crashed"]["live"] is False, "incomplete with NO live writer = not live (exact)"
        assert by_id["live"]["live"] is True and by_id["live"]["final_status"] is None, "incomplete + held lock = live"
        assert by_id["live"]["workflow_name"] == "WF" and by_id["live"]["trace_file"].endswith(".json")

    def test_filter_by_workflow_labels_only_runs_not_excludes(self, tmp_path, monkeypatch) -> None:
        """``?workflow=X`` filters history to X (matched on recorded ``meta.workflow_path``) and LABELS its
        ``--only`` runs (``only_node`` set) rather than excluding them — the exclude is the live overlay's
        policy, not history's (DR-3). A different workflow's run is absent."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        debug = tmp_path / ".pflow" / "debug"
        debug.mkdir(parents=True)
        wf_x = tmp_path / "x.pflow.md"
        wf_x.write_text("# X", encoding="utf-8")
        wf_y = tmp_path / "y.pflow.md"
        wf_y.write_text("# Y", encoding="utf-8")
        # The server resolves ?workflow= to the resolved path AND scan_traces hash-scopes by it, so the
        # trace filenames must embed md5(resolved path) — build them via the real format_trace_filename.
        wf_x_path = str(wf_x.resolve())
        wf_y_path = str(wf_y.resolve())
        self._write_trace(
            debug,
            format_trace_filename(wf_x_path, "x", "20260101-000000-000001"),
            wf_x_path,
            complete=True,
            execution_id="x-full",
        )
        self._write_trace(
            debug,
            format_trace_filename(wf_x_path, "x", "20260101-000000-000002"),
            wf_x_path,
            complete=True,
            only_node="b",
            execution_id="x-only",
        )
        self._write_trace(
            debug,
            format_trace_filename(wf_y_path, "y", "20260101-000000-000001"),
            wf_y_path,
            complete=True,
            execution_id="y-run",
        )
        body = _local(create_app()).get("/api/runs", params={"workflow": str(wf_x)}).json()
        by_id = {r["run_id"]: r for r in body}
        assert set(by_id) == {"x-full", "x-only"}, "filtered to X; --only labelled, not excluded; Y absent"
        assert by_id["x-only"]["only_node"] == "b"
        assert by_id["x-full"]["only_node"] is None

    def test_empty_dir_returns_empty_list(self, tmp_path, monkeypatch) -> None:
        """No trace dir (fresh install) → ``200 + []`` (genuinely zero runs), never an error."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        resp = _local(create_app()).get("/api/runs")
        assert resp.status_code == 200 and resp.json() == []

    def test_unknown_workflow_name_404(self, tmp_path, monkeypatch) -> None:
        """``?workflow=<unresolvable>`` → 404 (mirrors ``/api/events`` — a named filter must resolve)."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        resp = _local(create_app()).get("/api/runs", params={"workflow": "no-such-workflow-xyz"})
        assert resp.status_code == 404

    def test_run_entry_projects_resumed_from_chain_lineage(self, tmp_path, monkeypatch) -> None:
        """Task 171: `/api/runs` surfaces attempt-chain lineage — a resumed attempt reports its source
        run's id in `resumed_from`; a plain run (and a pre-2.6.0 trace lacking the meta key) reports
        None. Also pins the `paused` final_status riding through the raw-fact projection."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        debug = tmp_path / ".pflow" / "debug"
        debug.mkdir(parents=True)
        wf = str(tmp_path / "wf.pflow.md")
        self._write_trace(
            debug,
            "workflow-trace-aaa-wf-20260101-000000-000001.json",
            wf,
            complete=True,
            final_status="paused",
            execution_id="source-run",
        )
        self._write_trace(
            debug,
            "workflow-trace-aaa-wf-20260101-000000-000002.json",
            wf,
            complete=True,
            execution_id="attempt-2",
            resumed_from="source-run",
        )
        by_id = {r["run_id"]: r for r in _local(create_app()).get("/api/runs").json()}
        assert by_id["attempt-2"]["resumed_from"] == "source-run"
        assert by_id["source-run"]["resumed_from"] is None  # no lineage key on the meta → None
        assert by_id["source-run"]["final_status"] == "paused"  # the raw fact the UI composes the mark from

    def test_run_entry_buckets_runs_by_git_root(self, tmp_path, monkeypatch) -> None:
        """`git_root` lets the catalog bucket ad-hoc runs by repo (Task 173 D6): a run under a `.git`-bearing
        dir reports that root; one under no repo reports None; an inline `ir-hash:` run reports None (no file)."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        debug = tmp_path / ".pflow" / "debug"
        debug.mkdir(parents=True)
        repo = tmp_path / "repo"
        (repo / ".git").mkdir(parents=True)  # a normal clone — `.git` is a DIR
        repo_wf = repo / "flows" / "deploy.pflow.md"
        repo_wf.parent.mkdir(parents=True)
        loose_wf = tmp_path / "loose" / "scratch.pflow.md"
        loose_wf.parent.mkdir(parents=True)
        self._write_trace(
            debug,
            "workflow-trace-aaa-wf-20260101-000000-000001.json",
            str(repo_wf),
            complete=True,
            execution_id="in-repo",
        )
        self._write_trace(
            debug,
            "workflow-trace-bbb-wf-20260101-000000-000002.json",
            str(loose_wf),
            complete=True,
            execution_id="loose",
        )
        self._write_trace(
            debug,
            "workflow-trace-ccc-wf-20260101-000000-000003.json",
            "ir-hash:deadbeef",
            complete=True,
            execution_id="inline",
        )
        by_id = {r["run_id"]: r for r in _local(create_app()).get("/api/runs").json()}
        assert by_id["in-repo"]["git_root"] == str(repo.resolve())
        assert by_id["loose"]["git_root"] is None  # under no repo → the catalog's "Other" bucket
        assert by_id["inline"]["git_root"] is None  # inline (ir-hash:) has no file

    def test_walk_to_git_root_detects_a_dot_git_FILE_worktree(self, tmp_path) -> None:
        """A git WORKTREE (and submodule) has `.git` as a FILE, not a dir — `_walk_to_git_root` must detect it
        via `.exists()` (NOT `.is_dir()`). Pins the worktree case (this very checkout is a worktree)."""
        from pflow.ui.server import _walk_to_git_root

        worktree = tmp_path / "worktree"
        (worktree / "nested").mkdir(parents=True)
        (worktree / ".git").write_text("gitdir: /elsewhere/.git/worktrees/wt\n", encoding="utf-8")  # the pointer FILE
        assert _walk_to_git_root(worktree / "nested") == str(worktree)


class TestRunScopedBroadcast:
    """DR-1: run-events are delivered run-scoped (``broadcast_run``) so a pinned replay and the unpinned
    live overlay of one workflow never cross-feed; Point's ``broadcast`` stays workflow-scoped."""

    def test_broadcast_run_targets_only_matching_run_id(self) -> None:
        from pflow.ui.server import _Conn, _Hub

        def drain(conn: _Conn) -> list[str]:
            out: list[str] = []
            while not conn.queue.empty():
                out.append(str(conn.queue.get_nowait()["type"]))
            return out

        async def scenario() -> tuple[list[str], list[str]]:
            hub = _Hub()
            unpinned = hub.register("wfkey", "visible", None)  # the live overlay
            pinned = hub.register("wfkey", "visible", "runA")  # a pinned replay/watch
            hub.broadcast_run("wfkey", "runA", {"type": "run-events", "events": []})  # → pinned only
            hub.broadcast_run("wfkey", None, {"type": "run-reset"})  # → unpinned only
            hub.broadcast("wfkey", {"type": "clear"})  # Point: workflow-scoped → BOTH
            return (drain(pinned), drain(unpinned))

        pinned_msgs, unpinned_msgs = asyncio.run(scenario())
        # Assert message TYPES per connection, not just counts: a transposed-run_id bug (runA's events to
        # the unpinned conn, the reset to runA's) keeps both SIZES at 2 while cross-feeding — only checking
        # contents-per-conn catches it. This is what "never cross-feed" actually means.
        assert pinned_msgs == ["run-events", "clear"], "pinned got its run's events + the Point clear, NOT run-reset"
        assert unpinned_msgs == ["run-reset", "clear"], (
            "unpinned got its own reset + the Point clear, NOT runA's events"
        )

    def test_ensure_tailer_replaces_a_terminated_tailer(self, tmp_path, monkeypatch) -> None:
        """DR-1 fix (deep-review Critical): a pinned tailer that resolves to no trace broadcasts
        ``run-not-found`` and RETURNS — but its entry lingers in ``_tailers`` until the last viewer leaves.
        A second/reconnecting viewer of the same stale ``?run=`` must get a FRESH tailer (which re-resolves
        + re-broadcasts ``run-not-found``), never the terminated one (whose empty snapshot + silence = the
        all-pending blank canvas the message exists to prevent)."""
        from pflow.ui.server import _Hub

        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        # Shrink the pinned-resolve grace window — this exercises the run-not-found PATH, not the timing;
        # otherwise the ghost id waits the full production window of real asyncio.sleep before terminating.
        monkeypatch.setattr("pflow.ui.run_tailer._PINNED_RESOLVE_ATTEMPTS", 2)
        (tmp_path / ".pflow" / "debug").mkdir(parents=True)  # empty → "ghost" resolves to nothing

        async def scenario() -> tuple[bool, bool, bool]:
            hub = _Hub()
            first = hub.ensure_tailer("wf", "ghost")
            task1 = hub._tailers[("wf", "ghost")][1]
            await task1  # the run-not-found path returns → task done, entry lingers
            second = hub.ensure_tailer("wf", "ghost")  # MUST start fresh, not reuse the dead one
            task2 = hub._tailers[("wf", "ghost")][1]
            task2.cancel()
            return (task1.done(), second is first, task2 is task1)

        terminated, same_tailer, same_task = asyncio.run(scenario())
        assert terminated, "the pinned run-not-found tailer terminates (does not loop forever)"
        assert not same_tailer and not same_task, "a terminated tailer is replaced on the next subscribe (DR-1 fix)"


class TestLazyImportBoundary:
    def test_importing_ui_command_does_not_import_server(self) -> None:
        """The eagerly-imported ``ui`` command must not pull in the web stack (H4).

        ``cli/commands/ui.py`` is imported at ``main.py`` load. It must import
        starlette/uvicorn/the server only inside the command body, so a base
        install can load the CLI without the [ui] web stack.
        """
        import importlib

        # Observe a fresh import of the command module's effect, independent of
        # whatever earlier tests loaded.
        sys.modules.pop("pflow.ui.server", None)
        sys.modules.pop("pflow.cli.commands.ui", None)
        importlib.import_module("pflow.cli.commands.ui")

        assert "pflow.ui.server" not in sys.modules
