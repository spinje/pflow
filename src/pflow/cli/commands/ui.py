"""``pflow ui`` — serve and interact with the workflow Viewer.

The web stack (Starlette + uvicorn + the built frontend bundle) ships behind the
``pflow-cli[ui]`` extra. Serving imports it lazily so a base install still loads
the CLI. Point and Watch commands are thin HTTP clients for an already-running
server and use only the core ``httpx`` dependency.
"""

from __future__ import annotations

import base64
import json
import socket
import time
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import NoReturn
from urllib.parse import urlencode

import click
import httpx

from pflow.core.diagnostic import Diagnostic
from pflow.core.diagnostic_render import format_diagnostic

_HOST = "127.0.0.1"
_DEFAULT_PORT = 8765
_REQUEST_TIMEOUT_S = 5.0
_PROBE_TIMEOUT_S = 1.0
_OPEN_TIMEOUT_S = 15.0
_OPEN_INTERVAL_S = 0.25
# A typo must not synthesize a 10-minute clip. 1500 chars is ~90-100s of audio.
_SAY_MAX_CHARS = 1500


class UiGroup(click.Group):
    """Route a non-subcommand first argument to the hidden Viewer server."""

    ignore_unknown_options = True

    def resolve_command(
        self,
        ctx: click.Context,
        args: list[str],
    ) -> tuple[str | None, click.Command | None, list[str]]:
        if args and args[0] != "serve" and self.get_command(ctx, args[0]) is not None:
            return super().resolve_command(ctx, args)
        return "serve", self.get_command(ctx, "serve"), args


def _port_available(host: str, port: int) -> bool:
    """Whether ``(host, port)`` can be bound — mirrors uvicorn's SO_REUSEADDR bind."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind((host, port))
        except OSError:
            return False
    return True


def _open_browser_when_ready(host: str, port: int, url: str, *, timeout: float = 15.0) -> None:
    """Open the browser once the server is actually accepting connections."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.25)
            if probe.connect_ex((host, port)) == 0:
                break
        time.sleep(0.1)
    webbrowser.open(url)


def _viewer_url(port: int, workflow: str, *, focus: str | None = None) -> str:
    query = {"workflow": workflow}
    if focus is not None:
        query["focus"] = focus
    return f"http://{_HOST}:{port}/?{urlencode(query)}"


def _serve_url(port: int, workflow: str | None, no_auto_update: bool, run: str | None = None) -> str:
    """The browser URL ``serve`` opens — for both a fresh start and a reuse-existing.

    ``no_auto_update`` appends the private ``watch=0`` param that freezes the live
    source poll, so a reused tab honors ``--no-auto-update`` just like a fresh start.
    ``run`` appends ``?run=<id>`` (Task 175) so the opened tab pins/replays that run —
    the same contract the frontend reads at mount.
    """
    query: dict[str, str] = {}
    if workflow:
        query["workflow"] = workflow
    if run:
        query["run"] = run
    if no_auto_update:
        query["watch"] = "0"
    return f"http://{_HOST}:{port}/" + (f"?{urlencode(query)}" if query else "")


def _probe_health(port: int, workflow: str | None = None) -> dict[str, object] | None:
    """Return the ``/api/health`` body if a pflow viewer is on the port, else ``None``.

    Never raises or exits — unlike ``_request`` (which ``ctx.exit``s on any failure),
    this is safe to call in a poll loop and to probe a port that may hold a foreign
    process. Uses a short ``_PROBE_TIMEOUT_S`` so a non-pflow socket on the port does
    not stall the caller for the full ``_REQUEST_TIMEOUT_S`` before falling through.
    """
    params = {"workflow": workflow} if workflow else None
    try:
        response = httpx.get(f"http://{_HOST}:{port}/api/health", params=params, timeout=_PROBE_TIMEOUT_S)
        response.raise_for_status()
        body = response.json()
    except (httpx.HTTPError, ValueError):
        return None
    return body if isinstance(body, dict) and body.get("service") == "pflow-ui" else None


def _wants_json(ctx: click.Context, param: click.Parameter, value: str) -> bool:
    """Map the project-standard ``--output-format`` flag onto the internal bool.

    Keeps every command/helper signature on ``output_json: bool`` while the
    user-facing flag matches the rest of the CLI (``run``, ``probe``, ``settings``).
    """
    return value == "json"


