"""Server-side Point/Watch hub and endpoint contracts."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from unittest.mock import AsyncMock, patch
from urllib.parse import urlencode

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.testclient import TestClient

from pflow.core.workflow.manager import WorkflowManager
from pflow.ui.server import _ACTIVITY_MAX, _Hub, _workflow_key, create_app, events
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

        assert body == {"service": "pflow-ui", "workflow_key": key, "windows": 2}

    def test_identity_only_without_a_workflow(self) -> None:
        assert _client().get("/api/health").json() == {"service": "pflow-ui"}

    def test_unknown_workflow_is_identity_only_not_404(self) -> None:
        # A liveness probe must answer regardless — unlike command()/activity(), which 404.
        response = _client().get("/api/health", params={"workflow": "no-such-workflow-xyz"})
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
        assert kwargs["start_new_session"] is True
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
