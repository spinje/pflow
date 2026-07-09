"""CLI contract tests for Point and Watch commands under ``pflow ui``."""

from __future__ import annotations

import base64
import io
import json
import wave
from unittest.mock import patch

import httpx
from click.testing import CliRunner

from pflow.cli.commands import ui as ui_module
from pflow.core.exceptions import MissingApiKeyError, TTSSynthesisError


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
            patch("uvicorn.Server.run") as run,
        ):
            result = runner.invoke(ui_module.ui_cmd, ["./focus.pflow.md", "--no-open"])

        assert result.exit_code == 0, result.output
        assert "workflow=.%2Ffocus.pflow.md" in result.output
        run.assert_called_once()

    def test_no_auto_update_preserves_private_watch_query_param(self) -> None:
        runner = CliRunner()
        with (
            patch.object(ui_module, "_port_available", return_value=True),
            patch("uvicorn.Server.run"),
        ):
            result = runner.invoke(ui_module.ui_cmd, ["demo", "--no-open", "--no-auto-update"])

        assert result.exit_code == 0, result.output
        assert "workflow=demo&watch=0" in result.output

    def test_explicit_serve_accepts_workflow_after_options(self) -> None:
        runner = CliRunner()
        with (
            patch.object(ui_module, "_port_available", return_value=True),
            patch("uvicorn.Server.run") as run,
        ):
            result = runner.invoke(ui_module.ui_cmd, ["serve", "--port", "8894", "--no-open", "demo"])

        assert result.exit_code == 0, result.output
        assert "http://127.0.0.1:8894/?workflow=demo" in result.output
        run.assert_called_once()

    def test_shorthand_accepts_workflow_after_options(self) -> None:
        runner = CliRunner()
        with (
            patch.object(ui_module, "_port_available", return_value=True),
            patch("uvicorn.Server.run") as run,
        ):
            result = runner.invoke(ui_module.ui_cmd, ["--port", "8894", "--no-open", "demo"])

        assert result.exit_code == 0, result.output
        assert "http://127.0.0.1:8894/?workflow=demo" in result.output
        run.assert_called_once()


class TestServeRun:
    """`pflow ui <wf> --run <id>` (Task 175): smart open-or-switch. Fresh/no-viewer → open a pinned tab;
    a live Viewer of the workflow → switch it via a select-run broadcast (no duplicate tab)."""

    def test_serve_url_pins_the_run_id(self) -> None:
        url = ui_module._serve_url(8765, "demo", False, run="abc123")
        assert "workflow=demo" in url and "run=abc123" in url

    def test_fresh_start_opens_a_pinned_tab(self) -> None:
        runner = CliRunner()
        with patch.object(ui_module, "_port_available", return_value=True), patch("uvicorn.Server.run"):
            result = runner.invoke(ui_module.ui_cmd, ["demo", "--run", "abc123", "--no-open"])
        assert result.exit_code == 0, result.output
        assert "run=abc123" in result.output  # a fresh start has no Viewer to switch → opens pinned

    def test_reuse_with_a_live_viewer_switches_it_via_select_run(self) -> None:
        runner = CliRunner()
        with (
            patch.object(ui_module, "_port_available", return_value=False),
            patch.object(ui_module, "_probe_health", return_value={"service": "pflow-ui", "windows": 1}),
            patch(
                "httpx.request",
                return_value=_response(
                    200, {"sent_to": 1, "windows": [{"visibility": "visible"}], "workflow_key": "k"}
                ),
            ) as request,
            patch("webbrowser.open") as wb_open,
        ):
            result = runner.invoke(ui_module.ui_cmd, ["demo", "--run", "abc123"])
        assert result.exit_code == 0, result.output
        assert request.call_args.kwargs["json"] == {"workflow": "demo", "type": "select-run", "target": "abc123"}
        # select-run is latched (Issue #539), so this reliably steers the open window (live or on return) —
        # report the steer plainly rather than hedging.
        assert "steering it to run abc123" in result.output
        wb_open.assert_not_called()  # no duplicate tab

    def test_reuse_without_a_viewer_opens_a_pinned_tab(self) -> None:
        runner = CliRunner()
        with (
            patch.object(ui_module, "_port_available", return_value=False),
            patch.object(ui_module, "_probe_health", return_value={"service": "pflow-ui", "windows": 0}),
            patch("httpx.request") as request,
            patch("webbrowser.open") as wb_open,
        ):
            result = runner.invoke(ui_module.ui_cmd, ["demo", "--run", "abc123"])
        assert result.exit_code == 0, result.output
        assert "run=abc123" in result.output  # no live Viewer → open a pinned tab
        request.assert_not_called()  # no select-run POST — nothing to switch
        wb_open.assert_called_once()

    def test_run_without_a_workflow_errors_actionably(self) -> None:
        result = CliRunner().invoke(ui_module.serve_cmd, ["--run", "abc123"])
        assert result.exit_code == 1
        assert "needs a workflow" in result.output


