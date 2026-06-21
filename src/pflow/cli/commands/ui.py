"""``pflow ui`` — serve and interact with the workflow Viewer.

The web stack (Starlette + uvicorn + the built frontend bundle) ships behind the
``pflow-cli[ui]`` extra. Serving imports it lazily so a base install still loads
the CLI. Point and Watch commands are thin HTTP clients for an already-running
server and use only the core ``httpx`` dependency.
"""

from __future__ import annotations

import json
import socket
import time
import webbrowser
from datetime import UTC, datetime
from typing import NoReturn
from urllib.parse import urlencode

import click
import httpx

from pflow.core.diagnostic import Diagnostic
from pflow.core.diagnostic_render import format_diagnostic

_HOST = "127.0.0.1"
_DEFAULT_PORT = 8765
_REQUEST_TIMEOUT_S = 5.0
_OPEN_TIMEOUT_S = 15.0
_OPEN_INTERVAL_S = 0.25


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


def _render_dispatch(
    action: str,
    workflow: str,
    target: str | None,
    payload: dict[str, object],
    *,
    open_supported: bool = False,
    opened: bool = False,
) -> None:
    resolution = _resolution(payload)
    matched = _int_field(resolution, "matched")
    subject = f"{action} {target!r} in {workflow!r}" if target is not None else f"{action} in {workflow!r}"

    if resolution and matched == 0:
        suggestions = resolution.get("suggestions")
        suffix = ""
        if isinstance(suggestions, list) and suggestions:
            suffix = f" Did you mean: {', '.join(str(item) for item in suggestions)}?"
        click.echo(f"{subject}: not found.{suffix}")
        return
    if matched > 1:
        click.echo(f"{subject}: ambiguous — {matched} matches, not sent. Qualify with one of:")
        qualify = resolution.get("qualify")
        if isinstance(qualify, list):
            for address in qualify:
                click.echo(f"  {address}")
        return

    sent_to = _int_field(payload, "sent_to")
    windows = payload.get("windows")
    visibilities = (
        [
            window.get("visibility")
            for window in windows
            if isinstance(window, dict) and isinstance(window.get("visibility"), str)
        ]
        if isinstance(windows, list)
        else []
    )
    visible = visibilities.count("visible")
    backgrounded = visibilities.count("hidden")
    window_word = "window" if sent_to == 1 else "windows"
    visibility = f"{visible} visible, {backgrounded} backgrounded"

    if resolution:
        address = resolution.get("address")
        click.echo(f"{subject}: resolved 1 ({address}) · sent to {sent_to} {window_word} ({visibility})")
    else:
        click.echo(f"{subject}: sent to {sent_to} {window_word} ({visibility})")
    click.echo(f"  workflow key: {payload.get('workflow_key')}")
    if sent_to == 0 and not opened and open_supported:
        click.echo(f"  → re-run with --open, or run `pflow ui {workflow}`")
    elif sent_to == 0 and not opened:
        click.echo(f"  → open the workflow first: `pflow ui {workflow}`")


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
@click.pass_context
def serve_cmd(
    ctx: click.Context,
    workflow: str | None,
    port: int,
    no_open: bool,
    no_auto_update: bool,
) -> None:
    """Open a browser canvas and serve it until Ctrl+C."""
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
        click.echo(
            f"Port {port} is already in use.\n→ try a different --port (e.g. --port {port + 1})",
            err=True,
        )
        ctx.exit(1)
        return

    app = create_app()
    url = f"http://{_HOST}:{port}/"
    query: dict[str, str] = {}
    if workflow:
        query["workflow"] = workflow
    if no_auto_update:
        # `watch` is the stable private CLI↔frontend URL contract. Only the
        # user-facing flag changed to avoid colliding with Watch terminology.
        query["watch"] = "0"
    if query:
        url += f"?{urlencode(query)}"

    if not no_open:
        import threading

        threading.Thread(
            target=_open_browser_when_ready,
            args=(_HOST, port, url),
            daemon=True,
        ).start()

    click.echo(f"Serving pflow UI at {url} (Ctrl+C to stop)", err=True)
    uvicorn.run(app, host=_HOST, port=port, log_level="warning")