def _request(
    ctx: click.Context,
    port: int,
    method: str,
    path: str,
    *,
    workflow: str | None,
    output_json: bool,
    json_body: dict[str, str] | None = None,
    params: dict[str, str] | None = None,
) -> dict[str, object]:
    """Call one local Viewer endpoint and own every expected failure mode."""
    try:
        response = httpx.request(
            method,
            f"http://{_HOST}:{port}{path}",
            timeout=_REQUEST_TIMEOUT_S,
            json=json_body,
            params=params,
        )
        response.raise_for_status()
    except httpx.ConnectError:
        command = f"pflow ui {workflow}" if workflow else "pflow ui"
        _fail(
            ctx,
            f"No pflow ui server on port {port}.\n→ start one: {command}",
            output_json=output_json,
            payload={"error": "server_unavailable", "port": port, "hint": f"start one: {command}"},
        )
    except httpx.RequestError as exc:
        _fail(
            ctx,
            f"Could not reach the pflow ui server on port {port}: {exc}\n"
            f"→ check that it is running and retry with the matching --port",
            output_json=output_json,
            payload={"error": "server_unreachable", "port": port, "detail": str(exc)},
        )
    except httpx.HTTPStatusError as exc:
        _render_http_error(ctx, exc.response, output_json=output_json)

    try:
        payload: object = response.json()
    except ValueError:
        _fail(ctx, "The pflow ui server returned invalid JSON.", output_json=output_json)
    if not isinstance(payload, dict):
        _fail(ctx, "The pflow ui server returned an unexpected JSON value.", output_json=output_json)
    return payload


def _fail(
    ctx: click.Context,
    message: str,
    *,
    output_json: bool,
    payload: dict[str, object] | None = None,
) -> NoReturn:
    if output_json:
        click.echo(json.dumps(payload or {"error": message}, indent=2))
    else:
        click.echo(message, err=True)
    ctx.exit(1)


def _response_object(response: httpx.Response) -> dict[str, object]:
    content_type = response.headers.get("content-type", "")
    try:
        raw_body: object = response.json() if "json" in content_type else {}
    except ValueError:
        raw_body = {}
    return raw_body if isinstance(raw_body, dict) else {}


def _render_validation_errors(body: dict[str, object]) -> bool:
    errors = body.get("errors")
    if not isinstance(errors, list):
        return False
    rendered = False
    for item in errors:
        if isinstance(item, dict):
            click.echo(format_diagnostic(Diagnostic.from_dict(item)), err=True)
            rendered = True
    return rendered


def _render_http_error(ctx: click.Context, response: httpx.Response, *, output_json: bool) -> NoReturn:
    body = _response_object(response)

    if output_json:
        payload = body or {"error": response.text or "server_error", "status_code": response.status_code}
        click.echo(json.dumps(payload, indent=2))
        ctx.exit(1)

    if response.status_code == 422:
        if not _render_validation_errors(body):
            click.echo(f"Workflow validation failed: {body or response.text}", err=True)
    elif response.status_code == 415:
        click.echo("Server requires Content-Type: application/json (client bug).", err=True)
    elif response.status_code == 404:
        message = body.get("error", "Workflow not found.")
        click.echo(str(message), err=True)
        suggestions = body.get("suggestions")
        if isinstance(suggestions, list) and suggestions:
            click.echo(f"Did you mean: {', '.join(str(item) for item in suggestions)}?", err=True)
    else:
        detail = body or response.text
        click.echo(f"Server error {response.status_code}: {detail}", err=True)
    ctx.exit(1)


def _int_field(payload: dict[str, object], name: str) -> int:
    value = payload.get(name)
    return value if isinstance(value, int) else 0


def _resolution(payload: dict[str, object]) -> dict[str, object]:
    value = payload.get("resolved")
    return value if isinstance(value, dict) else {}


def _dispatch_failed(payload: dict[str, object]) -> bool:
    resolution = _resolution(payload)
    if resolution and _int_field(resolution, "matched") != 1:
        return True
    return _int_field(payload, "sent_to") == 0


