"""CLI contract tests for Point and Watch commands under ``pflow ui``."""

from __future__ import annotations

import json
from unittest.mock import patch

import httpx
from click.testing import CliRunner

from pflow.cli.commands import ui as ui_module


def _response(status: int, payload: dict[str, object]) -> httpx.Response:
    request = httpx.Request("POST", "http://127.0.0.1:8765/api/command")
    return httpx.Response(status, json=payload, request=request)


def _dispatch_payload(*, sent_to: int = 1) -> dict[str, object]:
    windows = [{"visibility": "visible"}] if sent_to else []
    return {
        "resolved": {"matched": 1, "address": "greet"},
        "sent_to": sent_to,
        "windows": windows,
        "workflow_key": "/workflows/demo.pflow.md",
    }


class TestUiRouting:
    def test_group_help_exposes_serve_flags_and_interaction_commands(self) -> None:
        result = CliRunner().invoke(ui_module.ui_cmd, ["--help"])

        assert result.exit_code == 0, result.output
        assert "--no-auto-update" in result.output
        assert "focus" in result.output
        assert "user-activity" in result.output

    def test_focus_dispatches_as_subcommand(self) -> None:
        runner = CliRunner()
        with patch("httpx.request", return_value=_response(200, _dispatch_payload())) as request:
            result = runner.invoke(ui_module.ui_cmd, ["focus", "demo", "greet", "--port", "9123"])

        assert result.exit_code == 0, result.output
        assert "sent to 1 window" in result.output
        assert request.call_args.args[:2] == ("POST", "http://127.0.0.1:9123/api/command")
        assert request.call_args.kwargs["json"] == {
            "workflow": "demo",
            "type": "focus",
            "target": "greet",
        }

    def test_workflow_path_named_like_subcommand_still_routes_to_serve(self) -> None:
        runner = CliRunner()
        with (
            patch.object(ui_module, "_port_available", return_value=True),
            patch("uvicorn.run") as run,
        ):
            result = runner.invoke(ui_module.ui_cmd, ["./focus.pflow.md", "--no-open"])

        assert result.exit_code == 0, result.output
        assert "workflow=.%2Ffocus.pflow.md" in result.output
        run.assert_called_once()

    def test_no_auto_update_preserves_private_watch_query_param(self) -> None:
        runner = CliRunner()
        with (
            patch.object(ui_module, "_port_available", return_value=True),
            patch("uvicorn.run"),
        ):
            result = runner.invoke(ui_module.ui_cmd, ["demo", "--no-open", "--no-auto-update"])

        assert result.exit_code == 0, result.output
        assert "workflow=demo&watch=0" in result.output


