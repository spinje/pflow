"""Server-side Point/Watch hub and endpoint contracts."""

from __future__ import annotations

import asyncio
import base64
import json
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from unittest.mock import AsyncMock, patch
from urllib.parse import urlencode

import pytest
from click.testing import CliRunner
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.testclient import TestClient

from pflow.cli.main import cli
from pflow.core.workflow.manager import WorkflowManager
from pflow.ui.server import (
    _ACTIVITY_MAX,
    _AUDIO_STORE_MAX,
    _AudioStore,
    _Hub,
    _workflow_key,
    create_app,
    events,
)
from tests.shared.markdown_utils import write_workflow_file


def _client(app: Starlette | None = None) -> TestClient:
    """A TestClient whose default Host is loopback so requests pass the ``_LoopbackOnly`` guard.

    Starlette's TestClient defaults to ``base_url="http://testserver"`` → ``Host: testserver``, which the
    Task-175 DNS-rebinding guard (the ``_LoopbackOnly`` middleware, on EVERY route — reads and writes)
    refuses with 403. A real browser / CLI talking to the loopback server always sends a loopback Host, so
    this is the faithful default."""
    return TestClient(app if app is not None else create_app(), base_url="http://127.0.0.1")


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

    def test_set_point_latches_the_latest_command_with_a_monotonic_epoch(self) -> None:
        # Issue #539: the hub remembers the agent's current Point per workflow_key, stamped with a
        # strictly-increasing epoch, so events() can replay the LATEST one to a new/reconnecting Viewer.
        hub = _Hub()
        assert hub.point_for("/a.pflow.md") is None
        first = hub.set_point("/a.pflow.md", {"type": "focus", "target": {"kind": "node"}})
        second = hub.set_point("/a.pflow.md", {"type": "clear"})
        assert first["epoch"] == 1 and second["epoch"] == 2  # broadcast order → monotonic epoch
        assert hub.point_for("/a.pflow.md") == {"type": "clear", "epoch": 2}  # latch holds the latest
        assert hub.point_for("/other.pflow.md") is None  # scoped per workflow_key

    def test_set_run_latches_on_a_separate_store_sharing_the_epoch(self) -> None:
        # Issue #539: the run selection latches independently of the Point latch (orthogonal state, both
        # replayed on subscribe), but on ONE monotonic epoch sequence so they stay comparably ordered.
        hub = _Hub()
        assert hub.run_for("/a.pflow.md") is None
        point = hub.set_point("/a.pflow.md", {"type": "focus"})
        run = hub.set_run("/a.pflow.md", {"type": "select-run", "run": "r1"})
        assert point["epoch"] == 1 and run["epoch"] == 2  # one shared monotonic sequence
        assert hub.run_for("/a.pflow.md") == {"type": "select-run", "run": "r1", "epoch": 2}
        assert hub.point_for("/a.pflow.md") == {"type": "focus", "epoch": 1}  # separate stores, both kept

    def test_boot_id_is_a_stable_per_process_nonce(self) -> None:
        # The restart-fence the client resets its epoch baseline against: stable within a process,
        # distinct across _Hub instances (a server restart mints a fresh one, restarting the counter).
        hub = _Hub()
        assert isinstance(hub.boot_id, str) and hub.boot_id
        assert hub.boot_id == hub.boot_id
        assert hub.boot_id != _Hub().boot_id


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

        body = _client(app).get("/api/health", params={"workflow": "discoverable"}).json()

        # narration_s_remaining / narration_blocked (Task 174 follow-up) ride every health body.
        assert body == {
            "service": "pflow-ui",
            "narration_s_remaining": 0.0,
            "narration_blocked": False,
            "workflow_key": key,
            "windows": 2,
        }

    def test_identity_only_without_a_workflow(self) -> None:
        assert _client().get("/api/health").json() == {
            "service": "pflow-ui",
            "narration_s_remaining": 0.0,
            "narration_blocked": False,
        }

    def test_unknown_workflow_is_identity_only_not_404(self) -> None:
        # A liveness probe must answer regardless — unlike command()/activity(), which 404.
        response = _client().get("/api/health", params={"workflow": "no-such-workflow-xyz"})
        assert response.status_code == 200
        assert response.json() == {
            "service": "pflow-ui",
            "narration_s_remaining": 0.0,
            "narration_blocked": False,
        }