def _echo_workflow_key(payload: dict[str, object]) -> None:
    """Echo the resolved workflow key, but never the bare ``None`` an unfiltered
    ``user-activity`` returns — the ``all workflows`` label already conveys it."""
    key = payload.get("workflow_key")
    if key is not None:
        click.echo(f"  workflow: {key}")


def _visibilities(payload: dict[str, object]) -> list[str]:
    windows = payload.get("windows")
    if not isinstance(windows, list):
        return []
    return [
        visibility
        for window in windows
        if isinstance(window, dict) and isinstance(visibility := window.get("visibility"), str)
    ]


def _render_delivery(
    subject: str,
    resolution: dict[str, object] | None,
    payload: dict[str, object],
    *,
    workflow: str,
    opened: bool,
    open_supported: bool,
    clearing: bool = False,
) -> None:
    """The matched/sent report: how many windows received the command, their
    visibility, and what to do when nobody — or nobody looking — got it."""
    sent_to = _int_field(payload, "sent_to")
    visibilities = _visibilities(payload)
    visible = visibilities.count("visible")
    backgrounded = visibilities.count("hidden")
    window_word = "window" if sent_to == 1 else "windows"

    # The visible/backgrounded split only carries information once something was
    # sent — at 0 it is just 0 = 0 + 0. The `resolved 1` line already confirms the
    # target was valid; the hint below says what to do about the empty audience.
    if sent_to == 0:
        delivery = f"sent to 0 {window_word}"
    else:
        delivery = f"sent to {sent_to} {window_word} ({visible} visible, {backgrounded} backgrounded)"

    if resolution:
        click.echo(f"{subject}: resolved 1 ({resolution.get('address')}) · {delivery}")
    else:
        click.echo(f"{subject}: {delivery}")
    _echo_workflow_key(payload)

    if sent_to == 0 and clearing:
        # Nothing to clear when no Viewer is open; the "open the workflow first"
        # hint below would be circular here (open a window only to clear it).
        click.echo("  → no Viewer open — nothing to clear")
    elif sent_to == 0 and not opened and open_supported:
        click.echo(f"  → re-run with --open, or run `pflow ui {workflow}`")
    elif sent_to == 0 and not opened:
        click.echo(f"  → open the workflow first: `pflow ui {workflow}`")
    elif resolution and visible == 0 and not opened:
        # Reached >=1 window, but every one is a background tab — the target was
        # revealed where the user is not looking. The fix is to get them to the
        # tab, not to re-point; say so rather than leave a silent count. `not opened`
        # suppresses this for a window this invocation just opened (it lands in front).
        click.echo("  → the Viewer is a background tab — tell the user to switch to it to see it")


def _render_dispatch(
    action: str,
    workflow: str,
    target: str | None,
    payload: dict[str, object],
    *,
    open_supported: bool = False,
    opened: bool = False,
    clearing: bool = False,
) -> None:
    resolution = _resolution(payload)
    matched = _int_field(resolution, "matched")
    subject = f"{action} {target!r} in {workflow!r}" if target is not None else f"{action} in {workflow!r}"

    if resolution and matched == 0:
        suggestions = resolution.get("suggestions")
        if isinstance(suggestions, list) and suggestions:
            click.echo(f"{subject}: not found. Did you mean: {', '.join(str(item) for item in suggestions)}?")
        else:
            # No near-miss to offer — orient the agent to the file's vocabulary so
            # a fundamental mismatch (wrong workflow, wrong idea of the grammar)
            # recovers instead of dead-ending on a bare "not found".
            click.echo(f"{subject}: not found.")
            click.echo(
                "  Targets are names from the workflow file: a step, input, or output, or a connection `source -> target`."
            )
        return
    if matched > 1:
        click.echo(f"{subject}: ambiguous — {matched} matches, not sent. Qualify with one of:")
        qualify = resolution.get("qualify")
        if isinstance(qualify, list):
            for address in qualify:
                click.echo(f"  {address}")
        return

    _render_delivery(
        subject, resolution, payload, workflow=workflow, opened=opened, open_supported=open_supported, clearing=clearing
    )


def _emit_payload(payload: dict[str, object], output_json: bool) -> None:
    if output_json:
        click.echo(json.dumps(payload, indent=2))