class TestPointCommands:
    def test_json_mode_passes_server_payload_through(self) -> None:
        payload = _dispatch_payload()
        runner = CliRunner()
        with patch("httpx.request", return_value=_response(200, payload)):
            result = runner.invoke(ui_module.ui_cmd, ["frame", "demo", "greet", "--output-format", "json"])

        assert result.exit_code == 0, result.output
        assert json.loads(result.output) == payload

    def test_frame_zero_windows_does_not_suggest_unsupported_open_flag(self) -> None:
        runner = CliRunner()
        with patch("httpx.request", return_value=_response(200, _dispatch_payload(sent_to=0))):
            result = runner.invoke(ui_module.ui_cmd, ["frame", "demo", "greet"])

        assert result.exit_code == 1, result.output
        assert "open the workflow first" in result.output
        assert "--open" not in result.output

    def test_clear_focus_zero_windows_says_nothing_to_clear_not_open_first(self) -> None:
        # Clearing with no Viewer open has nothing to clear; the "open the workflow
        # first" hint would be circular (open a window only to clear focus on it).
        payload = {"sent_to": 0, "windows": [], "workflow_key": "/workflows/demo.pflow.md"}
        runner = CliRunner()
        with patch("httpx.request", return_value=_response(200, payload)):
            result = runner.invoke(ui_module.ui_cmd, ["clear-focus", "demo"])

        assert result.exit_code == 1, result.output
        assert "nothing to clear" in result.output
        assert "open the workflow first" not in result.output

    def test_zero_window_focus_omits_the_vacuous_visibility_breakdown(self) -> None:
        # At 0 windows the "(0 visible, 0 backgrounded)" split is just 0 = 0 + 0.
        runner = CliRunner()
        with patch("httpx.request", return_value=_response(200, _dispatch_payload(sent_to=0))):
            result = runner.invoke(ui_module.ui_cmd, ["focus", "demo", "greet"])

        assert result.exit_code == 1, result.output
        assert "sent to 0 windows" in result.output
        assert "0 visible, 0 backgrounded" not in result.output
        assert "--open" in result.output

    def test_focus_to_only_background_tabs_says_to_switch_to_it(self) -> None:
        # Delivered to >=1 window but every one is a background tab: the highlight
        # applied where the user isn't looking, so the report must say what to do.
        payload = {
            "resolved": {"matched": 1, "address": "greet"},
            "sent_to": 1,
            "windows": [{"visibility": "hidden"}],
            "workflow_key": "/workflows/demo.pflow.md",
        }
        runner = CliRunner()
        with patch("httpx.request", return_value=_response(200, payload)):
            result = runner.invoke(ui_module.ui_cmd, ["focus", "demo", "greet"])

        assert result.exit_code == 0, result.output
        assert "0 visible, 1 backgrounded" in result.output
        assert "background tab" in result.output
        assert "switch to it" in result.output

    def test_unresolved_target_exits_nonzero_with_json_payload_intact(self) -> None:
        payload = {
            "resolved": {"matched": 0, "suggestions": ["greet"]},
            "sent_to": 0,
            "windows": [],
            "workflow_key": "/workflows/demo.pflow.md",
        }
        runner = CliRunner()
        with patch("httpx.request", return_value=_response(200, payload)):
            result = runner.invoke(ui_module.ui_cmd, ["focus", "demo", "grete", "--output-format", "json"])

        assert result.exit_code == 1
        assert json.loads(result.output) == payload

    def test_not_found_without_suggestions_orients_to_file_vocabulary(self) -> None:
        payload = {
            "resolved": {"matched": 0, "suggestions": []},
            "sent_to": 0,
            "windows": [],
            "workflow_key": "/workflows/demo.pflow.md",
        }
        runner = CliRunner()
        with patch("httpx.request", return_value=_response(200, payload)):
            result = runner.invoke(ui_module.ui_cmd, ["focus", "demo", "xyzzy"])

        assert result.exit_code == 1
        assert "not found." in result.output
        assert "names from the workflow file" in result.output
        # Nothing close — don't fabricate a "did you mean".
        assert "Did you mean" not in result.output

    def test_not_found_with_suggestions_stays_terse(self) -> None:
        payload = {
            "resolved": {"matched": 0, "suggestions": ["process_content"]},
            "sent_to": 0,
            "windows": [],
            "workflow_key": "/workflows/demo.pflow.md",
        }
        runner = CliRunner()
        with patch("httpx.request", return_value=_response(200, payload)):
            result = runner.invoke(ui_module.ui_cmd, ["focus", "demo", "proces"])

        assert result.exit_code == 1
        assert "Did you mean: process_content?" in result.output
        # The orientation line is only for the no-suggestion dead-end.
        assert "names from the workflow file" not in result.output

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
            result = runner.invoke(
                ui_module.ui_cmd, ["clear-focus", "demo", "--port", "9000", "--output-format", "json"]
            )

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
            result = runner.invoke(ui_module.ui_cmd, ["focus", "demo", "greet", "--output-format", "json"])

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
            # The open-loop polls the cheap /api/health window count (via _probe_health),
            # NOT the command endpoint. Simulate the Viewer registering its SSE
            # connection on the second poll so the loop exercises its real
            # break-on-connect path. Without this the probe (unmocked httpx.get to a
            # dead port) returns None every iteration and the loop spins the full
            # _OPEN_TIMEOUT_S (15s) — patching time.sleep does NOT help, the deadline
            # is a real-wall-clock time.monotonic() bound.
            patch.object(ui_module, "_probe_health", side_effect=[{"windows": 0}, {"windows": 1}]) as probe,
            patch("time.sleep"),
        ):
            result = runner.invoke(ui_module.ui_cmd, ["focus", "demo", "greet", "--open"])

        assert result.exit_code == 0, result.output
        assert request.call_count == 2
        assert probe.call_count == 2  # polled until the window registered
        open_browser.assert_called_once_with("http://127.0.0.1:8765/?workflow=demo&focus=greet")
        assert "sent to 1 window" in result.output

    def test_edge_open_reposts_until_viewer_connects(self) -> None:
        zero = _dispatch_payload(sent_to=0)
        connected = _dispatch_payload(sent_to=1)
        runner = CliRunner()
        with (
            patch("httpx.request", side_effect=[_response(200, zero), _response(200, connected)]) as request,
            patch("webbrowser.open") as open_browser,
            # See sibling test: mock the health poll so the loop breaks on connect
            # instead of spinning to the real 15s _OPEN_TIMEOUT_S deadline.
            patch.object(ui_module, "_probe_health", side_effect=[{"windows": 0}, {"windows": 1}]) as probe,
            patch("time.sleep"),
        ):
            result = runner.invoke(
                ui_module.ui_cmd,
                ["focus", "demo", "gen.response -> use.prompt", "--open"],
            )

        assert result.exit_code == 0, result.output
        assert request.call_count == 2
        assert probe.call_count == 2  # polled until the window registered
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