class TestPointCommands:
    def test_json_mode_passes_server_payload_through(self) -> None:
        payload = _dispatch_payload()
        runner = CliRunner()
        with patch("httpx.request", return_value=_response(200, payload)):
            result = runner.invoke(ui_module.ui_cmd, ["frame", "demo", "greet", "--json"])

        assert result.exit_code == 0, result.output
        assert json.loads(result.output) == payload

    def test_frame_zero_windows_does_not_suggest_unsupported_open_flag(self) -> None:
        runner = CliRunner()
        with patch("httpx.request", return_value=_response(200, _dispatch_payload(sent_to=0))):
            result = runner.invoke(ui_module.ui_cmd, ["frame", "demo", "greet"])

        assert result.exit_code == 1, result.output
        assert "open the workflow first" in result.output
        assert "--open" not in result.output

    def test_unresolved_target_exits_nonzero_with_json_payload_intact(self) -> None:
        payload = {
            "resolved": {"matched": 0, "suggestions": ["greet"]},
            "sent_to": 0,
            "windows": [],
            "workflow_key": "/workflows/demo.pflow.md",
        }
        runner = CliRunner()
        with patch("httpx.request", return_value=_response(200, payload)):
            result = runner.invoke(ui_module.ui_cmd, ["focus", "demo", "grete", "--json"])

        assert result.exit_code == 1
        assert json.loads(result.output) == payload

    def test_connection_failure_has_actionable_start_hint(self) -> None:
        error = httpx.ConnectError(
            "connection refused",
            request=httpx.Request("POST", "http://127.0.0.1:9000/api/command"),
        )
        runner = CliRunner()
        with patch("httpx.request", side_effect=error):
            result = runner.invoke(ui_module.ui_cmd, ["clear-focus", "demo", "--port", "9000"])

        assert result.exit_code == 1
        assert "No pflow ui server on port 9000" in result.output
        assert "pflow ui demo" in result.output
        assert "Traceback" not in result.output

    def test_connection_failure_is_structured_in_json_mode(self) -> None:
        error = httpx.ConnectError(
            "connection refused",
            request=httpx.Request("POST", "http://127.0.0.1:9000/api/command"),
        )
        runner = CliRunner()
        with patch("httpx.request", side_effect=error):
            result = runner.invoke(ui_module.ui_cmd, ["clear-focus", "demo", "--port", "9000", "--json"])

        assert result.exit_code == 1
        assert json.loads(result.output) == {
            "error": "server_unavailable",
            "port": 9000,
            "hint": "start one: pflow ui demo",
        }

    def test_422_renders_structured_diagnostic_without_traceback(self) -> None:
        payload = {
            "errors": [
                {
                    "severity": "error",
                    "message": "Unknown node type 'missing'.",
                    "source": "/workflows/demo.pflow.md",
                }
            ]
        }
        runner = CliRunner()
        with patch("httpx.request", return_value=_response(422, payload)):
            result = runner.invoke(ui_module.ui_cmd, ["focus", "demo", "greet"])

        assert result.exit_code == 1
        assert "Unknown node type 'missing'" in result.output
        assert "Traceback" not in result.output

    def test_422_json_mode_passes_server_error_body_through(self) -> None:
        payload = {
            "errors": [
                {
                    "severity": "error",
                    "message": "Unknown node type 'missing'.",
                    "source": "/workflows/demo.pflow.md",
                }
            ]
        }
        runner = CliRunner()
        with patch("httpx.request", return_value=_response(422, payload)):
            result = runner.invoke(ui_module.ui_cmd, ["focus", "demo", "greet", "--json"])

        assert result.exit_code == 1
        assert json.loads(result.output) == payload

    def test_open_never_duplicates_an_existing_background_window(self) -> None:
        payload = {
            **_dispatch_payload(),
            "windows": [{"visibility": "hidden"}],
        }
        runner = CliRunner()
        with (
            patch("httpx.request", return_value=_response(200, payload)),
            patch("webbrowser.open") as open_browser,
        ):
            result = runner.invoke(ui_module.ui_cmd, ["focus", "demo", "greet", "--open"])

        assert result.exit_code == 0, result.output
        assert "1 backgrounded" in result.output
        open_browser.assert_not_called()

    def test_open_loads_then_reposts_non_edge_target_when_viewer_connects(self) -> None:
        zero = _dispatch_payload(sent_to=0)
        connected = _dispatch_payload(sent_to=1)
        runner = CliRunner()
        with (
            patch("httpx.request", side_effect=[_response(200, zero), _response(200, connected)]) as request,
            patch("webbrowser.open") as open_browser,
            patch("time.sleep"),
        ):
            result = runner.invoke(ui_module.ui_cmd, ["focus", "demo", "greet", "--open"])

        assert result.exit_code == 0, result.output
        assert request.call_count == 2
        open_browser.assert_called_once_with("http://127.0.0.1:8765/?workflow=demo&focus=greet")
        assert "sent to 1 window" in result.output

    def test_edge_open_reposts_until_viewer_connects(self) -> None:
        zero = _dispatch_payload(sent_to=0)
        connected = _dispatch_payload(sent_to=1)
        runner = CliRunner()
        with (
            patch("httpx.request", side_effect=[_response(200, zero), _response(200, connected)]) as request,
            patch("webbrowser.open") as open_browser,
            patch("time.sleep"),
        ):
            result = runner.invoke(
                ui_module.ui_cmd,
                ["focus", "demo", "gen.response -> use.prompt", "--open"],
            )

        assert result.exit_code == 0, result.output
        assert request.call_count == 2
        open_browser.assert_called_once_with("http://127.0.0.1:8765/?workflow=demo")
        assert "sent to 1 window" in result.output

    def test_edge_open_timeout_has_distinct_rerun_message(self) -> None:
        runner = CliRunner()
        with (
            patch("httpx.request", return_value=_response(200, _dispatch_payload(sent_to=0))),
            patch("webbrowser.open"),
            patch.object(ui_module, "_OPEN_TIMEOUT_S", 0.0),
        ):
            result = runner.invoke(
                ui_module.ui_cmd,
                ["focus", "demo", "gen.response -> use.prompt", "--open"],
            )

        assert result.exit_code == 1, result.output
        assert "didn't connect within 15s" in result.output
        assert "re-run `pflow ui focus demo" in result.output
        assert "0 windows" not in result.output