def _point_request(
    ctx: click.Context,
    port: int,
    workflow: str,
    command_type: str,
    target: str,
    *,
    output_json: bool,
) -> dict[str, object]:
    return _request(
        ctx,
        port,
        "POST",
        "/api/command",
        workflow=workflow,
        output_json=output_json,
        json_body={"workflow": workflow, "type": command_type, "target": target},
    )


def _prepare_say(say: str) -> str:
    """Validate ``--say`` and return the caption (delivery tags stripped).

    Raises ``click.BadParameter`` (a usage error) on an over-length input or one
    that is nothing but ``[delivery]`` tags — the caption would be empty, so there
    is nothing to show or speak.
    """
    from pflow.core.tts import strip_delivery_tags

    if len(say) > _SAY_MAX_CHARS:
        raise click.BadParameter(f"--say is {len(say)} chars (max {_SAY_MAX_CHARS}).", param_hint="'--say'")
    caption = strip_delivery_tags(say)
    if not caption:
        # Accurate for BOTH an empty --say "" and a tags-only --say "[excited]": an agent passing an
        # empty variable must not be sent hunting for [tags] that aren't there.
        raise click.BadParameter(
            "--say has no speakable text — it is empty or only [delivery] tags, so nothing would be shown or spoken.",
            param_hint="'--say'",
        )
    return caption


def _synthesize_say(say: str) -> tuple[str | None, str | None, str | None]:
    """Synthesize ``--say`` to base64 audio. Returns ``(audio_b64, reason, reason_kind)``.

    Success: ``(b64, None, None)``. NEVER raises — this seam enforces the locked
    "synthesis failure is a report note, never an error" decision, so the catch is
    ``except Exception`` (a belt to ``synthesize()``'s own totality). A missing key
    is ``reason_kind="missing_key"``; any other failure (``TTSSynthesisError`` or a
    stray crash) is ``"synthesis_failed"`` — the point is never dropped.
    """
    from pflow.core.exceptions import MissingApiKeyError
    from pflow.core.llm_config import inject_settings_env_vars
    from pflow.core.settings import SettingsManager
    from pflow.core.tts import synthesize

    inject_settings_env_vars()  # push settings-stored keys into os.environ (ui.py never called this)
    llm = SettingsManager().load().llm
    try:
        audio = synthesize(say, model=llm.tts_model, voice=llm.tts_voice)
        return base64.b64encode(audio).decode("ascii"), None, None
    except MissingApiKeyError as exc:
        return None, str(exc), "missing_key"
    except Exception as exc:
        return None, str(exc), "synthesis_failed"


def _say_request(
    ctx: click.Context,
    port: int,
    workflow: str,
    command_type: str,
    target: str,
    caption: str,
    audio_b64: str | None,
    *,
    output_json: bool,
) -> dict[str, object]:
    json_body: dict[str, str] = {"workflow": workflow, "type": command_type, "target": target, "caption": caption}
    if audio_b64 is not None:
        json_body["audio_b64"] = audio_b64
    return _request(
        ctx,
        port,
        "POST",
        "/api/say",
        workflow=workflow,
        output_json=output_json,
        json_body=json_body,
    )


def _resolve_narration(say: str | None) -> tuple[str | None, str | None, str | None, str | None]:
    """Prepare + synthesize a ``--say`` request. Returns ``(caption, audio_b64, reason, reason_kind)``;
    an all-None tuple when ``--say`` was not given. ``_prepare_say`` may raise ``click.BadParameter``
    (a usage error the caller lets propagate); ``_synthesize_say`` never raises (caption-only degrade).
    """
    if say is None:
        return None, None, None, None
    caption = _prepare_say(say)
    audio_b64, reason, reason_kind = _synthesize_say(say)
    return caption, audio_b64, reason, reason_kind


def _send_point(
    ctx: click.Context,
    port: int,
    workflow: str,
    command_type: str,
    target: str,
    caption: str | None,
    audio_b64: str | None,
    *,
    output_json: bool,
) -> dict[str, object]:
    """Dispatch a point: a ``say`` (caption + optional audio) when ``--say`` produced a caption, else a
    bare ``focus``/``frame``. Concentrating the say-vs-point routing here keeps each command body linear
    and lets the ``--open`` re-send reuse the SAME ``audio_b64`` (never re-synthesize)."""
    if caption is not None:
        return _say_request(ctx, port, workflow, command_type, target, caption, audio_b64, output_json=output_json)
    return _point_request(ctx, port, workflow, command_type, target, output_json=output_json)