class TestSayNarration:
    """``pflow ui focus/frame --say`` (Task 174) — synthesize CLI-side, POST to ``/api/say``, and never
    let a synthesis failure drop the point. ``pflow.core.tts.synthesize`` is patched where the lazy
    import resolves it (at call time)."""

    def test_focus_say_posts_to_api_say_with_stripped_caption(self) -> None:
        runner = CliRunner()
        with (
            patch("httpx.request", return_value=_response(200, _dispatch_payload())) as request,
            patch("pflow.core.tts.synthesize", return_value=b"WAVDATA") as synth,
        ):
            result = runner.invoke(
                ui_module.ui_cmd, ["focus", "demo", "greet", "--say", "[excited] hi", "--port", "9123"]
            )

        assert result.exit_code == 0, result.output
        assert request.call_args.args[:2] == ("POST", "http://127.0.0.1:9123/api/say")
        body = request.call_args.kwargs["json"]
        assert body["type"] == "focus"
        assert body["target"] == "greet"
        assert body["caption"] == "hi"  # [excited] stripped
        assert body["audio_b64"] == base64.b64encode(b"WAVDATA").decode("ascii")
        # The RAW text (tags included) is synthesized; only the caption is stripped.
        assert synth.call_args.args[0] == "[excited] hi"

    def test_frame_say_posts_to_api_say_with_frame_type(self) -> None:
        runner = CliRunner()
        with (
            patch("httpx.request", return_value=_response(200, _dispatch_payload())) as request,
            patch("pflow.core.tts.synthesize", return_value=b"WAV"),
        ):
            result = runner.invoke(ui_module.ui_cmd, ["frame", "demo", "greet", "--say", "hi"])

        assert result.exit_code == 0, result.output
        assert request.call_args.args[:2] == ("POST", "http://127.0.0.1:8765/api/say")
        assert request.call_args.kwargs["json"]["type"] == "frame"

    def test_synthesis_failure_posts_caption_only_and_exits_zero(self) -> None:
        runner = CliRunner()
        with (
            patch("httpx.request", return_value=_response(200, _dispatch_payload())) as request,
            patch("pflow.core.tts.synthesize", side_effect=TTSSynthesisError("boom")),
        ):
            result = runner.invoke(ui_module.ui_cmd, ["focus", "demo", "greet", "--say", "hi"])

        assert result.exit_code == 0, result.output
        body = request.call_args.kwargs["json"]
        assert body["caption"] == "hi"
        assert "audio_b64" not in body  # caption-only — the point still delivered
        assert "narration unavailable: boom" in result.output

    def test_synthesis_failure_json_mode_splits_stdout_and_stderr(self) -> None:
        runner = CliRunner(mix_stderr=False)
        with (
            patch("httpx.request", return_value=_response(200, _dispatch_payload())),
            patch("pflow.core.tts.synthesize", side_effect=TTSSynthesisError("boom")),
        ):
            result = runner.invoke(
                ui_module.ui_cmd, ["focus", "demo", "greet", "--say", "hi", "--output-format", "json"]
            )

        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert payload["narration"] == {
            "audio": False,
            "reason": "boom",
            "reason_kind": "synthesis_failed",
            "duration_s": None,
        }
        assert "narration unavailable: boom" in result.stderr  # note on stderr keeps stdout parseable

    def test_missing_api_key_reports_reason_kind_missing_key(self) -> None:
        runner = CliRunner(mix_stderr=False)
        with (
            patch("httpx.request", return_value=_response(200, _dispatch_payload())),
            patch("pflow.core.tts.synthesize", side_effect=MissingApiKeyError("no key: settings set-env ...")),
        ):
            result = runner.invoke(
                ui_module.ui_cmd, ["focus", "demo", "greet", "--say", "hi", "--output-format", "json"]
            )

        assert result.exit_code == 0, result.output
        assert json.loads(result.stdout)["narration"]["reason_kind"] == "missing_key"

    def test_bare_runtime_error_backstop_still_posts_and_exits_zero(self) -> None:
        # A stray crash inside synthesize must degrade to caption-only, never drop the point.
        runner = CliRunner()
        with (
            patch("httpx.request", return_value=_response(200, _dispatch_payload())) as request,
            patch("pflow.core.tts.synthesize", side_effect=RuntimeError("unexpected")),
        ):
            result = runner.invoke(ui_module.ui_cmd, ["focus", "demo", "greet", "--say", "hi"])

        assert result.exit_code == 0, result.output
        assert "audio_b64" not in request.call_args.kwargs["json"]
        assert "narration unavailable: unexpected" in result.output

    def test_over_length_say_is_rejected_before_any_request(self) -> None:
        runner = CliRunner()
        with patch("httpx.request") as request:
            result = runner.invoke(ui_module.ui_cmd, ["focus", "demo", "greet", "--say", "x" * 1501])

        assert result.exit_code != 0
        assert "max 1500" in result.output
        request.assert_not_called()

    def test_tags_only_say_is_rejected(self) -> None:
        runner = CliRunner()
        with patch("httpx.request") as request:
            result = runner.invoke(ui_module.ui_cmd, ["focus", "demo", "greet", "--say", "[only-tags]"])

        assert result.exit_code != 0
        assert "only [delivery] tags" in result.output
        request.assert_not_called()

    def test_empty_say_is_rejected(self) -> None:
        # An empty --say "" (e.g. an agent passing an empty variable) is a usage error, not a silent
        # no-op, and the message must not send the agent hunting for [tags] that aren't there.
        runner = CliRunner()
        with patch("httpx.request") as request:
            result = runner.invoke(ui_module.ui_cmd, ["focus", "demo", "greet", "--say", ""])

        assert result.exit_code != 0
        assert "no speakable text" in result.output
        request.assert_not_called()

    def test_bare_focus_still_posts_to_api_command(self) -> None:
        # Regression: no --say leaves the Task 169 body/endpoint untouched.
        runner = CliRunner()
        with patch("httpx.request", return_value=_response(200, _dispatch_payload())) as request:
            result = runner.invoke(ui_module.ui_cmd, ["focus", "demo", "greet"])

        assert result.exit_code == 0, result.output
        assert request.call_args.args[:2] == ("POST", "http://127.0.0.1:8765/api/command")
        assert request.call_args.kwargs["json"] == {"workflow": "demo", "type": "focus", "target": "greet"}

    def test_bare_frame_still_posts_to_api_command(self) -> None:
        runner = CliRunner()
        with patch("httpx.request", return_value=_response(200, _dispatch_payload())) as request:
            result = runner.invoke(ui_module.ui_cmd, ["frame", "demo", "greet"])

        assert result.exit_code == 0, result.output
        assert request.call_args.args[:2] == ("POST", "http://127.0.0.1:8765/api/command")
        assert request.call_args.kwargs["json"] == {"workflow": "demo", "type": "frame", "target": "greet"}

    def test_open_say_resends_to_api_say_and_synthesizes_once(self) -> None:
        zero = _dispatch_payload(sent_to=0)
        connected = _dispatch_payload(sent_to=1)
        runner = CliRunner()
        with (
            patch("httpx.request", side_effect=[_response(200, zero), _response(200, connected)]) as request,
            patch("webbrowser.open"),
            # Pitfall #21: the monotonic deadline ignores a patched sleep — mock the health poll to
            # break on connect, otherwise the loop spins the real 15s _OPEN_TIMEOUT_S.
            patch.object(ui_module, "_probe_health", side_effect=[{"windows": 0}, {"windows": 1}]),
            patch("time.sleep"),
            patch("pflow.core.tts.synthesize", return_value=b"WAV") as synth,
        ):
            result = runner.invoke(ui_module.ui_cmd, ["focus", "demo", "greet", "--say", "hi", "--open"])

        assert result.exit_code == 0, result.output
        assert request.call_count == 2
        # BOTH the initial send and the re-send go to /api/say...
        assert [call.args[:2] for call in request.call_args_list] == [
            ("POST", "http://127.0.0.1:8765/api/say"),
            ("POST", "http://127.0.0.1:8765/api/say"),
        ]
        # ...but synthesis happens exactly ONCE (the re-send reuses the same audio).
        assert synth.call_count == 1
        assert request.call_args_list[1].kwargs["json"]["audio_b64"] == base64.b64encode(b"WAV").decode("ascii")

    def test_inject_settings_env_vars_called_on_say_path_only(self) -> None:
        runner = CliRunner()
        with (
            patch("httpx.request", return_value=_response(200, _dispatch_payload())),
            patch("pflow.core.tts.synthesize", return_value=b"WAV"),
            patch("pflow.core.llm_config.inject_settings_env_vars") as inject,
        ):
            runner.invoke(ui_module.ui_cmd, ["focus", "demo", "greet", "--say", "hi"])
            assert inject.call_count == 1

        with (
            patch("httpx.request", return_value=_response(200, _dispatch_payload())),
            patch("pflow.core.llm_config.inject_settings_env_vars") as inject_bare,
        ):
            runner.invoke(ui_module.ui_cmd, ["focus", "demo", "greet"])
            inject_bare.assert_not_called()


