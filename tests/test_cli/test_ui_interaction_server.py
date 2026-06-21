"""Server-side Point/Watch hub and endpoint contracts."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from pathlib import Path
from unittest.mock import AsyncMock, patch
from urllib.parse import urlencode

from starlette.testclient import TestClient

from pflow.core.workflow.manager import WorkflowManager
from pflow.ui.server import _ACTIVITY_MAX, _Hub, _workflow_key, create_app
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