@click.group(cls=UiGroup, name="ui", invoke_without_command=True)
@click.pass_context
def ui_cmd(ctx: click.Context) -> None:
    """Serve the Viewer, Point at targets, or Watch deliberate user activity.

    Serve with ``pflow ui [WORKFLOW] [--port N] [--no-open]
    [--no-auto-update]``. A first argument other than a command is treated as
    the workflow to serve.

    Saved workflows named like a command remain reachable by path, for example
    ``pflow ui ./focus.pflow.md``.
    """
    # Click does not call resolve_command for an empty invoke_without_command
    # group. Preserve bare `pflow ui` by explicitly invoking the default here.
    if ctx.invoked_subcommand is None:
        ctx.invoke(serve_cmd)


@ui_cmd.command(name="serve", hidden=True, context_settings={"ignore_unknown_options": True})
@click.argument("workflow", required=False)
@click.option("--port", default=_DEFAULT_PORT, type=int, help="Port to serve on (default: 8765).")
@click.option("--no-open", is_flag=True, default=False, help="Do not open a browser window.")
@click.option(
    "--no-auto-update",
    is_flag=True,
    default=False,
    help="Freeze the view: don't live-update when the .pflow.md source changes.",
)
@click.option("--run", "run", default=None, help="Open the Viewer pinned to a past run's id (replay it).")
@click.pass_context
def serve_cmd(
    ctx: click.Context,
    workflow: str | None,
    port: int,
    no_open: bool,
    no_auto_update: bool,
    run: str | None,
) -> None:
    """Open a browser canvas and serve it until Ctrl+C.

    ``--run <id>`` opens the Viewer pinned to that past run (Task 175). If a Viewer of this workflow is
    already live, it SWITCHES that window to the run (a select-run broadcast) instead of opening a
    duplicate tab; otherwise it opens a fresh pinned tab. ``<id>`` is the run's ``execution_id``.
    """
    if run and not workflow:
        click.echo("`--run <id>` needs a workflow: `pflow ui <workflow> --run <id>`.", err=True)
        ctx.exit(1)
        return
    try:
        import starlette  # noqa: F401
        import uvicorn
    except ImportError:
        click.echo(
            "The 'pflow ui' web interface needs extra dependencies.\n→ uv tool install 'pflow-cli[ui]'",
            err=True,
        )
        ctx.exit(1)
        return

    from pflow.ui.server import create_app

    if not _port_available(_HOST, port):
        # Port taken. If it's our own viewer, reuse it (open a tab) rather than fail —
        # `pflow ui <wf>` becomes idempotent. A foreign process keeps the hard error.
        if _probe_health(port) is not None:
            # The already-running server may have a DIFFERENT cwd, so a relative path
            # would resolve against ITS cwd, not the caller's — opening the wrong/
            # missing workflow. Send an absolute path for a path-like arg; a saved
            # NAME resolves via the registry regardless of cwd, so leave it untouched.
            reuse_workflow = str(Path(workflow).resolve()) if workflow and Path(workflow).exists() else workflow
            # Smart --run (Task 175): if a Viewer of THIS workflow is already live, SWITCH it to the run via
            # a select-run broadcast rather than opening a duplicate tab. windows>0 = an SSE-connected
            # Viewer exists for reuse_workflow. Otherwise fall through to open a fresh pinned tab below.
            if run and reuse_workflow:
                health = _probe_health(port, reuse_workflow)
                if health is not None and _int_field(health, "windows") > 0:
                    _point_request(ctx, port, reuse_workflow, "select-run", run, output_json=False)
                    # `select-run` is latched (Issue #539), so this steers the open window whether it's
                    # visible (live) or backgrounded (caught up on return) — even if `windows` was counting a
                    # just-closing tab, the latch still delivers on reopen. So report the steer plainly.
                    click.echo(f"pflow UI already showing {reuse_workflow} — steering it to run {run}", err=True)
                    ctx.exit(0)
                    return
            url = _serve_url(port, reuse_workflow, no_auto_update, run=run)
            if not no_open:
                webbrowser.open(url)
                click.echo(f"pflow UI already running on port {port} — opened a view at {url}", err=True)
            else:
                click.echo(f"pflow UI already running on port {port} — view available at {url}", err=True)
            ctx.exit(0)
            return
        click.echo(
            f"Port {port} is already in use.\n→ try a different --port (e.g. --port {port + 1})",
            err=True,
        )
        ctx.exit(1)
        return

    app = create_app()
    # `watch=0` (in _serve_url) is the stable private CLI↔frontend URL contract; only
    # the user-facing flag is named --no-auto-update to avoid colliding with Watch.
    # A fresh start has no live Viewer to switch, so --run always opens a pinned tab.
    url = _serve_url(port, workflow, no_auto_update, run=run)

    if not no_open:
        import threading

        threading.Thread(
            target=_open_browser_when_ready,
            args=(_HOST, port, url),
            daemon=True,
        ).start()

    click.echo(f"Serving pflow UI at {url} (Ctrl+C to stop)", err=True)
    # Hand Ctrl+C to uvicorn cleanly. pflow's global SIGINT handler (main._handle_sigint → sys.exit(130)) is
    # for `pflow run`, not a long-lived server: uvicorn captures signals while serving and RE-RAISES SIGINT
    # into that handler on shutdown, so sys.exit(130) fires inside the event loop mid-teardown → a SystemExit
    # tangled with the connections it is force-cancelling (a traceback wall). Restore Python's default handler
    # so uvicorn owns the whole shutdown, and swallow the resulting KeyboardInterrupt for a clean exit.
    # timeout_graceful_shutdown bounds the wait on the overlay's long-lived SSE connections (they never close
    # on their own), so the first Ctrl+C exits instead of hanging forever.
    import contextlib
    import signal
    from types import FrameType

    # Close the overlay's long-lived SSE streams the moment Ctrl+C arrives — BEFORE uvicorn's graceful-wait
    # times out and FORCE-cancels them (which logs a CancelledError per stream). Wrapping uvicorn's own
    # handle_exit runs hub.shutdown() on the event loop, so each stream returns cleanly first.
    config = uvicorn.Config(app, host=_HOST, port=port, log_level="warning", timeout_graceful_shutdown=2)
    server = uvicorn.Server(config)
    _uvicorn_handle_exit = server.handle_exit

    def _handle_exit(sig: int, frame: FrameType | None) -> None:
        app.state.hub.shutdown()
        _uvicorn_handle_exit(sig, frame)

    server.handle_exit = _handle_exit  # type: ignore[method-assign]
    signal.signal(signal.SIGINT, signal.default_int_handler)
    with contextlib.suppress(KeyboardInterrupt):
        server.run()