def _wav_of(seconds: float) -> bytes:
    """A real (silent) mono PCM16 WAV of exactly ``seconds`` at 24 kHz — pacing reads its header."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(24000)
        writer.writeframes(b"\x00\x00" * int(24000 * seconds))
    return buffer.getvalue()


class TestSayPacing:
    """``--say`` waits for the PREVIOUS clip to finish BEFORE dispatching (Task 174 follow-up v2):
    synthesis runs first (overlapping the playing clip), then the CLI reads the remainder off the
    server's ``/api/health`` (``narration_s_remaining``) and sleeps it out, THEN points. So
    sequential ``--say`` commands play back-to-back with ~no dead air. ``--no-wait`` interrupts;
    a bare focus/frame never waits (169 latency untouched)."""

    def test_say_waits_out_the_previous_clip_before_posting(self) -> None:
        events: list[tuple[str, object]] = []

        def record_request(method: str, url: str, **kwargs: object) -> httpx.Response:
            events.append(("post", url))
            return _response(200, _dispatch_payload())

        runner = CliRunner(mix_stderr=False)
        with (
            patch("httpx.request", side_effect=record_request),
            patch.object(
                ui_module, "_probe_health", return_value={"service": "pflow-ui", "narration_s_remaining": 2.5}
            ),
            patch("time.sleep", side_effect=lambda secs: events.append(("sleep", secs))),
            patch("pflow.core.tts.synthesize", return_value=_wav_of(1.0)),
        ):
            result = runner.invoke(
                ui_module.ui_cmd, ["focus", "demo", "greet", "--say", "hi", "--output-format", "json"]
            )

        assert result.exit_code == 0, result.output
        # The wait happens BEFORE the dispatch, for the PREVIOUS clip's remainder — and there is
        # NO post-dispatch sleep (the next command's synthesis overlaps this clip instead).
        assert [event for event in events if event[0] == "sleep"] == [("sleep", 2.5)]
        assert events[0] == ("sleep", 2.5)
        assert events[-1][0] == "post"
        assert json.loads(result.stdout)["narration"]["duration_s"] == 1.0  # own clip still reported

    def test_frame_say_waits_too(self) -> None:
        runner = CliRunner()
        with (
            patch("httpx.request", return_value=_response(200, _dispatch_payload())),
            patch.object(ui_module, "_probe_health", return_value={"narration_s_remaining": 1.5}),
            patch("time.sleep") as sleep,
            patch("pflow.core.tts.synthesize", return_value=_wav_of(1.0)),
        ):
            result = runner.invoke(ui_module.ui_cmd, ["frame", "demo", "greet", "--say", "hi"])

        assert result.exit_code == 0, result.output
        sleep.assert_called_once_with(1.5)

    def test_idle_server_means_no_wait(self) -> None:
        # First say of a sequence: nothing is playing → dispatch immediately.
        runner = CliRunner()
        with (
            patch("httpx.request", return_value=_response(200, _dispatch_payload())),
            patch.object(ui_module, "_probe_health", return_value={"narration_s_remaining": 0.0}),
            patch("time.sleep") as sleep,
            patch("pflow.core.tts.synthesize", return_value=_wav_of(1.0)),
        ):
            result = runner.invoke(ui_module.ui_cmd, ["focus", "demo", "greet", "--say", "hi"])

        assert result.exit_code == 0, result.output
        sleep.assert_not_called()

    def test_no_wait_skips_the_probe_and_posts_immediately(self) -> None:
        runner = CliRunner()
        with (
            patch("httpx.request", return_value=_response(200, _dispatch_payload())) as request,
            patch.object(ui_module, "_probe_health") as probe,
            patch("time.sleep") as sleep,
            patch("pflow.core.tts.synthesize", return_value=_wav_of(1.0)),
        ):
            result = runner.invoke(ui_module.ui_cmd, ["focus", "demo", "greet", "--say", "hi", "--no-wait"])

        assert result.exit_code == 0, result.output
        probe.assert_not_called()
        sleep.assert_not_called()
        assert request.call_args.args[1].endswith("/api/say")

    def test_bare_focus_never_probes_or_waits(self) -> None:
        # No --say → the Task 169 point path gains zero latency.
        runner = CliRunner()
        with (
            patch("httpx.request", return_value=_response(200, _dispatch_payload())),
            patch.object(ui_module, "_probe_health") as probe,
            patch("time.sleep") as sleep,
        ):
            result = runner.invoke(ui_module.ui_cmd, ["focus", "demo", "greet"])

        assert result.exit_code == 0, result.output
        probe.assert_not_called()
        sleep.assert_not_called()

    def test_unreachable_server_skips_the_wait_and_lets_dispatch_report(self) -> None:
        # _probe_health -> None (nothing listening): don't stall — the POST's own error handling owns it.
        runner = CliRunner()
        with (
            patch("httpx.request", return_value=_response(200, _dispatch_payload())),
            patch.object(ui_module, "_probe_health", return_value=None),
            patch("time.sleep") as sleep,
            patch("pflow.core.tts.synthesize", return_value=_wav_of(1.0)),
        ):
            result = runner.invoke(ui_module.ui_cmd, ["focus", "demo", "greet", "--say", "hi"])

        assert result.exit_code == 0, result.output
        sleep.assert_not_called()

    def test_synthesis_failure_still_waits_its_turn(self) -> None:
        # A caption-only step is still a walkthrough step: moving the camera mid-sentence is the
        # exact interruption feeling pacing exists to prevent.
        runner = CliRunner()
        with (
            patch("httpx.request", return_value=_response(200, _dispatch_payload())),
            patch.object(ui_module, "_probe_health", return_value={"narration_s_remaining": 1.2}),
            patch("time.sleep") as sleep,
            patch("pflow.core.tts.synthesize", side_effect=TTSSynthesisError("boom")),
        ):
            result = runner.invoke(ui_module.ui_cmd, ["focus", "demo", "greet", "--say", "hi"])

        assert result.exit_code == 0, result.output
        sleep.assert_called_once_with(1.2)

    def test_blocked_viewer_holds_the_walkthrough_until_unblocked_then_posts(self) -> None:
        # The Viewer beaconed an autoplay-blocked play(): the next --say HOLDS (polling health)
        # instead of marching past a silent window; the user's ▶ click starts the clip (started
        # beacon clears the flag) and the walkthrough resumes — waiting out that clip first.
        events: list[tuple[str, object]] = []
        health_states = iter([
            {"narration_s_remaining": 0.0, "narration_blocked": True},
            {"narration_s_remaining": 0.0, "narration_blocked": True},
            {"narration_s_remaining": 1.0, "narration_blocked": False},  # ▶ clicked; clip playing
        ])

        def record_request(method: str, url: str, **kwargs: object) -> httpx.Response:
            events.append(("post", url))
            return _response(200, _dispatch_payload())

        runner = CliRunner(mix_stderr=False)
        with (
            patch("httpx.request", side_effect=record_request),
            patch.object(ui_module, "_probe_health", side_effect=lambda port: next(health_states)),
            patch("time.sleep", side_effect=lambda secs: events.append(("sleep", secs))),
            patch("pflow.core.tts.synthesize", return_value=_wav_of(1.0)),
        ):
            result = runner.invoke(
                ui_module.ui_cmd, ["focus", "demo", "greet", "--say", "hi", "--output-format", "json"]
            )

        assert result.exit_code == 0, result.output
        # Two blocked polls, then the unblocking clip's remainder, THEN the dispatch.
        assert events == [("sleep", 0.5), ("sleep", 0.5), ("sleep", 1.0), ("post", events[-1][1])]
        assert str(events[-1][1]).endswith("/api/say")
        assert "holding the walkthrough" in result.stderr
        assert "resuming" in result.stderr
        json.loads(result.stdout)  # stdout stays a pure JSON payload (notes are stderr-only)

    def test_blocked_viewer_gives_up_after_the_poll_cap(self) -> None:
        runner = CliRunner(mix_stderr=False)
        with (
            patch("httpx.request", return_value=_response(200, _dispatch_payload())) as request,
            patch.object(
                ui_module,
                "_probe_health",
                return_value={"narration_s_remaining": 0.0, "narration_blocked": True},
            ) as probe,
            patch.object(ui_module, "_BLOCKED_MAX_POLLS", 3),
            patch("time.sleep") as sleep,
            patch("pflow.core.tts.synthesize", return_value=_wav_of(1.0)),
        ):
            result = runner.invoke(
                ui_module.ui_cmd, ["focus", "demo", "greet", "--say", "hi", "--output-format", "json"]
            )

        assert result.exit_code == 0, result.output
        assert probe.call_count == 3
        assert sleep.call_count == 3
        assert request.call_args.args[1].endswith("/api/say")  # still dispatched (captions show)
        assert "still blocked" in result.stderr

    def test_open_say_waits_once_before_the_first_post(self) -> None:
        # --open: the turn-wait happens ONCE, before the initial POST; the connect-poll's own
        # interval sleeps are a separate source (distinguished by value).
        events: list[tuple[str, object]] = []
        responses = iter([_response(200, _dispatch_payload(sent_to=0)), _response(200, _dispatch_payload())])

        def record_request(method: str, url: str, **kwargs: object) -> httpx.Response:
            events.append(("post", url))
            return next(responses)

        runner = CliRunner()
        with (
            patch("httpx.request", side_effect=record_request),
            patch("webbrowser.open"),
            patch.object(
                ui_module,
                "_probe_health",
                side_effect=[{"narration_s_remaining": 2.0}, {"windows": 1}],
            ),
            patch("time.sleep", side_effect=lambda secs: events.append(("sleep", secs))),
            patch("pflow.core.tts.synthesize", return_value=_wav_of(1.0)) as synth,
        ):
            result = runner.invoke(ui_module.ui_cmd, ["focus", "demo", "greet", "--say", "hi", "--open"])

        assert result.exit_code == 0, result.output
        assert synth.call_count == 1  # the re-send reuses the same audio
        assert [event for event in events if event == ("sleep", 2.0)] == [("sleep", 2.0)]
        assert events[0] == ("sleep", 2.0)  # turn-wait precedes the first POST
        say_posts = [event for event in events if event[0] == "post"]
        assert len(say_posts) == 2
        assert all(str(url).endswith("/api/say") for _, url in say_posts)


class TestUserActivityCommand:
    def test_empty_filtered_activity_is_explicit(self) -> None:
        payload = {"events": [], "workflow_key": "/workflows/demo.pflow.md"}
        runner = CliRunner()
        with patch("httpx.request", return_value=_response(200, payload)):
            result = runner.invoke(ui_module.ui_cmd, ["user-activity", "demo"])

        assert result.exit_code == 0, result.output
        assert "user-activity 'demo' (0 events)" in result.output
        assert "server up, no interactions recorded for this workflow" in result.output
        assert "/workflows/demo.pflow.md" in result.output

    def test_unfiltered_activity_does_not_leak_none_workflow_key(self) -> None:
        # No workflow arg → the server returns workflow_key: null. The text must not
        # echo a bare "workflow: None" (a Python repr leaking into agent output); the
        # "all workflows" label already conveys that nothing is filtered.
        payload = {"events": [], "workflow_key": None}
        runner = CliRunner()
        with patch("httpx.request", return_value=_response(200, payload)):
            result = runner.invoke(ui_module.ui_cmd, ["user-activity"])

        assert result.exit_code == 0, result.output
        assert "user-activity all workflows (0 events)" in result.output
        assert "server up, no interactions recorded yet" in result.output
        assert "None" not in result.output
        assert "workflow:" not in result.output

    def test_activity_renders_unfocused_view_state_without_python_none(self) -> None:
        # A pan / zoom / density-toggle event has no focused node → focus is null
        # over the wire. The line must read "focus none", never a raw Python "None".
        payload = {
            "workflow_key": "/workflows/demo.pflow.md",
            "events": [
                {
                    "ts": 1_750_000_000.0,
                    "age_seconds": 1.0,
                    "type": "density_change",
                    "target": None,
                    "view_state": {"density": "advanced", "direction": "LR", "focus": None},
                    "workflow_key": "/workflows/demo.pflow.md",
                }
            ],
        }
        runner = CliRunner()
        with patch("httpx.request", return_value=_response(200, payload)):
            result = runner.invoke(ui_module.ui_cmd, ["user-activity", "demo"])

        assert result.exit_code == 0, result.output
        assert "focus none" in result.output
        assert "None" not in result.output

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