class TestInteractionEndpoints:
    def test_focus_resolves_and_broadcasts_to_matching_windows(self, tmp_path: Path) -> None:
        workflow = _workflow(tmp_path)
        app = create_app()
        key = str(workflow.resolve())
        visible = app.state.hub.register(key, "visible")
        app.state.hub.register(key, "hidden")
        app.state.hub.register("/different.pflow.md", "visible")

        response = _client(app).post(
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
            "epoch": 1,  # Issue #539: focus/frame/clear carry a monotonic epoch for latch dedup
        }

    def test_clear_does_not_require_a_target(self, tmp_path: Path) -> None:
        workflow = _workflow(tmp_path)
        app = create_app()
        conn = app.state.hub.register(str(workflow.resolve()), "visible")

        response = _client(app).post(
            "/api/command",
            json={"workflow": str(workflow), "type": "clear"},
        )

        assert response.status_code == 200
        assert response.json()["sent_to"] == 1
        assert conn.queue.get_nowait() == {"type": "clear", "epoch": 1}  # Issue #539: epoch stamp

    def test_select_run_broadcasts_the_run_id_as_pass_through(self, tmp_path: Path) -> None:
        # Task 175: select-run carries a RUN id in `target` and is PASS-THROUGH — broadcast as
        # {type:"select-run", run:<id>} with NO resolve_target (a run isn't a graph node/edge).
        workflow = _workflow(tmp_path)
        app = create_app()
        conn = app.state.hub.register(str(workflow.resolve()), "visible")

        response = _client(app).post(
            "/api/command",
            json={"workflow": str(workflow), "type": "select-run", "target": "run-abc"},
        )

        assert response.status_code == 200
        assert response.json()["sent_to"] == 1
        # Issue #539: select-run now carries a monotonic `epoch` (it's latched for steering, like Point).
        assert conn.queue.get_nowait() == {"type": "select-run", "run": "run-abc", "epoch": 1}

    def test_select_run_requires_a_target(self, tmp_path: Path) -> None:
        workflow = _workflow(tmp_path)
        response = _client().post("/api/command", json={"workflow": str(workflow), "type": "select-run"})
        assert response.status_code == 400

    def test_focus_latches_the_point_even_with_no_live_windows(self, tmp_path: Path) -> None:
        # Issue #539: the latch exists precisely to reach a tab that was NOT connected when the command
        # fired, so storing it must not depend on there being live windows.
        workflow = _workflow(tmp_path)
        app = create_app()
        key = str(workflow.resolve())

        response = _client(app).post(
            "/api/command", json={"workflow": str(workflow), "type": "focus", "target": "greet"}
        )

        assert response.json()["sent_to"] == 0  # nobody connected
        assert app.state.hub.point_for(key) == {
            "type": "focus",
            "target": {"kind": "node", "ref": {"node_id": "greet", "ancestor_path": [], "port": None}},
            "epoch": 1,
        }

    def test_clear_replaces_the_latched_focus_with_a_higher_epoch(self, tmp_path: Path) -> None:
        workflow = _workflow(tmp_path)
        app = create_app()
        key = str(workflow.resolve())
        client = _client(app)

        client.post("/api/command", json={"workflow": str(workflow), "type": "focus", "target": "greet"})
        client.post("/api/command", json={"workflow": str(workflow), "type": "clear"})

        # The latch holds the LATEST command (the clear), so a reopening tab catches up to the clear rather
        # than re-applying a stale highlight; its epoch is higher than the focus it superseded.
        assert app.state.hub.point_for(key) == {"type": "clear", "epoch": 2}

    def test_select_run_latches_the_run_selection(self, tmp_path: Path) -> None:
        # Issue #539: select-run is latched (on its OWN store) so the agent can steer a backgrounded/returning
        # window to a run. It does NOT touch the Point latch — focus and run selection are orthogonal state.
        workflow = _workflow(tmp_path)
        app = create_app()
        key = str(workflow.resolve())

        _client(app).post("/api/command", json={"workflow": str(workflow), "type": "select-run", "target": "run-abc"})

        assert app.state.hub.run_for(key) == {"type": "select-run", "run": "run-abc", "epoch": 1}
        assert app.state.hub.point_for(key) is None  # the focus latch is untouched

    def test_unknown_command_verb_is_rejected(self, tmp_path: Path) -> None:
        # The verb whitelist still rejects anything outside {focus, frame, clear, select-run}.
        workflow = _workflow(tmp_path)
        response = _client().post("/api/command", json={"workflow": str(workflow), "type": "teleport", "target": "x"})
        assert response.status_code == 400

    def test_point_build_runs_off_the_hub_event_loop(self, tmp_path: Path) -> None:
        workflow = _workflow(tmp_path)

        async def run_in_thread(function: Callable[..., object], *args: object, **kwargs: object) -> object:
            return function(*args, **kwargs)

        to_thread = AsyncMock(side_effect=run_in_thread)
        with patch("pflow.ui.server.asyncio.to_thread", to_thread):
            response = _client().post(
                "/api/command",
                json={"workflow": str(workflow), "type": "focus", "target": "greet"},
            )

        assert response.status_code == 200
        to_thread.assert_awaited_once()

    def test_not_found_and_ambiguous_targets_are_not_broadcast(self, tmp_path: Path) -> None:
        workflow = _workflow(tmp_path)
        app = create_app()
        conn = app.state.hub.register(str(workflow.resolve()), "visible")
        client = _client(app)

        response = client.post(
            "/api/command",
            json={"workflow": str(workflow), "type": "focus", "target": "grete"},
        )

        assert response.status_code == 200
        assert response.json()["resolved"] == {"matched": 0, "suggestions": ["greet"]}
        assert response.json()["sent_to"] == 0
        assert conn.queue.empty()
        # A zero/ambiguous match neither broadcasts NOR latches — no epoch is minted (Issue #539).
        assert app.state.hub.point_for(str(workflow.resolve())) is None

    def test_unknown_workflow_name_is_actionable_404(self) -> None:
        response = _client().post(
            "/api/command",
            json={"workflow": "does-not-exist", "type": "focus", "target": "greet"},
        )

        assert response.status_code == 404
        assert "does-not-exist" in response.json()["error"]
        assert response.json()["suggestions"] == []

    def test_mutating_endpoints_require_json_content_type(self, tmp_path: Path) -> None:
        workflow = _workflow(tmp_path)
        client = _client()

        for path in ("/api/command", "/api/say", "/api/narration", "/api/interaction", "/api/visibility"):
            response = client.post(path, content=json.dumps({"workflow": str(workflow)}))
            assert response.status_code == 415
            assert "application/json" in response.json()["error"]

    def test_invalid_workflow_source_is_422(self, tmp_path: Path) -> None:
        workflow = tmp_path / "invalid.pflow.md"
        write_workflow_file(
            {"nodes": [{"id": "bad", "type": "nonexistent_type_xyz", "params": {}}]},
            workflow,
        )

        response = _client().post(
            "/api/command",
            json={"workflow": str(workflow), "type": "focus", "target": "bad"},
        )

        assert response.status_code == 422
        assert response.json()["errors"]

    def test_interactions_are_recorded_and_read_as_an_aged_snapshot(self, tmp_path: Path) -> None:
        workflow = _workflow(tmp_path)
        client = _client()
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
        client = _client()
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
        response = _client().get(
            "/api/activity",
            params={"workflow": "does-not-exist"},
        )

        assert response.status_code == 404
        assert "does-not-exist" in response.json()["error"]

    def test_visibility_updates_only_the_named_connection(self, tmp_path: Path) -> None:
        workflow = _workflow(tmp_path)
        app = create_app()
        conn = app.state.hub.register(str(workflow.resolve()), "visible")

        response = _client(app).post(
            "/api/visibility",
            json={"conn_id": conn.conn_id, "visibility": "hidden"},
        )

        assert response.status_code == 204
        assert conn.visibility == "hidden"


def _workflow_with_input(tmp_path: Path, *, required: bool) -> Path:
    """A workflow with one declared string input ``text``, REFERENCED in a node (an unused declared
    input is a parse error). ``required=True`` omits the default so a blank submit fails the pre-flight."""
    default_line = "" if required else "- default: hi\n"
    path = tmp_path / "withinput.pflow.md"
    path.write_text(
        "# WithInput\n\nEchoes an input.\n\n## Inputs\n\n"
        "### text\n\nText to echo.\n\n- type: string\n" + default_line + "\n"
        '## Steps\n\n### echo\n\nEchoes the text.\n\n- type: shell\n- command: echo "${text}"\n',
        encoding="utf-8",
    )
    return path


_GREET_DESCRIPTOR = {"kind": "node", "ref": {"node_id": "greet", "ancestor_path": [], "port": None}}