_say_option = click.option(
    "--say",
    "say",
    default=None,
    help=(
        "Narrate this text aloud in the Viewer with an on-canvas caption. Delivery direction goes in "
        '[brackets] (e.g. "[excited] this node..."); bracketed tags shape the voice and are stripped '
        "from the caption."
    ),
)


@ui_cmd.command(name="focus")
@click.argument("workflow")
@click.argument("target")
@click.option("--open", "open_if_absent", is_flag=True, help="Open a Viewer when no window is connected.")
@_say_option
@click.option(
    "--output-format",
    "output_json",
    type=click.Choice(["text", "json"]),
    default="text",
    callback=_wants_json,
    help="Output format: text (default) or json.",
)
@click.option("--port", default=_DEFAULT_PORT, type=int, help="Viewer server port (default: 8765).")
@click.pass_context
def focus_cmd(
    ctx: click.Context,
    workflow: str,
    target: str,
    open_if_absent: bool,
    say: str | None,
    output_json: bool,
    port: int,
) -> None:
    """Focus TARGET in every Viewer showing WORKFLOW.

    TARGET is a name from the workflow file: a step (``process_content``), an
    input or output (``source_file``), or a connection
    (``gen.response -> summarize.prompt``). If a name matches more than one
    element the command replies with qualified addresses to pick from — you never
    have to guess the syntax.

    ``--say "text"`` also narrates the text aloud with an on-canvas caption.
    """
    caption, audio_b64, narration_reason, narration_kind = _resolve_narration(say)
    payload = _send_point(ctx, port, workflow, "focus", target, caption, audio_b64, output_json=output_json)
    opened = False
    timed_out = False
    if open_if_absent and _int_field(payload, "sent_to") == 0 and _int_field(_resolution(payload), "matched") == 1:
        opened = True
        is_edge = "->" in target
        webbrowser.open(_viewer_url(port, workflow, focus=None if is_edge else target))
        # Poll a CHEAP readiness signal (the live window count) instead of re-POSTing
        # the build-triggering `focus` on a timer (that re-ran the full graph build
        # ~60x). `windows > 0` means the Viewer has registered its SSE connection,
        # which only happens after its graph is built, so it is the same readiness
        # proxy the old `sent_to > 0` loop used.
        deadline = time.monotonic() + _OPEN_TIMEOUT_S
        while time.monotonic() < deadline:
            time.sleep(_OPEN_INTERVAL_S)
            health = _probe_health(port, workflow)
            if health is not None and _int_field(health, "windows") > 0:
                break
        # Deliver once after the loop, unconditionally: this makes `timed_out` reflect
        # a real send (a window that connects in the final poll interval must not be
        # reported "didn't connect"), and an edge focus can ONLY arrive over SSE — the
        # opened URL carries no edge focus. Re-send reuses the SAME audio_b64 (do NOT
        # re-synthesize). Applying a bare focus once is harmless.
        payload = _send_point(ctx, port, workflow, "focus", target, caption, audio_b64, output_json=output_json)
        timed_out = _int_field(payload, "sent_to") == 0

    if say is not None:
        # CLI-merged so JSON consumers see the narration outcome without substring-matching prose.
        payload["narration"] = {
            "audio": audio_b64 is not None,
            "reason": narration_reason,
            "reason_kind": narration_kind,
        }
    _emit_payload(payload, output_json)
    if not output_json and not timed_out:
        _render_dispatch(
            "focus",
            workflow,
            target,
            payload,
            open_supported=True,
            opened=opened,
        )
    if timed_out:
        # err=output_json routes this human note to stderr in JSON mode so the
        # parseable payload already emitted on stdout stays clean for consumers.
        click.echo(
            "Opened a window but it didn't connect within 15s.\n"
            f"→ re-run `pflow ui focus {workflow} {target!r}` now that it may be up.",
            err=output_json,
        )
    if narration_reason is not None:
        # A top-level statement (NOT gated by the timed_out/text-mode block above): the point still
        # delivered, so the caption showed — only the voice is missing. err=output_json keeps stdout
        # parseable in JSON mode (the exact `timed_out` routing precedent). Never exits non-zero.
        click.echo(f"narration unavailable: {narration_reason}", err=output_json)
    if _dispatch_failed(payload):
        ctx.exit(1)