class TestUserActivityCommand:
    def test_empty_filtered_activity_is_explicit(self) -> None:
        payload = {"events": [], "workflow_key": "/workflows/demo.pflow.md"}
        runner = CliRunner()
        with patch("httpx.request", return_value=_response(200, payload)):
            result = runner.invoke(ui_module.ui_cmd, ["user-activity", "demo"])

        assert result.exit_code == 0, result.output
        assert "user-activity 'demo' (0 events)" in result.output
        assert "server up, no interactions recorded for this workflow key" in result.output
        assert "/workflows/demo.pflow.md" in result.output

    def test_activity_formats_structural_and_flat_identity_with_view_state(self) -> None:
        payload = {
            "workflow_key": "/workflows/demo.pflow.md",
            "events": [
                {
                    "ts": 1_750_000_000.0,
                    "age_seconds": 0.25,
                    "type": "node_click",
                    "target": {
                        "kind": "node",
                        "flat_id": "n3",
                        "ref": {
                            "node_id": "greet",
                            "ancestor_path": [{"node_id": "child", "batch_index": 2}],
                            "port": None,
                        },
                    },
                    "view_state": {"density": "beautiful", "direction": "LR", "focus": "greet"},
                    "workflow_key": "/workflows/demo.pflow.md",
                }
            ],
        }
        runner = CliRunner()
        with patch("httpx.request", return_value=_response(200, payload)):
            result = runner.invoke(ui_module.ui_cmd, ["user-activity", "demo"])

        assert result.exit_code == 0, result.output
        assert "child[2].greet [n3]" in result.output
        assert "beautiful/LR · focus greet" in result.output
        assert "0.2s ago" in result.output

    def test_nested_io_activity_uses_round_trippable_point_grammar(self) -> None:
        payload = {
            "workflow_key": "/workflows/demo.pflow.md",
            "events": [
                {
                    "ts": 1_750_000_000.0,
                    "age_seconds": 1.0,
                    "type": "port_click",
                    "target": {
                        "kind": "node",
                        "flat_id": "p3",
                        "ref": {
                            "node_id": "data",
                            "ancestor_path": [{"node_id": "child", "batch_index": None}],
                            "port": "in",
                        },
                    },
                    "view_state": {"density": "advanced", "direction": "TD", "focus": "data"},
                }
            ],
        }
        runner = CliRunner()
        with patch("httpx.request", return_value=_response(200, payload)):
            result = runner.invoke(ui_module.ui_cmd, ["user-activity", "demo"])

        assert result.exit_code == 0, result.output
        assert "in:child.data [p3]" in result.output
