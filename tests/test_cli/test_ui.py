"""Tests for ``pflow ui`` — the Starlette server, its endpoints, and the CLI.

Covers the three ``/api/graph`` failure arms (H2: 400 missing param, 422
resolution/validation failure, 500 build/render bug → never a 200-with-empty-
graph), the catalog endpoint, the ``pip install pflow[ui]`` hint when the extra
is absent (H4), and the lazy-import boundary that keeps the base CLI loading
without the web stack.

Implementation: src/pflow/ui/server.py, src/pflow/cli/commands/ui.py
"""

from __future__ import annotations

import datetime
import json
import socket
import sys
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner
from starlette.testclient import TestClient

from pflow.cli.commands.ui import ui_cmd
from pflow.core.workflow.manager import WorkflowManager
from pflow.ui.server import _json, create_app
from tests.shared.markdown_utils import write_workflow_file

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
        client = TestClient(create_app())
        response = client.get("/api/catalog")
        assert response.status_code == 200
        assert response.json() == []

    def test_catalog_lists_saved_workflows_without_ir(self) -> None:
        """A saved workflow appears with name/description/path and no ``ir``."""
        _save_workflow("demo", description="A demo workflow")
        client = TestClient(create_app())
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

        client = TestClient(create_app())
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
        client = TestClient(create_app())
        response = client.get("/api/graph")
        assert response.status_code == 400
        assert response.json()["errors"][0]["message"]

    def test_invalid_workflow_is_422_not_500(self, tmp_path: Path) -> None:
        """A workflow that fails validation → 422 with diagnostics, never a 500."""
        bad_ir = {"nodes": [{"id": "bad", "type": "nonexistent_type_xyz", "params": {}}], "edges": []}
        workflow_path = tmp_path / "invalid.pflow.md"
        write_workflow_file(bad_ir, workflow_path)

        client = TestClient(create_app())
        response = client.get("/api/graph", params={"workflow": str(workflow_path)})

        assert response.status_code == 422
        errors = response.json()["errors"]
        assert errors and all("message" in e for e in errors)

    def test_nonexistent_workflow_is_422(self) -> None:
        """An unresolvable workflow reference → 422 (resolution failure)."""
        client = TestClient(create_app())
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

        client = TestClient(create_app(), raise_server_exceptions=False)
        with patch(
            "pflow.ui.server.resolve_validate_build",
            side_effect=RuntimeError("simulated builder bug"),
        ):
            response = client.get("/api/graph", params={"workflow": str(workflow_path)})

        assert response.status_code == 500


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
            client = TestClient(create_app())
            response = client.get("/")
        assert response.status_code == 503
        assert "make ui-build" in response.text

    def test_built_bundle_is_served_and_api_is_not_shadowed(self, tmp_path: Path) -> None:
        """With a bundle present, ``/`` serves index.html, assets resolve, and the
        API routes still win (they are registered before the static mount)."""
        (tmp_path / "assets").mkdir()
        (tmp_path / "index.html").write_text("<!doctype html><div id=root></div>")
        (tmp_path / "assets" / "app.js").write_text("console.log('hi')")

        with patch("pflow.ui.server._STATIC_DIR", tmp_path):
            client = TestClient(create_app())
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
        (tmp_path / "index.html").write_text("<!doctype html><div id=root></div>")
        (tmp_path / "assets" / "app-CAFE1234.js").write_text("console.log('hi')")

        with patch("pflow.ui.server._STATIC_DIR", tmp_path):
            client = TestClient(create_app())
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
        assert "pip install pflow[ui]" in result.output

    def test_serves_without_opening_browser(self, tmp_path: Path) -> None:
        """``--no-open`` starts the server without a browser; uvicorn.run is invoked.

        ``uvicorn.run`` blocks forever, so it is stubbed — the test asserts the
        command wires the app + host/port through to it and never schedules a
        browser open.
        """
        workflow_path = tmp_path / "wf.pflow.md"
        write_workflow_file(_VALID_IR, workflow_path)

        runner = CliRunner()
        with (
            patch("pflow.cli.commands.ui._port_available", return_value=True),
            patch("uvicorn.run") as mock_run,
            patch("webbrowser.open") as mock_open,
        ):
            result = runner.invoke(ui_cmd, [str(workflow_path), "--no-open", "--port", "9123"])

        assert result.exit_code == 0, result.output
        mock_run.assert_called_once()
        assert mock_run.call_args.kwargs["port"] == 9123
        assert mock_run.call_args.kwargs["host"] == "127.0.0.1"
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
            patch("uvicorn.run"),
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

    def test_port_in_use_prints_actionable_hint(self) -> None:
        """An occupied port → exit 1 with an actionable hint; uvicorn is never reached.

        Regression guard: uvicorn swallows the bind OSError and sys.exit(1)s with
        only its own log line, so the command pre-flights the bind to own the
        message. ``uvicorn.run`` is stubbed as a safety net against a hang if the
        pre-flight check ever wrongly passes.
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        port = sock.getsockname()[1]
        try:
            runner = CliRunner()
            with patch("uvicorn.run") as mock_run:
                result = runner.invoke(ui_cmd, ["--no-open", "--port", str(port)])
        finally:
            sock.close()

        assert result.exit_code == 1
        assert "already in use" in result.output
        assert "--port" in result.output
        mock_run.assert_not_called()


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