@ui_cmd.command(name="frame")
@click.argument("workflow")
@click.argument("target")
@_say_option
@click.option(
    "--output-format",
    "output_json",
    type=click.Choice(["text", "json"]),
    default="text",
    callback=_wants_json,
    help="Output format: text (default) or json.",
)
@click.option("--port", default=_DEFAULT_PORT, type=int, help="Viewer server port (default: 8765).")
@click.pass_context
def frame_cmd(ctx: click.Context, workflow: str, target: str, say: str | None, output_json: bool, port: int) -> None:
    """Frame TARGET without changing focus state.

    TARGET uses the same names as ``pflow ui focus``. ``--say "text"`` also
    narrates the text aloud with an on-canvas caption.
    """
    caption, audio_b64, narration_reason, narration_kind = _resolve_narration(say)
    payload = _send_point(ctx, port, workflow, "frame", target, caption, audio_b64, output_json=output_json)
    if say is not None:
        payload["narration"] = {
            "audio": audio_b64 is not None,
            "reason": narration_reason,
            "reason_kind": narration_kind,
        }
    _emit_payload(payload, output_json)
    if not output_json:
        _render_dispatch("frame", workflow, target, payload)
    if narration_reason is not None:
        # Top-level: the caption showed even when synthesis failed. err=output_json keeps stdout clean.
        click.echo(f"narration unavailable: {narration_reason}", err=output_json)
    if _dispatch_failed(payload):
        ctx.exit(1)


