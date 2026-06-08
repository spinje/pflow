"""``pflow ui`` — serve the interactive workflow visualization web UI.

The web stack (Starlette + uvicorn + the built frontend bundle) ships behind the
``pflow[ui]`` extra. This command imports it **lazily** inside the body so a base
install without the extra still loads the CLI; a missing import prints the
install hint instead of crashing. Keep the module top free of starlette/uvicorn/
server imports (it is imported eagerly at ``main.py`` load).
"""

from __future__ import annotations

import socket

import click


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
    """Open the browser once the server is actually accepting connections.

    ``uvicorn.run()`` blocks, so the browser must be opened from a side thread —
    but rather than guess a fixed delay (which races a cold-registry startup and
    can pop a "connection refused" page), poll the port until it accepts a
    connection. uvicorn binds the listening socket only AFTER lifespan startup
    (the registry warm) completes, so a successful connect means the server is
    fully ready to serve. Falls back to opening after ``timeout`` so a stuck
    probe never silently skips the browser.
    """
    import time
    import webbrowser

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.25)
            if probe.connect_ex((host, port)) == 0:
                break
        time.sleep(0.1)
    webbrowser.open(url)


@click.command(name="ui")
@click.argument("workflow", required=False)
@click.option("--port", default=8765, type=int, help="Port to serve on (default: 8765).")
@click.option("--no-open", is_flag=True, default=False, help="Do not open a browser window.")
@click.pass_context
def ui_cmd(ctx: click.Context, workflow: str | None, port: int, no_open: bool) -> None:
    """Serve a browser UI for seeing and understanding a workflow's structure.

    With WORKFLOW (a saved name or a .pflow.md path), opens straight to it.
    Without it, opens the catalog of saved workflows.

    Examples:

        pflow ui workflow.pflow.md

        pflow ui my-saved-workflow --port 9000

        pflow ui --no-open
    """
    # Only the extra's OWN packages go under the install-hint guard. Importing
    # the server module separately means a genuine ImportError inside it (a real
    # bug — a bad import in graph_service, a renderer typo, a circular import)
    # surfaces as a loud traceback, not a misleading "install [ui]" hint.
    try:
        import starlette  # noqa: F401
        import uvicorn
    except ImportError:
        click.echo(
            "The 'pflow ui' web interface needs extra dependencies.\n→ pip install pflow[ui]",
            err=True,
        )
        ctx.exit(1)
        return

    from pflow.ui.server import create_app

    host = "127.0.0.1"

    # Pre-flight the bind so the error is ours. uvicorn catches a bind failure
    # internally and sys.exit(1)s with only its own log line — an `except
    # OSError` around uvicorn.run() never fires, so the actionable hint would be
    # lost and "Serving …" would print before a doomed bind. (Tiny TOCTOU window
    # between probe and uvicorn's bind — acceptable for a local single-user
    # server; uvicorn still errors loudly if it loses the race.)
    if not _port_available(host, port):
        click.echo(
            f"Port {port} is already in use.\n→ try a different --port (e.g. --port {port + 1})",
            err=True,
        )
        ctx.exit(1)
        return

    app = create_app()
    url = f"http://{host}:{port}/"
    if workflow:
        from urllib.parse import urlencode

        url += f"?{urlencode({'workflow': workflow})}"

    if not no_open:
        import threading

        # uvicorn.run() blocks, so open the browser from a side thread that waits
        # until the server is actually listening — not after a guessed delay.
        threading.Thread(
            target=_open_browser_when_ready,
            args=(host, port, url),
            daemon=True,
        ).start()

    click.echo(f"Serving pflow UI at {url} (Ctrl+C to stop)", err=True)
    uvicorn.run(app, host=host, port=port, log_level="warning")


__all__ = ["ui_cmd"]