class TestSayEndpoint:
    """``POST /api/say`` (Task 174) — store audio + broadcast the point then the caption; ``GET
    /api/audio/<id>`` serves stored clips."""

    def test_say_broadcasts_point_then_caption_with_audio(self, tmp_path: Path) -> None:
        workflow = _workflow(tmp_path)
        app = create_app()
        key = str(workflow.resolve())
        conn = app.state.hub.register(key, "visible")
        clip = b"\x00\x01\x02\x03fake-wav-bytes"

        response = _client(app).post(
            "/api/say",
            json={
                "workflow": str(workflow),
                "type": "focus",
                "target": "greet",
                "caption": "this is the LLM call",
                "audio_b64": base64.b64encode(clip).decode(),
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["resolved"] == {"matched": 1, "address": "greet"}
        assert body["sent_to"] == 1

        # Order is load-bearing: the ordinary stamped point arrives BEFORE the transient caption.
        point = conn.queue.get_nowait()
        assert point == {"type": "focus", "target": _GREET_DESCRIPTOR, "epoch": 1}
        say_msg = conn.queue.get_nowait()
        assert say_msg["type"] == "say"
        assert say_msg["target"] == _GREET_DESCRIPTOR
        assert say_msg["caption"] == "this is the LLM call"
        assert "epoch" not in say_msg  # transient — never latched/replayed

        audio_url = say_msg["audio_url"]
        assert audio_url.startswith("/api/audio/")
        got = _client(app).get(audio_url)
        assert got.status_code == 200
        assert got.headers["content-type"] == "audio/wav"
        assert got.content == clip

    def test_say_without_audio_omits_audio_url(self, tmp_path: Path) -> None:
        workflow = _workflow(tmp_path)
        app = create_app()
        conn = app.state.hub.register(str(workflow.resolve()), "visible")

        response = _client(app).post(
            "/api/say",
            json={"workflow": str(workflow), "type": "focus", "target": "greet", "caption": "hi"},
        )

        assert response.status_code == 200
        conn.queue.get_nowait()  # the point
        say_msg = conn.queue.get_nowait()
        assert say_msg["type"] == "say"
        assert "audio_url" not in say_msg

    def test_say_point_is_replayed_to_a_reconnecting_window_but_the_caption_is_not(self, tmp_path: Path) -> None:
        """The plan's most-debated deep-review decision, verified through the REAL replay path (not just the
        latch): a window connecting AFTER a say catches up to the POINT (latched like any focus) but is NEVER
        replayed the caption/audio. Reconnecting to stale audio would be worse than silence. This is the
        demo-critical scenario — the presenter's tab was backgrounded during the say and reopens. Drives the
        events() generator directly (same technique as test_events_replays_the_latched_point_to_a_new_connection)."""
        workflow = _workflow(tmp_path)
        app = create_app()
        key = str(workflow.resolve())
        caption = "this is the LLM call"

        # Agent says at a node while NO tab of this workflow is connected.
        _client(app).post(
            "/api/say",
            json={
                "workflow": str(workflow),
                "type": "focus",
                "target": "greet",
                "caption": caption,
                "audio_b64": base64.b64encode(b"clip").decode(),
            },
        )

        # The point is latched (set_point); the say is fire-and-forget (stored in no latch).
        assert app.state.hub.point_for(key) == {"type": "focus", "target": _GREET_DESCRIPTOR, "epoch": 1}

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/events",
            "query_string": urlencode({"workflow": str(workflow), "visibility": "visible"}).encode(),
            "headers": [],
            "app": app,
        }

        async def _drive() -> list[str]:
            response = await events(Request(scope))
            body = response.body_iterator
            # Replay is exactly: connected -> run-snapshot -> latched point (run_for is None, so no 4th
            # replay frame; a 4th __anext__ would block until keepalive). The say is NOT in this sequence.
            frames = [await asyncio.wait_for(body.__anext__(), timeout=2.0) for _ in range(3)]
            await body.aclose()
            return frames

        connected, snapshot, latched = asyncio.run(_drive())

        assert '"type": "connected"' in connected
        assert '"type": "run-snapshot"' in snapshot
        payload = json.loads(latched.removeprefix("data: ").strip())
        assert payload == {"type": "focus", "target": _GREET_DESCRIPTOR, "epoch": 1}  # the point, no caption
        # The caption text and the say envelope never enter the replay — a reconnecting window can't
        # receive stale audio because there is no latch to replay it from.
        assert all(caption not in frame and '"type": "say"' not in frame for frame in (connected, snapshot, latched))

    def test_say_frame_uses_frame_verb(self, tmp_path: Path) -> None:
        workflow = _workflow(tmp_path)
        app = create_app()
        conn = app.state.hub.register(str(workflow.resolve()), "visible")

        _client(app).post(
            "/api/say",
            json={"workflow": str(workflow), "type": "frame", "target": "greet", "caption": "hi"},
        )

        assert conn.queue.get_nowait()["type"] == "frame"

    def test_say_missing_caption_is_400(self, tmp_path: Path) -> None:
        workflow = _workflow(tmp_path)
        response = _client().post("/api/say", json={"workflow": str(workflow), "type": "focus", "target": "greet"})
        assert response.status_code == 400

    def test_say_bad_base64_is_400(self, tmp_path: Path) -> None:
        workflow = _workflow(tmp_path)
        response = _client().post(
            "/api/say",
            json={
                "workflow": str(workflow),
                "type": "focus",
                "target": "greet",
                "caption": "hi",
                "audio_b64": "!!!not-base64!!!",
            },
        )
        assert response.status_code == 400

    def test_say_rejects_non_point_verb(self, tmp_path: Path) -> None:
        # Only focus/frame carry a caption; clear/select-run are not say verbs.
        workflow = _workflow(tmp_path)
        response = _client().post(
            "/api/say",
            json={"workflow": str(workflow), "type": "clear", "target": "greet", "caption": "hi"},
        )
        assert response.status_code == 400

    def test_say_unknown_workflow_is_404(self) -> None:
        response = _client().post(
            "/api/say",
            json={"workflow": "does-not-exist", "type": "focus", "target": "greet", "caption": "hi"},
        )
        assert response.status_code == 404

    def test_say_oversize_audio_is_400_stating_the_limit(self, tmp_path: Path) -> None:
        workflow = _workflow(tmp_path)
        # Patch the constant in the namespace the RUNNING handler reads (`create_app.__globals__`), not
        # via a `"pflow.ui.server._AUDIO_MAX_BYTES"` string — a sibling test reloads that module
        # (test_ui.py pops it from sys.modules), so the string form would target a fresh module object
        # while `create_app` (imported at file top) still runs the original one (tests/CLAUDE.md #21).
        with patch.dict(create_app.__globals__, {"_AUDIO_MAX_BYTES": 4}):
            response = _client().post(
                "/api/say",
                json={
                    "workflow": str(workflow),
                    "type": "focus",
                    "target": "greet",
                    "caption": "hi",
                    "audio_b64": base64.b64encode(b"12345").decode(),
                },
            )
        assert response.status_code == 400
        assert "max 4" in response.json()["error"]

    def test_say_failed_resolve_does_not_broadcast_or_store_audio(self, tmp_path: Path) -> None:
        workflow = _workflow(tmp_path)
        app = create_app()
        conn = app.state.hub.register(str(workflow.resolve()), "visible")

        response = _client(app).post(
            "/api/say",
            json={
                "workflow": str(workflow),
                "type": "focus",
                "target": "grete",  # typo → matched 0
                "caption": "hi",
                "audio_b64": base64.b64encode(b"clip").decode(),
            },
        )

        assert response.status_code == 200
        assert response.json()["resolved"]["matched"] == 0
        assert response.json()["sent_to"] == 0
        assert conn.queue.empty()  # neither point nor say broadcast
        assert app.state.audio._clips == {}  # audio is NOT stored on a failed resolve

    def test_audio_unknown_id_is_404(self) -> None:
        response = _client().get("/api/audio/no-such-id")
        assert response.status_code == 404


class TestNarrationPacingRendezvous:
    """``app.state.narration_until`` (Task 174 follow-up v2): a delivered audio ``say`` records when
    its clip stops playing; ``/api/health`` reports the remainder (``narration_s_remaining``) so the
    NEXT ``--say`` can wait its turn BEFORE dispatching; ``clear`` resets it (clear = stop talking)."""

    @staticmethod
    def _wav_b64(seconds: float) -> str:
        import io
        import wave

        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as writer:
            writer.setnchannels(1)
            writer.setsampwidth(2)
            writer.setframerate(24000)
            writer.writeframes(b"\x00\x00" * int(24000 * seconds))
        return base64.b64encode(buffer.getvalue()).decode()

    def _say(self, app: Starlette, workflow: Path, **extra: str) -> None:
        response = _client(app).post(
            "/api/say",
            json={"workflow": str(workflow), "type": "focus", "target": "greet", "caption": "hi", **extra},
        )
        assert response.status_code == 200

    def test_delivered_audio_say_sets_the_remaining_window(self, tmp_path: Path) -> None:
        workflow = _workflow(tmp_path)
        app = create_app()
        app.state.hub.register(str(workflow.resolve()), "visible")

        self._say(app, workflow, audio_b64=self._wav_b64(2.0))

        # clip duration + the start-lag allowance (the browser starts playing AFTER the broadcast;
        # the estimate must err past the true end or the next say clips the last words).
        remaining = _client(app).get("/api/health").json()["narration_s_remaining"]
        assert 2.25 < remaining <= 2.75

    def test_health_reports_zero_when_idle(self) -> None:
        assert _client().get("/api/health").json()["narration_s_remaining"] == 0.0

    def test_caption_only_say_does_not_mark_narration_busy(self, tmp_path: Path) -> None:
        workflow = _workflow(tmp_path)
        app = create_app()
        app.state.hub.register(str(workflow.resolve()), "visible")

        self._say(app, workflow)  # no audio_b64

        assert _client(app).get("/api/health").json()["narration_s_remaining"] == 0.0

    def test_zero_window_say_does_not_mark_narration_busy(self, tmp_path: Path) -> None:
        # Nothing received the clip, so nothing is playing — the next say must not wait for it.
        workflow = _workflow(tmp_path)
        app = create_app()

        self._say(app, workflow, audio_b64=self._wav_b64(2.0))

        assert _client(app).get("/api/health").json()["narration_s_remaining"] == 0.0

    def test_clear_resets_the_rendezvous(self, tmp_path: Path) -> None:
        # clear pauses the clip in the browser — a stale window must not stall the next say.
        workflow = _workflow(tmp_path)
        app = create_app()
        app.state.hub.register(str(workflow.resolve()), "visible")
        self._say(app, workflow, audio_b64=self._wav_b64(5.0))
        assert _client(app).get("/api/health").json()["narration_s_remaining"] > 0

        response = _client(app).post("/api/command", json={"workflow": str(workflow), "type": "clear"})

        assert response.status_code == 200
        assert _client(app).get("/api/health").json()["narration_s_remaining"] == 0.0

    def test_clear_also_resets_a_stuck_blocked_flag(self, tmp_path: Path) -> None:
        # A window autoplay-blocked a clip and the user walked away without clicking ▶. `clear` must
        # release the stuck flag too (window-independent — a frontend `ended` would only fire if a tab
        # were still open), else the next unrelated --say holds for the full blocked-poll cap.
        workflow = _workflow(tmp_path)
        app = create_app()
        app.state.hub.register(str(workflow.resolve()), "visible")
        _client(app).post("/api/narration", json={"audio_id": "x", "event": "blocked"})
        assert _client(app).get("/api/health").json()["narration_blocked"] is True

        _client(app).post("/api/command", json={"workflow": str(workflow), "type": "clear"})

        assert _client(app).get("/api/health").json()["narration_blocked"] is False

    def test_started_beacon_reanchors_to_real_playback(self, tmp_path: Path) -> None:
        # Broadcast-time estimate = duration + the start-lag guess; the Viewer's `started` beacon
        # replaces it with the exact end measured from REAL playback (no lag pad).
        workflow = _workflow(tmp_path)
        app = create_app()
        conn = app.state.hub.register(str(workflow.resolve()), "visible")
        self._say(app, workflow, audio_b64=self._wav_b64(2.0))
        conn.queue.get_nowait()  # the point
        audio_id = conn.queue.get_nowait()["audio_url"].rsplit("/", 1)[1]

        response = _client(app).post("/api/narration", json={"audio_id": audio_id, "event": "started"})

        assert response.status_code == 200
        remaining = _client(app).get("/api/health").json()["narration_s_remaining"]
        assert 1.5 < remaining <= 2.0

    def test_blocked_beacon_flags_health_until_playback_succeeds(self) -> None:
        app = create_app()
        assert _client(app).get("/api/health").json()["narration_blocked"] is False

        _client(app).post("/api/narration", json={"audio_id": "x", "event": "blocked"})
        assert _client(app).get("/api/health").json()["narration_blocked"] is True

        _client(app).post("/api/narration", json={"audio_id": "x", "event": "started"})
        assert _client(app).get("/api/health").json()["narration_blocked"] is False

    def test_ended_beacon_clears_the_window(self, tmp_path: Path) -> None:
        workflow = _workflow(tmp_path)
        app = create_app()
        conn = app.state.hub.register(str(workflow.resolve()), "visible")
        self._say(app, workflow, audio_b64=self._wav_b64(5.0))
        conn.queue.get_nowait()  # the point
        audio_id = conn.queue.get_nowait()["audio_url"].rsplit("/", 1)[1]
        assert _client(app).get("/api/health").json()["narration_s_remaining"] > 0

        _client(app).post("/api/narration", json={"audio_id": audio_id, "event": "ended"})

        assert _client(app).get("/api/health").json()["narration_s_remaining"] == 0.0

    def test_a_stale_ended_beacon_does_not_free_the_current_clip(self, tmp_path: Path) -> None:
        # A late `ended` for a SUPERSEDED clip (a rapid --no-wait interrupt, a multi-window or delayed
        # beacon) must not zero the live clip's window — that would clip the current narration. This is
        # what lets the frontend beacon `ended` from every stop path without racing a newer say.
        workflow = _workflow(tmp_path)
        app = create_app()
        app.state.hub.register(str(workflow.resolve()), "visible")
        self._say(app, workflow, audio_b64=self._wav_b64(5.0))
        assert _client(app).get("/api/health").json()["narration_s_remaining"] > 0

        _client(app).post("/api/narration", json={"audio_id": "not-the-current-clip", "event": "ended"})

        # The window stands — only an `ended` for the CURRENT audio_id frees pacing.
        assert _client(app).get("/api/health").json()["narration_s_remaining"] > 0

    def test_a_stale_started_beacon_does_not_reanchor_pacing(self, tmp_path: Path) -> None:
        # Symmetric to the stale `ended`: a `started` for a superseded clip must not re-arm pacing to a
        # window that is no longer current (it would stretch the wait to the wrong clip's length).
        workflow = _workflow(tmp_path)
        app = create_app()
        conn = app.state.hub.register(str(workflow.resolve()), "visible")
        self._say(app, workflow, audio_b64=self._wav_b64(2.0))
        conn.queue.get_nowait()  # the point
        current_id = conn.queue.get_nowait()["audio_url"].rsplit("/", 1)[1]
        # A different, longer clip that is real in the store but NOT the current say.
        stale_id = app.state.audio.put(base64.b64decode(self._wav_b64(9.0)))
        assert stale_id != current_id

        _client(app).post("/api/narration", json={"audio_id": stale_id, "event": "started"})

        # Ignored: the window stays the ~2s current clip, never stretched to the 9s stale clip.
        assert _client(app).get("/api/health").json()["narration_s_remaining"] < 3.0

    def test_narration_beacon_validates_body(self) -> None:
        assert _client().post("/api/narration", json={"audio_id": "x", "event": "nope"}).status_code == 400
        assert _client().post("/api/narration", json={"event": "started"}).status_code == 400

    def test_started_beacon_for_an_evicted_clip_is_harmless(self) -> None:
        # The clip may already be LRU-evicted when the beacon lands — duration unknown → no window.
        app = create_app()
        response = _client(app).post("/api/narration", json={"audio_id": "gone", "event": "started"})
        assert response.status_code == 200
        assert _client(app).get("/api/health").json()["narration_s_remaining"] == 0.0

    def test_unparseable_audio_bytes_degrade_to_zero_not_a_stall(self, tmp_path: Path) -> None:
        # wav_duration is TOTAL: fake bytes → 0.0 → the rendezvous never blocks on garbage.
        workflow = _workflow(tmp_path)
        app = create_app()
        app.state.hub.register(str(workflow.resolve()), "visible")

        self._say(app, workflow, audio_b64=base64.b64encode(b"not-a-wav").decode())

        assert _client(app).get("/api/health").json()["narration_s_remaining"] == 0.0


class TestAudioStore:
    def test_put_get_round_trip(self) -> None:
        store = _AudioStore()
        audio_id = store.put(b"clip")
        assert store.get(audio_id) == b"clip"

    def test_evicts_oldest_beyond_max(self) -> None:
        store = _AudioStore()
        ids = [store.put(bytes([i % 256])) for i in range(_AUDIO_STORE_MAX + 1)]
        assert store.get(ids[0]) is None  # oldest evicted once over the bound
        assert store.get(ids[1]) is not None
        assert store.get(ids[-1]) is not None


class TestRunEndpoint:
    """``POST /api/run`` — spawns a DETACHED ``pflow run`` (Task 175). ``subprocess.Popen`` is patched in
    every test so no real subprocess is spawned; the off-loop pre-flight (real ``compile_workflow``) runs."""

    def test_spawn_invoked_with_expected_detached_argv(self, tmp_path: Path) -> None:
        workflow = _workflow(tmp_path)  # the no-input _VALID_IR
        key = str(workflow.resolve())
        with patch("pflow.ui.server.subprocess.Popen") as popen:
            response = _client().post("/api/run", json={"workflow": str(workflow), "inputs": {}})

        assert response.status_code == 200
        # The minted run_id is returned (so the browser can PIN the overlay to this exact run) AND forced
        # onto the spawned run via PFLOW_EXECUTION_ID (Task 175).
        body = response.json()
        assert body["status"] == "spawned"
        run_id = body["run_id"]
        assert isinstance(run_id, str) and run_id
        popen.assert_called_once()
        argv = popen.call_args.args[0]
        assert argv == [sys.executable, "-m", "pflow.cli", "run", key, "--output-format", "json"]
        kwargs = popen.call_args.kwargs
        if sys.platform == "win32":
            assert kwargs["creationflags"] == subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
            assert "start_new_session" not in kwargs
        else:
            assert kwargs["start_new_session"] is True
            assert "creationflags" not in kwargs
        assert kwargs["stdin"] == kwargs["stdout"] == kwargs["stderr"] == subprocess.DEVNULL
        assert kwargs["env"]["PFLOW_EXECUTION_ID"] == run_id  # forced onto the child so the pin resolves

    def test_declared_inputs_become_one_argv_token_each_injection_safe(self, tmp_path: Path) -> None:
        # A value with a space and a shell metacharacter must arrive as ONE unparsed argv element.
        workflow = _workflow_with_input(tmp_path, required=False)
        with patch("pflow.ui.server.subprocess.Popen") as popen:
            response = _client().post(
                "/api/run",
                json={"workflow": str(workflow), "inputs": {"text": "a b; rm -rf /"}},
            )

        assert response.status_code == 200
        argv = popen.call_args.args[0]
        assert argv[-1] == "text=a b; rm -rf /"  # single token, never shell-split

    def test_unknown_workflow_is_404_and_does_not_spawn(self) -> None:
        with patch("pflow.ui.server.subprocess.Popen") as popen:
            response = _client().post("/api/run", json={"workflow": "does-not-exist-xyz", "inputs": {}})

        assert response.status_code == 404
        assert "does-not-exist-xyz" in response.json()["error"]
        popen.assert_not_called()

    def test_malformed_body_is_400_and_does_not_spawn(self, tmp_path: Path) -> None:
        workflow = str(_workflow(tmp_path))
        bad_bodies = [
            {"inputs": {}},  # missing 'workflow'
            {"workflow": workflow, "inputs": ["not", "an", "object"]},  # inputs not an object
            {"workflow": workflow, "inputs": {"count": 5}},  # non-string input value
        ]
        with patch("pflow.ui.server.subprocess.Popen") as popen:
            for body in bad_bodies:
                response = _client().post("/api/run", json=body)
                assert response.status_code == 400, body
        popen.assert_not_called()

    def test_missing_required_input_is_400_with_diagnostics_and_does_not_spawn(self, tmp_path: Path) -> None:
        # The pre-flight compile (off-loop) catches the silent pre-trace-failure class as a clean 400.
        workflow = _workflow_with_input(tmp_path, required=True)
        with patch("pflow.ui.server.subprocess.Popen") as popen:
            response = _client().post("/api/run", json={"workflow": str(workflow), "inputs": {}})

        assert response.status_code == 400
        errors = response.json()["errors"]
        assert errors and any("text" in json.dumps(err) for err in errors)
        popen.assert_not_called()


def _write_paused_trace(
    debug: Path,
    name: str,
    wf_path: str,
    *,
    execution_id: str,
    final_status: str = "paused",
    gate_request: dict | None = None,
    paused_node_id: str | None = "deploy",
) -> None:
    """A synthetic trace whose CONSUMED keys mirror the producer (meta ← `_meta_fields`,
    run.complete + flat pause keys ← `finalize`'s paused arm, Task 171). Projection-test-grade
    (mirrors tests/test_cli/test_ui.py `_write_trace`); the P2 answer-FLOW tests use real
    producer traces instead (tests/CLAUDE.md pitfall #19)."""
    meta = {
        "kind": "meta",
        "pflow_trace": "jsonl/1",
        "workflow_path": wf_path,
        "workflow_name": "WF",
        "execution_id": execution_id,
    }
    trailer: dict = {"kind": "run.complete", "final_status": final_status, "nodes_executed": 1}
    if final_status == "paused":
        if paused_node_id is not None:
            trailer["paused_node_id"] = paused_node_id
        if gate_request is not None:
            trailer["gate_request"] = gate_request
    lines = [meta, trailer]
    (debug / name).write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")


class TestGateEndpoint:
    """``GET /api/gate`` — the on-demand gate payload read (Task 176). Read-only; the bulky
    ``gate_request`` is served here precisely so it never rides the SSE wire or ``/api/runs``."""

    @staticmethod
    def _debug_dir(tmp_path: Path, monkeypatch) -> Path:
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        debug = tmp_path / ".pflow" / "debug"
        debug.mkdir(parents=True)
        return debug

    @pytest.mark.trace_files
    def test_real_paused_run_serves_the_masked_payload_and_rides_the_runs_listing(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """★ The 200 arm against the REAL producer (pitfall #19 — a synthetic trailer here would
        stay green if the producer's pause-record shape ever drifted): pause an actual gated run
        through the CLI, then read the WHOLE server read path off its trace. Pins three seams at
        once: (1) `paused_node_id`/`gate_request` really are flat trailer keys the reader finds;
        (2) `/api/runs` carries `paused_node_id` (the light wire) but never `gate_request`;
        (3) `/api/gate` serves the payload MASKED — the on-disk trailer is unmasked, so a skipped
        `masked_gate_dict` leaks the real secret and fails the absent-from-body assertion."""
        self._debug_dir(tmp_path, monkeypatch)
        wf = tmp_path / "paused_demo.pflow.md"
        wf.write_text(_PAUSED_GATE_WF, encoding="utf-8")
        run = CliRunner(mix_stderr=False).invoke(cli, [str(wf)])
        assert run.exit_code == 4, run.stderr
        token = _TOKEN_RE.search(run.stdout).group(1)

        entry = next(r for r in _client().get("/api/runs").json() if r["run_id"] == token)
        assert entry["final_status"] == "paused"
        assert entry["paused_node_id"] == "gated"
        assert "gate_request" not in entry

        response = _client().get("/api/gate", params={"run": token})
        assert response.status_code == 200
        body = response.json()
        assert body["paused_node_id"] == "gated"
        assert body["gate_kind"] == "action_approval"
        assert "gated action" in body["gate_request"]["preview"]["command"]
        assert body["gate_request"]["preview"]["env"]["API_KEY"] == "<REDACTED>"
        assert "sk-super-secret" not in response.text, "the raw secret never reaches the browser"

    def test_unknown_run_id_is_404(self, tmp_path: Path, monkeypatch) -> None:
        self._debug_dir(tmp_path, monkeypatch)
        response = _client().get("/api/gate", params={"run": "no-such-run"})
        assert response.status_code == 404
        assert "no-such-run" in response.json()["error"]

    def test_non_paused_run_is_404(self, tmp_path: Path, monkeypatch) -> None:
        debug = self._debug_dir(tmp_path, monkeypatch)
        _write_paused_trace(
            debug,
            "workflow-trace-aaa-wf-20260101-000000-000001.json",
            "/wf.pflow.md",
            execution_id="done-run",
            final_status="success",
        )
        response = _client().get("/api/gate", params={"run": "done-run"})
        assert response.status_code == 404
        assert "not paused" in response.json()["error"]

    def test_paused_trailer_without_gate_request_is_404_not_500(self, tmp_path: Path, monkeypatch) -> None:
        """Edge ledger #2: a corrupt/hand-edited paused trailer (no gate_request) → the not-paused 404,
        never a 500 — mirroring the resume loader's malformed-pause refusal."""
        debug = self._debug_dir(tmp_path, monkeypatch)
        _write_paused_trace(
            debug,
            "workflow-trace-aaa-wf-20260101-000000-000001.json",
            "/wf.pflow.md",
            execution_id="corrupt-run",
            gate_request=None,
        )
        response = _client().get("/api/gate", params={"run": "corrupt-run"})
        assert response.status_code == 404

    def test_paused_trailer_without_gate_kind_is_404_not_a_null_kind_200(self, tmp_path: Path, monkeypatch) -> None:
        """`kind` is a required GateRequest field — a hand-corrupted trailer without it must land in
        the not-paused 404 (edge ledger #2's corruption stance), never a 200 whose `gate_kind` is
        null: the response contract types it as one of the two gate-kind literals and the typed
        frontend kind-switches on it (deep-review 2026-07-12)."""
        debug = self._debug_dir(tmp_path, monkeypatch)
        _write_paused_trace(
            debug,
            "workflow-trace-aaa-wf-20260101-000000-000001.json",
            "/wf.pflow.md",
            execution_id="kindless-run",
            gate_request={"node_id": "deploy", "node_type": "shell", "preview": {"command": "rm -rf"}},
        )
        response = _client().get("/api/gate", params={"run": "kindless-run"})
        assert response.status_code == 404

    def test_missing_run_param_is_400(self, tmp_path: Path, monkeypatch) -> None:
        self._debug_dir(tmp_path, monkeypatch)
        assert _client().get("/api/gate").status_code == 400
        assert _client().get("/api/gate", params={"run": ""}).status_code == 400

    def test_oversized_gate_request_is_still_served(self, tmp_path: Path, monkeypatch) -> None:
        """A paused trailer larger than the reader's 64 KB tail window (Task 171 gotcha) is still served
        in full — the endpoint rides read_run_trailer's one-shot full re-read."""
        debug = self._debug_dir(tmp_path, monkeypatch)
        big_value = "x" * 100_000
        _write_paused_trace(
            debug,
            "workflow-trace-aaa-wf-20260101-000000-000001.json",
            "/wf.pflow.md",
            execution_id="big-paused",
            gate_request={
                "node_id": "deploy",
                "node_type": "shell",
                "kind": "action_approval",
                "preview": {"payload": big_value},
            },
        )
        response = _client().get("/api/gate", params={"run": "big-paused"})
        assert response.status_code == 200
        assert response.json()["gate_request"]["preview"]["payload"] == big_value


# ── POST /api/resume (Task 176) ───────────────────────────────────────────────

# A real gated workflow (mirrors test_paused_cli.py) — pausing it via the actual CLI produces the
# REAL producer trace shape the answer-flow tests must run against (tests/CLAUDE.md pitfall #19;
# synthetic trailers are for projection tests only).
_PAUSED_GATE_WF = """# Paused Demo

A workflow whose second step needs a human approval.

## Steps

### g1

Upstream value.

- type: shell
- next: gated

```shell command
echo "g1-value"
```

### gated

Requires a human approval decision before running.

- type: shell
- env: { API_KEY: sk-super-secret }
- approval: required

```shell command
echo "gated action"
```
"""

# A run that FAILS at a side-effecting (shell) step — the failed-run Resume arm's pre-flight fodder.
_FAILING_WF = """# Failing Demo

A workflow whose only step fails.

## Steps

### boom

Always fails.

- type: shell

```shell command
exit 7
```
"""

_TOKEN_RE = re.compile(r"Resume token: (\S+) \(exit 4\)")


@pytest.mark.trace_files
class TestResumeEndpoint:
    """``POST /api/resume`` — the observe-and-spawn answer bridge (Task 176). ``subprocess.Popen``
    is patched around every POST (no real spawn); the REAL pre-flight (``preflight_resume`` + the
    child's compile) runs underneath, against REAL traces produced by pausing/failing actual CLI
    runs. The no-silent-no-op pins each assert ``popen.assert_not_called()`` — a refused answer
    must 4xx BEFORE the spawn, never exit-1 invisibly inside a DEVNULL'd child."""

    @staticmethod
    def _home(tmp_path: Path, monkeypatch) -> Path:
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        (tmp_path / ".pflow" / "debug").mkdir(parents=True)
        return tmp_path

    @staticmethod
    def _pause(wf: Path) -> str:
        """Run ``wf`` through the real CLI to a durable pause; return the resume token."""
        result = CliRunner(mix_stderr=False).invoke(cli, [str(wf)])
        assert result.exit_code == 4, result.stderr
        match = _TOKEN_RE.search(result.stdout)
        assert match, f"expected a token line; stdout:\n{result.stdout}"
        return match.group(1)

    @staticmethod
    def _paused_wf(tmp_path: Path) -> Path:
        path = tmp_path / "paused_demo.pflow.md"
        path.write_text(_PAUSED_GATE_WF, encoding="utf-8")
        return path

    def test_approve_yes_spawns_the_detached_resume_argv(self, tmp_path: Path, monkeypatch) -> None:
        self._home(tmp_path, monkeypatch)
        token = self._pause(self._paused_wf(tmp_path))
        with patch("pflow.ui.server.subprocess.Popen") as popen:
            response = _client().post("/api/resume", json={"run": token, "approve": "yes"})

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "spawned"
        run_id = body["run_id"]
        assert isinstance(run_id, str) and run_id
        popen.assert_called_once()
        argv = popen.call_args.args[0]
        assert argv == [
            sys.executable,
            "-m",
            "pflow.cli",
            "resume",
            token,
            "--output-format",
            "json",
            "--approve",
            "yes",
        ]
        kwargs = popen.call_args.kwargs
        assert kwargs["stdin"] == kwargs["stdout"] == kwargs["stderr"] == subprocess.DEVNULL
        if sys.platform == "win32":
            assert kwargs["creationflags"] == subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            assert kwargs["start_new_session"] is True
        # Forced onto the child so the browser pins the exact resumed attempt (Task 175 pattern).
        assert kwargs["env"]["PFLOW_EXECUTION_ID"] == run_id

    def test_approve_no_maps_to_its_flag(self, tmp_path: Path, monkeypatch) -> None:
        self._home(tmp_path, monkeypatch)
        token = self._pause(self._paused_wf(tmp_path))
        with patch("pflow.ui.server.subprocess.Popen") as popen:
            response = _client().post("/api/resume", json={"run": token, "approve": "no"})
        assert response.status_code == 200, response.text
        argv = popen.call_args.args[0]
        assert argv[-2:] == ["--approve", "no"]

    def test_choose_on_a_real_escalation_maps_to_its_flag(self, tmp_path: Path, monkeypatch) -> None:
        """An escalation pause answered with `choose` → `--choose <text>` (the label text — the
        numeric mapping is a loader-side terminal convenience; edge ledger #9)."""
        from pflow.registry import Registry
        from tests.test_runtime.test_gate_pause import EscalatingNode

        self._home(tmp_path, monkeypatch)
        # Registry injection (the test_paused_cli.py pattern — works only inside pytest, where
        # isolate_pflow_config redirects Registry to tmp paths).
        registry = Registry()
        nodes = registry.load()
        nodes["escalating-node"] = {
            "module": "tests.test_runtime.test_gate_pause",
            "class_name": "EscalatingNode",
            "docstring": EscalatingNode.__doc__ or "",
            "file_path": "tests/test_runtime/test_gate_pause.py",
            "type": "core",
            "interface": {
                "description": "Test node that raises a decision escalation.",
                "params": [{"key": "question", "type": "str", "description": "The escalation question"}],
                "inputs": [],
                "outputs": [{"key": "result", "type": "dict", "description": "Carries the escalation marker"}],
                "actions": ["default"],
            },
        }
        registry.save(nodes)
        wf = tmp_path / "esc_demo.pflow.md"
        wf.write_text(
            "# Escalation Demo\n\nAn escalating step, then a consumer.\n\n## Steps\n\n"
            "### esc\n\nRaises a decision escalation.\n\n"
            "- type: escalating-node\n- question: pick a or b\n- next: after\n\n"
            "### after\n\nReads the decision.\n\n- type: shell\n\n"
            '```shell command\necho "picked ${esc.result.escalation.decision.chosen}"\n```\n',
            encoding="utf-8",
        )
        token = self._pause(wf)
        with patch("pflow.ui.server.subprocess.Popen") as popen:
            response = _client().post("/api/resume", json={"run": token, "choose": "b"})
        assert response.status_code == 200, response.text
        argv = popen.call_args.args[0]
        assert argv[-2:] == ["--choose", "b"]

    def test_force_true_appends_the_flag_absent_otherwise(self, tmp_path: Path, monkeypatch) -> None:
        self._home(tmp_path, monkeypatch)
        wf = self._paused_wf(tmp_path)
        token = self._pause(wf)
        with patch("pflow.ui.server.subprocess.Popen") as popen:
            plain = _client().post("/api/resume", json={"run": token, "approve": "yes"})
            forced = _client().post("/api/resume", json={"run": token, "approve": "yes", "force": True})
        assert plain.status_code == forced.status_code == 200
        plain_argv, forced_argv = (call.args[0] for call in popen.call_args_list)
        assert "--force" not in plain_argv, "the server NEVER adds --force itself"
        assert forced_argv[-1] == "--force"

    def test_superseded_token_is_409_and_does_not_spawn(self, tmp_path: Path, monkeypatch) -> None:
        self._home(tmp_path, monkeypatch)
        token = self._pause(self._paused_wf(tmp_path))
        # Consume the token through the real CLI (deny → a real denied attempt trace, exit 3).
        denied = CliRunner(mix_stderr=False).invoke(cli, ["resume", token, "--approve", "no"])
        assert denied.exit_code == 3, denied.stderr
        with patch("pflow.ui.server.subprocess.Popen") as popen:
            response = _client().post("/api/resume", json={"run": token, "approve": "yes"})
        assert response.status_code == 409
        body = response.json()
        assert body["refusal"] == "superseded"
        assert isinstance(body["newer_execution_id"], str) and body["newer_execution_id"]
        assert body["errors"]
        popen.assert_not_called()

    def test_side_effecting_failed_entry_is_409_with_node_facts(self, tmp_path: Path, monkeypatch) -> None:
        """Bare resume of a failed run whose entry K is side-effecting (shell) → the non-TTY refusal,
        carrying K's id + REGISTRY type so the browser dialog is buildable from this body alone."""
        self._home(tmp_path, monkeypatch)
        wf = tmp_path / "failing.pflow.md"
        wf.write_text(_FAILING_WF, encoding="utf-8")
        failed = CliRunner(mix_stderr=False).invoke(cli, [str(wf)])
        assert failed.exit_code == 1, failed.stderr
        with patch("pflow.ui.server.subprocess.Popen") as popen:
            response = _client().post("/api/resume", json={"run": str(wf)})
        assert response.status_code == 409
        body = response.json()
        assert body["refusal"] == "side_effect_confirmation"
        assert body["node_id"] == "boom"
        assert body["node_type"] == "shell"
        popen.assert_not_called()

    def test_stale_workflow_is_409_and_does_not_spawn(self, tmp_path: Path, monkeypatch) -> None:
        self._home(tmp_path, monkeypatch)
        wf = self._paused_wf(tmp_path)
        token = self._pause(wf)
        wf.write_text(wf.read_text(encoding="utf-8") + "\n<!-- edited since the pause -->\n", encoding="utf-8")
        with patch("pflow.ui.server.subprocess.Popen") as popen:
            response = _client().post("/api/resume", json={"run": token, "approve": "yes"})
        assert response.status_code == 409
        body = response.json()
        assert body["refusal"] == "stale_workflow"
        assert body["hash_known"] is True
        popen.assert_not_called()

    def test_unanswered_paused_is_409_answer_required_with_the_masked_gate(self, tmp_path: Path, monkeypatch) -> None:
        self._home(tmp_path, monkeypatch)
        token = self._pause(self._paused_wf(tmp_path))
        with patch("pflow.ui.server.subprocess.Popen") as popen:
            response = _client().post("/api/resume", json={"run": token})
        assert response.status_code == 409
        body = response.json()
        assert body["refusal"] == "answer_required"
        gate = body["errors"][0]["context"]["gate"]  # rides the diagnostic, already masked
        assert gate["kind"] == "action_approval"
        assert gate["preview"]["env"]["API_KEY"] == "<REDACTED>"
        assert "sk-super-secret" not in response.text
        popen.assert_not_called()

    def test_both_answer_flags_is_400_and_does_not_spawn(self, tmp_path: Path, monkeypatch) -> None:
        self._home(tmp_path, monkeypatch)
        with patch("pflow.ui.server.subprocess.Popen") as popen:
            response = _client().post("/api/resume", json={"run": "x", "approve": "yes", "choose": "b"})
        assert response.status_code == 400
        assert "mutually exclusive" in response.json()["error"]
        popen.assert_not_called()

    def test_shape_errors_are_400_before_any_io(self, tmp_path: Path, monkeypatch) -> None:
        self._home(tmp_path, monkeypatch)
        bad_bodies = [
            {},  # missing run
            {"run": ""},  # empty run
            {"run": "x", "approve": "YES"},  # server-stricter: lowercase only
            {"run": "x", "choose": "   "},  # whitespace choose
            {"run": "x", "force": "yes"},  # non-boolean force
        ]
        with patch("pflow.ui.server.subprocess.Popen") as popen:
            for body in bad_bodies:
                assert _client().post("/api/resume", json=body).status_code == 400, body
        popen.assert_not_called()

    def test_equals_bearing_target_is_400_and_does_not_spawn(self, tmp_path: Path, monkeypatch) -> None:
        """Argv parity (deep-review 2026-07-12): the spawned child's `_split_target_and_params`
        reads every `=`-bearing token as a workflow input, so a `=`-bearing TARGET (only a file
        path can carry one) leaves the child with zero positionals — UsageError exit 2 straight
        into DEVNULL, the silent no-op class the pre-flight exists to eliminate. The server must
        refuse it loudly BEFORE the pre-flight can pass on a resolvable path."""
        self._home(tmp_path, monkeypatch)
        with patch("pflow.ui.server.subprocess.Popen") as popen:
            response = _client().post("/api/resume", json={"run": "./runs/foo=bar.pflow.md"})
        assert response.status_code == 400
        assert "must not contain '='" in response.json()["error"]
        popen.assert_not_called()

    def test_unknown_run_id_is_404_and_does_not_spawn(self, tmp_path: Path, monkeypatch) -> None:
        self._home(tmp_path, monkeypatch)
        ghost = "00000000-0000-4000-8000-000000000000"  # uuid-shaped, matches nothing
        with patch("pflow.ui.server.subprocess.Popen") as popen:
            response = _client().post("/api/resume", json={"run": ghost})
        assert response.status_code == 404
        assert response.json()["refusal"] == "missing"
        popen.assert_not_called()

    def test_non_loopback_host_is_403_and_does_not_spawn(self, tmp_path: Path, monkeypatch) -> None:
        self._home(tmp_path, monkeypatch)
        with patch("pflow.ui.server.subprocess.Popen") as popen:
            response = _client().post("/api/resume", json={"run": "x", "approve": "yes"}, headers={"host": "evil.com"})
        assert response.status_code == 403
        popen.assert_not_called()


def test_refusal_literal_map_covers_every_resume_source_error() -> None:
    """The `refusal` discriminator is the frontend's typed contract (plan §P2-3 — the panel
    switches on it, never string-parses). A future ResumeSourceError subclass that is missing from
    `_RESUME_REFUSALS` would 409 with NO literal — the panel silently degrades to the generic
    inline-errors arm with no failing test. This introspection net makes that gap loud: adding a
    refusal family forces a deliberate decision about its HTTP literal."""
    import pflow.core.exceptions as exceptions_module
    from pflow.ui.server import _RESUME_REFUSALS

    subclasses = {
        obj
        for obj in vars(exceptions_module).values()
        if isinstance(obj, type)
        and issubclass(obj, exceptions_module.ResumeSourceError)
        and obj is not exceptions_module.ResumeSourceError
    }
    assert set(_RESUME_REFUSALS) == subclasses, (
        "every ResumeSourceError subclass needs a `refusal` literal in server._RESUME_REFUSALS "
        "(or a deliberate, documented exclusion)"
    )


class TestHostGuard:
    """The ``_LoopbackOnly`` middleware — the DNS-rebinding guard on EVERY route (Task 175), reads and
    writes. A non-loopback Host is 403; loopback variants pass. (Read-endpoint coverage is pinned by
    ``test_guard_also_covers_read_endpoints``.)"""

    def test_non_loopback_host_is_403_and_does_not_spawn(self, tmp_path: Path) -> None:
        workflow = str(_workflow(tmp_path))
        with patch("pflow.ui.server.subprocess.Popen") as popen:
            response = _client().post(
                "/api/run",
                json={"workflow": workflow, "inputs": {}},
                headers={"host": "evil.com"},
            )

        assert response.status_code == 403
        popen.assert_not_called()

    def test_loopback_hosts_pass_the_guard(self, tmp_path: Path) -> None:
        # 127.0.0.1[:port], localhost[:port] (case-insensitive), and an IPv6 [::1]:port literal all resolve to loopback.
        workflow = str(_workflow(tmp_path))
        for host in ("127.0.0.1:8765", "localhost:8765", "LOCALHOST:8765", "[::1]:8765"):
            with patch("pflow.ui.server.subprocess.Popen"):
                response = _client().post(
                    "/api/run",
                    json={"workflow": workflow, "inputs": {}},
                    headers={"host": host},
                )
            assert response.status_code == 200, host

    def test_guard_also_rejects_the_existing_mutating_posts(self, tmp_path: Path) -> None:
        workflow = str(_workflow(tmp_path))
        evil = {"host": "evil.com"}
        assert (
            _client().post("/api/command", json={"workflow": workflow, "type": "clear"}, headers=evil).status_code
            == 403
        )
        assert (
            _client()
            .post(
                "/api/say",
                json={"workflow": workflow, "type": "focus", "target": "greet", "caption": "hi"},
                headers=evil,
            )
            .status_code
            == 403
        )
        assert (
            _client().post("/api/narration", json={"audio_id": "x", "event": "blocked"}, headers=evil).status_code
            == 403
        )
        assert (
            _client().post("/api/interaction", json={"workflow": workflow, "type": "x"}, headers=evil).status_code
            == 403
        )
        assert (
            _client().post("/api/visibility", json={"conn_id": "c", "visibility": "hidden"}, headers=evil).status_code
            == 403
        )

    def test_guard_also_covers_read_endpoints(self, tmp_path: Path) -> None:
        # The guard is middleware on EVERY route, so a DNS-rebinding attacker can't READ workflow/trace
        # content (/api/source, /api/graph, ...) either — not just mutate. A non-loopback Host → 403; the
        # same request from loopback is NOT 403 (it reaches the handler: 200/400/422, endpoint-dependent).
        workflow = str(_workflow(tmp_path))
        evil = {"host": "evil.com"}
        for path, params in (
            ("/api/graph", {"workflow": workflow}),
            ("/api/source", {"workflow": workflow}),
            ("/api/catalog", {}),
            ("/api/audio/some-id", {}),
            ("/api/gate", {"run": "some-run"}),
        ):
            assert _client().get(path, params=params, headers=evil).status_code == 403, path
            assert _client().get(path, params=params).status_code != 403, path


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
        "headers": [(b"host", b"127.0.0.1")],  # the _LoopbackOnly guard 403s a request with no/non-loopback Host
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

    async def _drive() -> tuple[str, str, str]:
        response = await events(Request(scope))
        body = response.body_iterator
        # Each pull resumes stream() to its next yield: the first returns the
        # connected handshake; the second returns the Task-173 catch-up run-snapshot
        # the stream enqueues for every new viewer (empty here — no run in progress);
        # the third blocks on the keepalive timeout (0.01s) and returns the comment
        # frame. aclose() then raises GeneratorExit at the yield, so stream()'s
        # finally unregisters the connection.
        connected = await asyncio.wait_for(body.__anext__(), timeout=2.0)
        snapshot = await asyncio.wait_for(body.__anext__(), timeout=2.0)
        keepalive = await asyncio.wait_for(body.__anext__(), timeout=2.0)
        await body.aclose()
        return connected, snapshot, keepalive

    with patch.dict(events.__globals__, {"_KEEPALIVE_S": 0.01}):
        connected, snapshot, keepalive = asyncio.run(_drive())

    assert '"type": "connected"' in connected
    assert '"boot_id"' in connected  # Issue #539: the restart-fence nonce rides the handshake
    assert '"type": "run-snapshot"' in snapshot  # Task-173 catch-up frame for new viewers
    assert keepalive.strip().startswith(":")  # the idle keepalive comment frame
    assert app.state.hub.windows_for(str(workflow.resolve())) == []


def test_events_replays_the_latched_point_to_a_new_connection(tmp_path: Path) -> None:
    """Issue #539: a Viewer connecting AFTER an agent Point catches up to it.

    A focus issued while a tab was hidden (its SSE closed to free a connection slot) — or before a new tab
    opened — is latched server-side; every new /api/events stream replays it right after the run snapshot,
    so the tab adopts the agent's current highlight. Drives the response generator directly (same technique
    as the keepalive test) to read the ordered frames without racing the ASGI disconnect listener."""
    workflow = _workflow(tmp_path)
    app = create_app()

    # An agent points at a node while no tab of this workflow is connected.
    _client(app).post("/api/command", json={"workflow": str(workflow), "type": "focus", "target": "greet"})

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/events",
        "query_string": urlencode({"workflow": str(workflow), "visibility": "visible"}).encode(),
        "headers": [],
        "app": app,
    }

    async def _drive() -> tuple[str, str, str]:
        response = await events(Request(scope))
        body = response.body_iterator
        connected = await asyncio.wait_for(body.__anext__(), timeout=2.0)
        snapshot = await asyncio.wait_for(body.__anext__(), timeout=2.0)
        latched = await asyncio.wait_for(body.__anext__(), timeout=2.0)  # the Point replay, after the snapshot
        await body.aclose()
        return connected, snapshot, latched

    connected, snapshot, latched = asyncio.run(_drive())

    assert '"type": "connected"' in connected
    assert '"type": "run-snapshot"' in snapshot
    payload = json.loads(latched.removeprefix("data: ").strip())
    assert payload["type"] == "focus"
    assert payload["target"]["ref"]["node_id"] == "greet"
    assert payload["epoch"] == 1  # the client dedups against this so the replay is idempotent


def test_events_replays_the_latched_run_selection_to_a_new_connection(tmp_path: Path) -> None:
    """Issue #539: `select-run` is latched, so a window that connects AFTER the agent steered the workflow to
    a run catches up to it — this is what lets the agent steer a backgrounded/returning window, not just a
    live one. Only the run is latched here, so the replay is the third frame (connected → snapshot → run)."""
    workflow = _workflow(tmp_path)
    app = create_app()

    # The agent steers the workflow to a run while no tab is connected.
    _client(app).post("/api/command", json={"workflow": str(workflow), "type": "select-run", "target": "run-xyz"})

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/events",
        "query_string": urlencode({"workflow": str(workflow), "visibility": "visible"}).encode(),
        "headers": [],
        "app": app,
    }

    async def _drive() -> tuple[str, str, str]:
        response = await events(Request(scope))
        body = response.body_iterator
        connected = await asyncio.wait_for(body.__anext__(), timeout=2.0)
        snapshot = await asyncio.wait_for(body.__anext__(), timeout=2.0)
        steered = await asyncio.wait_for(body.__anext__(), timeout=2.0)  # the run replay, after the snapshot
        await body.aclose()
        return connected, snapshot, steered

    connected, snapshot, steered = asyncio.run(_drive())

    assert '"type": "connected"' in connected
    assert '"type": "run-snapshot"' in snapshot
    assert json.loads(steered.removeprefix("data: ").strip()) == {"type": "select-run", "run": "run-xyz", "epoch": 1}