@ui_cmd.command(name="clear-focus")
@click.argument("workflow")
@click.option(
    "--output-format",
    "output_json",
    type=click.Choice(["text", "json"]),
    default="text",
    callback=_wants_json,
    help="Output format: text (default) or json.",
)
@click.option("--port", default=_DEFAULT_PORT, type=int, help="Viewer server port (default: 8765).")
@click.pass_context
def clear_focus_cmd(ctx: click.Context, workflow: str, output_json: bool, port: int) -> None:
    """Clear focus in every Viewer showing WORKFLOW."""
    payload = _request(
        ctx,
        port,
        "POST",
        "/api/command",
        workflow=workflow,
        output_json=output_json,
        json_body={"workflow": workflow, "type": "clear"},
    )
    _emit_payload(payload, output_json)
    if not output_json:
        _render_dispatch("clear focus", workflow, None, payload, clearing=True)
    if _dispatch_failed(payload):
        ctx.exit(1)


def _target_address(target: object) -> tuple[str | None, str | None]:
    """Render a Watch event's structural target in the Point address grammar.

    Delegates to ``targets.address_for_target`` so the address shown by
    ``user-activity`` is the SAME grammar ``resolve_target`` accepts — an agent
    copies the line straight back into ``pflow ui focus``. One parser, no drift.
    Lazy import keeps ``pflow.ui.targets`` out of module load (the lazy-import
    boundary test asserts the server stack isn't pulled in by importing the CLI).
    """
    from pflow.ui.targets import address_for_target

    flat_id = target.get("flat_id") if isinstance(target, dict) and isinstance(target.get("flat_id"), str) else None
    return address_for_target(target), flat_id


def _format_age(value: object) -> str:
    if not isinstance(value, (int, float)):
        return "age unknown"
    return f"{value:.1f}s ago" if value < 60 else f"{value / 60:.1f}m ago"


def _render_activity(workflow: str | None, payload: dict[str, object]) -> None:
    events = payload.get("events")
    event_list = events if isinstance(events, list) else []
    label = repr(workflow) if workflow else "all workflows"
    count = len(event_list)
    event_word = "event" if count == 1 else "events"
    click.echo(f"user-activity {label} ({count} {event_word})")
    if not event_list:
        if workflow:
            click.echo("  server up, no interactions recorded for this workflow (is a window open on it?).")
        else:
            click.echo("  server up, no interactions recorded yet.")
        _echo_workflow_key(payload)
        return

    for raw_event in event_list:
        if not isinstance(raw_event, dict):
            continue
        timestamp = raw_event.get("ts")
        when = (
            datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat(timespec="seconds")
            if isinstance(timestamp, (int, float))
            else "timestamp unknown"
        )
        address, flat_id = _target_address(raw_event.get("target"))
        target_text = address or "no target"
        if flat_id:
            target_text += f" [{flat_id}]"
        view = raw_event.get("view_state")
        if isinstance(view, dict):
            density = view.get("density") or "unknown"
            direction = view.get("direction") or "unknown"
            focus = view.get("focus") or "none"
            state = f"{density}/{direction} · focus {focus}"
        else:
            state = "view state unknown"
        workflow_key = raw_event.get("workflow_key")
        workflow_text = f" · {workflow_key}" if workflow is None else ""
        click.echo(
            f"  {when} ({_format_age(raw_event.get('age_seconds'))}) "
            f"{raw_event.get('type')} · {target_text} · {state}{workflow_text}"
        )
    _echo_workflow_key(payload)


@ui_cmd.command(name="user-activity")
@click.argument("workflow", required=False)
@click.option(
    "--output-format",
    "output_json",
    type=click.Choice(["text", "json"]),
    default="text",
    callback=_wants_json,
    help="Output format: text (default) or json.",
)
@click.option("--port", default=_DEFAULT_PORT, type=int, help="Viewer server port (default: 8765).")
@click.pass_context
def user_activity_cmd(ctx: click.Context, workflow: str | None, output_json: bool, port: int) -> None:
    """Read recent deliberate Viewer interactions, newest first."""
    params = {"workflow": workflow} if workflow else None
    payload = _request(
        ctx,
        port,
        "GET",
        "/api/activity",
        workflow=workflow,
        output_json=output_json,
        params=params,
    )
    _emit_payload(payload, output_json)
    if not output_json:
        _render_activity(workflow, payload)


__all__ = ["ui_cmd"]
