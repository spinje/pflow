"""Server-side Point/Watch hub and endpoint contracts."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from pathlib import Path
from unittest.mock import AsyncMock, patch
from urllib.parse import urlencode

from starlette.requests import Request
from starlette.testclient import TestClient

from pflow.core.workflow.manager import WorkflowManager
from pflow.ui.server import _ACTIVITY_MAX, _Hub, _workflow_key, create_app, events
from tests.shared.markdown_utils import write_workflow_file

_VALID_IR = {
    "nodes": [
        {"id": "greet", "type": "shell", "params": {"command": "echo hello"}},
        {"id": "done", "type": "shell", "params": {"command": "echo ${greet.stdout}"}},
    ],
    "edges": [{"from": "greet", "to": "done"}],
}


def _workflow(tmp_path: Path) -> Path:
    path = tmp_path / "interaction.pflow.md"
    write_workflow_file(_VALID_IR, path)
    return path


def test_workflow_key_groups_saved_name_and_resolved_path() -> None:
    manager = WorkflowManager()
    workflow_dir = manager.workflows_dir / "interaction"
    workflow_dir.mkdir(parents=True)
    path = workflow_dir / "interaction.pflow.md"
    write_workflow_file(_VALID_IR, path)

    assert _workflow_key("interaction") == _workflow_key(str(path)) == str(path.resolve())


def test_workflow_key_returns_none_for_a_nonexistent_pflow_md_path() -> None:
    # A ".pflow.md" path that does not exist is "not found", not a phantom key:
    # the suffix is not a special case (Path.suffix is only ".md"), so identity
    # rests entirely on exists() — you cannot Point at a graph that cannot be built.
    assert _workflow_key("/no/such/workflow.pflow.md") is None


class TestHub:
    def test_register_broadcast_visibility_and_unregister(self) -> None:
        hub = _Hub()
        first = hub.register("/a.pflow.md", "visible")
        second = hub.register("/a.pflow.md", "hidden")
        hub.register("/other.pflow.md", "visible")

        sent = hub.broadcast("/a.pflow.md", {"type": "clear"})

        assert [conn.conn_id for conn in sent] == [first.conn_id, second.conn_id]
        assert first.queue.get_nowait() == {"type": "clear"}
        assert second.queue.get_nowait() == {"type": "clear"}
        hub.set_visibility(second.conn_id, "visible")
        assert [conn.visibility for conn in hub.windows_for("/a.pflow.md")] == ["visible", "visible"]

        hub.unregister(first.conn_id)
        assert [conn.conn_id for conn in hub.windows_for("/a.pflow.md")] == [second.conn_id]

    def test_slow_connection_is_evicted_instead_of_growing_without_bound(self) -> None:
        hub = _Hub()
        conn = hub.register("/wf.pflow.md", "visible")
        for sequence in range(conn.queue.maxsize):
            conn.queue.put_nowait({"sequence": sequence})

        sent = hub.broadcast("/wf.pflow.md", {"type": "focus"})

        assert sent == []
        assert conn.active is False
        assert hub.windows_for("/wf.pflow.md") == []

    def test_activity_ring_is_bounded_filtered_and_newest_first(self) -> None:
        hub = _Hub()
        for index in range(_ACTIVITY_MAX + 5):
            hub.record({"workflow_key": "/a.pflow.md", "sequence": index})
        hub.record({"workflow_key": "/b.pflow.md", "sequence": 999})

        all_events = hub.activity()
        filtered = hub.activity("/a.pflow.md")

        assert len(all_events) == _ACTIVITY_MAX
        assert all_events[0]["sequence"] == 999
        assert filtered[0]["sequence"] == _ACTIVITY_MAX + 4
        assert filtered[-1]["sequence"] == 6


class TestHealthEndpoint:
    """``/api/health`` — the discovery/reuse probe. It TOUCHES THE HUB, so the
    load-bearing invariant is that it counts live connections under the SAME
    ``_workflow_key`` a Viewer registers under. If health derived a different key
    than ``events()``, a connected Viewer would read as ``windows: 0`` forever —
    discovery would re-spawn duplicates and ``focus --open`` would silently time
    out instead of sending. This is the same register-then-assert-count pattern as
    ``test_focus_resolves_and_broadcasts_to_matching_windows``."""

    def test_counts_live_windows_under_the_resolved_key_for_a_saved_name(self) -> None:
        # The realistic case: `pflow ui <name>` opens the Viewer (registers under the
        # resolved PATH); `pflow ui focus <name> --open` polls health by NAME. Health
        # must resolve name→path to see the connection — a raw-string lookup would read
        # 0 (name != path) on EVERY platform, so this pins the resolution unambiguously.
        manager = WorkflowManager()
        wf_dir = manager.workflows_dir / "discoverable"
        wf_dir.mkdir(parents=True)
        path = wf_dir / "discoverable.pflow.md"
        write_workflow_file(_VALID_IR, path)
        key = str(path.resolve())

        app = create_app()
        app.state.hub.register(key, "visible")
        app.state.hub.register(key, "hidden")
        app.state.hub.register("/different.pflow.md", "visible")  # other workflow — must NOT count

        body = TestClient(app).get("/api/health", params={"workflow": "discoverable"}).json()

        assert body == {"service": "pflow-ui", "workflow_key": key, "windows": 2}

    def test_identity_only_without_a_workflow(self) -> None:
        assert TestClient(create_app()).get("/api/health").json() == {"service": "pflow-ui"}

    def test_unknown_workflow_is_identity_only_not_404(self) -> None:
        # A liveness probe must answer regardless — unlike command()/activity(), which 404.
        response = TestClient(create_app()).get("/api/health", params={"workflow": "no-such-workflow-xyz"})
        assert response.status_code == 200
        assert response.json() == {"service": "pflow-ui"}


class TestInteractionEndpoints:
    def test_focus_resolves_and_broadcasts_to_matching_windows(self, tmp_path: Path) -> None:
        workflow = _workflow(tmp_path)
        app = create_app()
        key = str(workflow.resolve())
        visible = app.state.hub.register(key, "visible")
        app.state.hub.register(key, "hidden")
        app.state.hub.register("/different.pflow.md", "visible")

        response = TestClient(app).post(
            "/api/command",
            json={"workflow": str(workflow), "type": "focus", "target": "greet"},
        )

        assert response.status_code == 200
        assert response.json() == {
            "resolved": {"matched": 1, "address": "greet"},
            "sent_to": 2,
            "windows": [{"visibility": "visible"}, {"visibility": "hidden"}],
            "workflow_key": key,
        }
        assert visible.queue.get_nowait() == {
            "type": "focus",
            "target": {
                "kind": "node",
                "ref": {"node_id": "greet", "ancestor_path": [], "port": None},
            },
        }

    def test_clear_does_not_require_a_target(self, tmp_path: Path) -> None:
        workflow = _workflow(tmp_path)
        app = create_app()
        conn = app.state.hub.register(str(workflow.resolve()), "visible")

        response = TestClient(app).post(
            "/api/command",
            json={"workflow": str(workflow), "type": "clear"},
        )

        assert response.status_code == 200
        assert response.json()["sent_to"] == 1
        assert conn.queue.get_nowait() == {"type": "clear"}

    def test_point_build_runs_off_the_hub_event_loop(self, tmp_path: Path) -> None:
        workflow = _workflow(tmp_path)

        async def run_in_thread(function: Callable[..., object], *args: object, **kwargs: object) -> object:
            return function(*args, **kwargs)

        to_thread = AsyncMock(side_effect=run_in_thread)
        with patch("pflow.ui.server.asyncio.to_thread", to_thread):
            response = TestClient(create_app()).post(
                "/api/command",
                json={"workflow": str(workflow), "type": "focus", "target": "greet"},
            )

        assert response.status_code == 200
        to_thread.assert_awaited_once()

    def test_not_found_and_ambiguous_targets_are_not_broadcast(self, tmp_path: Path) -> None:
        workflow = _workflow(tmp_path)
        app = create_app()
        conn = app.state.hub.register(str(workflow.resolve()), "visible")
        client = TestClient(app)

        response = client.post(
            "/api/command",
            json={"workflow": str(workflow), "type": "focus", "target": "grete"},
        )

        assert response.status_code == 200
        assert response.json()["resolved"] == {"matched": 0, "suggestions": ["greet"]}
        assert response.json()["sent_to"] == 0
        assert conn.queue.empty()

    def test_unknown_workflow_name_is_actionable_404(self) -> None:
        response = TestClient(create_app()).post(
            "/api/command",
            json={"workflow": "does-not-exist", "type": "focus", "target": "greet"},
        )

        assert response.status_code == 404
        assert "does-not-exist" in response.json()["error"]
        assert response.json()["suggestions"] == []

    def test_mutating_endpoints_require_json_content_type(self, tmp_path: Path) -> None:
        workflow = _workflow(tmp_path)
        client = TestClient(create_app())

        for path in ("/api/command", "/api/interaction", "/api/visibility"):
            response = client.post(path, content=json.dumps({"workflow": str(workflow)}))
            assert response.status_code == 415
            assert "application/json" in response.json()["error"]

    def test_invalid_workflow_source_is_422(self, tmp_path: Path) -> None:
        workflow = tmp_path / "invalid.pflow.md"
        write_workflow_file(
            {"nodes": [{"id": "bad", "type": "nonexistent_type_xyz", "params": {}}]},
            workflow,
        )

        response = TestClient(create_app()).post(
            "/api/command",
            json={"workflow": str(workflow), "type": "focus", "target": "bad"},
        )

        assert response.status_code == 422
        assert response.json()["errors"]

    def test_interactions_are_recorded_and_read_as_an_aged_snapshot(self, tmp_path: Path) -> None:
        workflow = _workflow(tmp_path)
        client = TestClient(create_app())
        event = {
            "workflow": str(workflow),
            "type": "node_click",
            "target": {
                "kind": "node",
                "flat_id": "n0",
                "ref": {"node_id": "greet", "ancestor_path": [], "port": None},
            },
            "view_state": {"density": "beautiful", "direction": "LR", "focus": "greet"},
        }

        posted = client.post("/api/interaction", json=event)
        response = client.get("/api/activity", params={"workflow": str(workflow)})

        assert posted.status_code == 204
        assert response.status_code == 200
        payload = response.json()
        assert payload["workflow_key"] == str(workflow.resolve())
        assert len(payload["events"]) == 1
        assert payload["events"][0]["type"] == "node_click"
        assert payload["events"][0]["target"]["flat_id"] == "n0"
        assert payload["events"][0]["age_seconds"] >= 0

    def test_interaction_records_only_whitelisted_fields(self, tmp_path: Path) -> None:
        # Arbitrary client-supplied keys must not leak into the Watch snapshot, so
        # the agent reading /api/activity sees a predictable event shape.
        workflow = _workflow(tmp_path)
        client = TestClient(create_app())
        event = {
            "workflow": str(workflow),
            "type": "node_click",
            "view_state": {"density": "beautiful", "direction": "LR", "focus": None},
            "injected": "should-not-be-recorded",
        }

        assert client.post("/api/interaction", json=event).status_code == 204
        recorded = client.get("/api/activity", params={"workflow": str(workflow)}).json()["events"]
        assert len(recorded) == 1
        assert "injected" not in recorded[0]
        assert recorded[0]["type"] == "node_click"

    def test_unknown_workflow_activity_is_actionable_404(self) -> None:
        response = TestClient(create_app()).get(
            "/api/activity",
            params={"workflow": "does-not-exist"},
        )

        assert response.status_code == 404
        assert "does-not-exist" in response.json()["error"]

    def test_visibility_updates_only_the_named_connection(self, tmp_path: Path) -> None:
        workflow = _workflow(tmp_path)
        app = create_app()
        conn = app.state.hub.register(str(workflow.resolve()), "visible")

        response = TestClient(app).post(
            "/api/visibility",
            json={"conn_id": conn.conn_id, "visibility": "hidden"},
        )

        assert response.status_code == 204
        assert conn.visibility == "hidden"


def test_sse_disconnect_unregisters_connection_via_raw_asgi(tmp_path: Path) -> None:
    """Exercise real ``http.disconnect`` delivery; TestClient cannot do this."""
    workflow = _workflow(tmp_path)
    app = create_app()
    command_sent = asyncio.Event()
    request_sent = False
    response_frames: list[dict[str, object]] = []

    async def receive() -> dict[str, object]:
        nonlocal request_sent
        if not request_sent:
            request_sent = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await command_sent.wait()
        return {"type": "http.disconnect"}

    async def send(message: dict[str, object]) -> None:
        response_frames.append(message)
        body = message.get("body")
        if isinstance(body, bytes) and b'"type": "connected"' in body:
            app.state.hub.broadcast(str(workflow.resolve()), {"type": "clear"})
        if isinstance(body, bytes) and b'"type": "clear"' in body:
            command_sent.set()

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/api/events",
        "raw_path": b"/api/events",
        "query_string": urlencode({"workflow": str(workflow), "visibility": "visible"}).encode(),
        "headers": [],
        "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 8765),
        "root_path": "",
    }

    asyncio.run(app(scope, receive, send))

    assert command_sent.is_set()
    assert app.state.hub.windows_for(str(workflow.resolve())) == []
    assert response_frames[0]["type"] == "http.response.start"
    assert any(b'"type": "clear"' in frame.get("body", b"") for frame in response_frames)


def test_idle_connection_emits_keepalive_frames(tmp_path: Path) -> None:
    """An idle SSE connection emits a `:` keepalive comment frame, then cleans up.

    The keepalive is load-bearing: on ASGI spec >=2.4 ``StreamingResponse`` has no
    disconnect listener, so a silently-dropped socket only surfaces when the next
    ``send`` fails — and the keepalive is the only ``send`` an idle stream makes.

    Two robustness fixes here, both learned from this one test roughly tripling
    ``make test`` wall time:

    1. Drive the response body generator directly, not the whole ASGI app. Driving
       the app made teardown hinge on Starlette's disconnect listener winning a
       scheduler race against the keepalive loop — not the behavior under test.
    2. Patch ``_KEEPALIVE_S`` on ``events.__globals__`` (the dict the running
       generator actually reads), NOT by the dotted path ``"pflow.ui.server"``. In
       the full suite that module is sometimes a *different* object than the one
       this file imported ``events`` from — a duplicated/reloaded module (see
       tests/CLAUDE.md pitfall #2). A dotted-path patch then lands on the wrong
       object, the generator keeps the real 15s interval, and the test passes but
       sleeps 15s. Patching the closure's own globals is immune to that skew.

    The 2s ``wait_for`` caps turn any future interval-patch regression into a fast
    failure instead of a 15s hang."""
    workflow = _workflow(tmp_path)
    app = create_app()
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/events",
        "query_string": urlencode({"workflow": str(workflow), "visibility": "visible"}).encode(),
        "headers": [],
        "app": app,
    }

    async def _drive() -> tuple[str, str]:
        response = await events(Request(scope))
        body = response.body_iterator
        # Each pull resumes stream() to its next yield: the first returns the
        # connected handshake, the second blocks on the keepalive timeout (0.01s)
        # and returns the comment frame. aclose() then raises GeneratorExit at the
        # yield, so stream()'s finally unregisters the connection.
        connected = await asyncio.wait_for(body.__anext__(), timeout=2.0)
        keepalive = await asyncio.wait_for(body.__anext__(), timeout=2.0)
        await body.aclose()
        return connected, keepalive

    with patch.dict(events.__globals__, {"_KEEPALIVE_S": 0.01}):
        connected, keepalive = asyncio.run(_drive())

    assert '"type": "connected"' in connected
    assert keepalive.strip().startswith(":")  # the idle keepalive comment frame
    assert app.state.hub.windows_for(str(workflow.resolve())) == []