@ui_cmd.command(name="focus")
@click.argument("workflow")
@click.argument("target")
@click.option("--open", "open_if_absent", is_flag=True, help="Open a Viewer when no window is connected.")
@click.option("--json", "output_json", is_flag=True, help="Output the server response as JSON.")
@click.option("--port", default=_DEFAULT_PORT, type=int, help="Viewer server port (default: 8765).")
@click.pass_context
def focus_cmd(
    ctx: click.Context,
    workflow: str,
    target: str,
    open_if_absent: bool,
    output_json: bool,
    port: int,
) -> None:
    """Focus TARGET in every Viewer showing WORKFLOW."""
    payload = _point_request(ctx, port, workflow, "focus", target, output_json=output_json)
    opened = False
    timed_out = False
    if open_if_absent and _int_field(payload, "sent_to") == 0 and _int_field(_resolution(payload), "matched") == 1:
        opened = True
        is_edge = "->" in target
        webbrowser.open(_viewer_url(port, workflow, focus=None if is_edge else target))
        # The URL focus parser accepts a bare node_id/flat id, but Point also
        # accepts qualified nested and in:/out: addresses. Re-send for every
        # target once the graph-ready Viewer subscribes; applying bare focus a
        # second time is harmless and keeps one reliable open path.
        deadline = time.monotonic() + _OPEN_TIMEOUT_S
        while time.monotonic() < deadline:
            time.sleep(_OPEN_INTERVAL_S)
            payload = _point_request(ctx, port, workflow, "focus", target, output_json=output_json)
            if _int_field(payload, "sent_to") > 0:
                break
        timed_out = _int_field(payload, "sent_to") == 0

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
        click.echo(
            "Opened a window but it didn't connect within 15s.\n"
            f"→ re-run `pflow ui focus {workflow} {target!r}` now that it may be up.",
            err=output_json,
        )
    if _dispatch_failed(payload):
        ctx.exit(1)


@ui_cmd.command(name="frame")
@click.argument("workflow")
@click.argument("target")
@click.option("--json", "output_json", is_flag=True, help="Output the server response as JSON.")
@click.option("--port", default=_DEFAULT_PORT, type=int, help="Viewer server port (default: 8765).")
@click.pass_context
def frame_cmd(ctx: click.Context, workflow: str, target: str, output_json: bool, port: int) -> None:
    """Frame TARGET without changing focus state."""
    payload = _point_request(ctx, port, workflow, "frame", target, output_json=output_json)
    _emit_payload(payload, output_json)
    if not output_json:
        _render_dispatch("frame", workflow, target, payload)
    if _dispatch_failed(payload):
        ctx.exit(1)


@ui_cmd.command(name="clear-focus")
@click.argument("workflow")
@click.option("--json", "output_json", is_flag=True, help="Output the server response as JSON.")
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
        _render_dispatch("clear focus", workflow, None, payload)
    if _dispatch_failed(payload):
        ctx.exit(1)


def _ref_address(ref: object) -> str | None:
    if not isinstance(ref, dict):
        return None
    node_id = ref.get("node_id")
    if not isinstance(node_id, str):
        return None
    segments: list[str] = []
    ancestors = ref.get("ancestor_path")
    if isinstance(ancestors, list):
        for ancestor in ancestors:
            if not isinstance(ancestor, dict) or not isinstance(ancestor.get("node_id"), str):
                continue
            segment = str(ancestor["node_id"])
            batch_index = ancestor.get("batch_index")
            if isinstance(batch_index, int):
                segment += f"[{batch_index}]"
            segments.append(segment)
    address = ".".join([*segments, node_id])
    port = ref.get("port")
    return f"{port}:{address}" if port in {"in", "out"} else address


def _target_address(target: object) -> tuple[str | None, str | None]:
    if not isinstance(target, dict):
        return None, None
    flat_id = target.get("flat_id") if isinstance(target.get("flat_id"), str) else None
    if target.get("kind") == "node":
        return _ref_address(target.get("ref")), flat_id
    if target.get("kind") != "edge":
        return None, flat_id

    source = _ref_address(target.get("source"))
    destination = _ref_address(target.get("target"))
    if source is None or destination is None:
        return None, flat_id
    source_field = target.get("source_field")
    if isinstance(source_field, str):
        source += f".{source_field}"
    source_path = target.get("source_path")
    if isinstance(source_path, list):
        source += "".join(f".{part}" for part in source_path if isinstance(part, str))
    input_name = target.get("input_name")
    if isinstance(input_name, str):
        destination += f".{input_name}"
    return f"{source} -> {destination}", flat_id


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
            click.echo("  server up, no interactions recorded for this workflow key (is a window open on it?).")
        else:
            click.echo("  server up, no interactions recorded yet.")
        click.echo(f"  workflow key: {payload.get('workflow_key')}")
        return

    for raw_event in event_list:
        if not isinstance(raw_event, dict):
            continue
        timestamp = raw_event.get("ts")
        when = (
            datetime.fromtimestamp(timestamp, tz=UTC).isoformat(timespec="seconds")
            if isinstance(timestamp, (int, float))
            else "timestamp unknown"
        )
        address, flat_id = _target_address(raw_event.get("target"))
        target_text = address or "no target"
        if flat_id:
            target_text += f" [{flat_id}]"
        view = raw_event.get("view_state")
        if isinstance(view, dict):
            state = f"{view.get('density')}/{view.get('direction')} · focus {view.get('focus')}"
        else:
            state = "view state unknown"
        workflow_key = raw_event.get("workflow_key")
        workflow_text = f" · {workflow_key}" if workflow is None else ""
        click.echo(
            f"  {when} ({_format_age(raw_event.get('age_seconds'))}) "
            f"{raw_event.get('type')} · {target_text} · {state}{workflow_text}"
        )
    click.echo(f"  workflow key: {payload.get('workflow_key')}")


@ui_cmd.command(name="user-activity")
@click.argument("workflow", required=False)
@click.option("--json", "output_json", is_flag=True, help="Output the server response as JSON.")
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
