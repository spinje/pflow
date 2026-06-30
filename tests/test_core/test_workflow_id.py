"""Task 173 — the canonical IR digest factored out of the inline-workflow id (workflow_id.py).

The digest is the shared fingerprint behind TWO consumers: the inline-run scope id (``ir-hash:<digest>``)
and the replay version-detection ``content_hash`` (producer stamp + replay compare). Both depend on it being
ORDER-INSENSITIVE and DETERMINISTIC, and on ``synthesize_inline_workflow_id`` being exactly that digest under
an ``ir-hash:`` prefix (one definition — a drift would silently make an inline replay false-flag stale)."""

from __future__ import annotations

from pflow.core.workflow_id import canonical_ir_digest, synthesize_inline_workflow_id, workflow_content_hash


def test_canonical_ir_digest_is_insensitive_to_dict_key_order() -> None:
    a = {"ir_version": "0.1.0", "nodes": [{"id": "x", "type": "shell", "params": {"command": "echo hi"}}]}
    b = {"nodes": [{"params": {"command": "echo hi"}, "type": "shell", "id": "x"}], "ir_version": "0.1.0"}
    assert canonical_ir_digest(a) == canonical_ir_digest(b)


def test_canonical_ir_digest_changes_when_content_changes() -> None:
    base = {"nodes": [{"id": "greet", "type": "shell", "params": {"command": "echo hi"}}]}
    renamed = {"nodes": [{"id": "greet2", "type": "shell", "params": {"command": "echo hi"}}]}
    assert canonical_ir_digest(base) != canonical_ir_digest(renamed)


def test_synthesize_inline_workflow_id_is_the_digest_under_an_ir_hash_prefix() -> None:
    # ONE definition: the inline id is exactly ``ir-hash:`` + the digest. The whole replay feature's
    # inline short-circuit (``_is_stale`` returns False on an ``ir-hash:`` key) banks on this equality.
    ir = {"nodes": [{"id": "x", "type": "shell", "params": {"command": "echo hi"}}]}
    assert synthesize_inline_workflow_id(ir) == f"ir-hash:{canonical_ir_digest(ir)}"


def test_workflow_content_hash_ignores_source_location_provenance() -> None:
    # The replay fingerprint is the LOGICAL workflow: a node that differs ONLY in source-line provenance
    # (`_source_line`/`_source_lines`/`_source_files` — editor-click metadata a comment/whitespace edit
    # shifts) hashes the SAME, so a layout-only edit never reads as "a different version".
    at_line_7 = {"nodes": [{"id": "x", "type": "shell", "params": {"command": "echo hi"}, "_source_line": 7}]}
    at_line_9 = {"nodes": [{"id": "x", "type": "shell", "params": {"command": "echo hi"}, "_source_line": 9}]}
    assert workflow_content_hash(at_line_7) == workflow_content_hash(at_line_9)
    # …and it still differs from the raw digest (provenance WAS present and stripped).
    assert workflow_content_hash(at_line_7) != canonical_ir_digest(at_line_7)


def test_workflow_content_hash_still_changes_on_a_logical_edit() -> None:
    # A real change (node rename) must still flip it — and `_routes_to_end` is semantic, NOT stripped.
    base = {"nodes": [{"id": "greet", "type": "shell", "params": {"command": "echo hi"}, "_source_line": 3}]}
    renamed = {"nodes": [{"id": "greet2", "type": "shell", "params": {"command": "echo hi"}, "_source_line": 3}]}
    routed = {"nodes": [{"id": "greet", "type": "shell", "params": {"command": "echo hi"}, "_routes_to_end": True}]}
    assert workflow_content_hash(base) != workflow_content_hash(renamed)
    assert workflow_content_hash(base) != workflow_content_hash(routed)  # _routes_to_end is kept (semantic)


def test_workflow_content_hash_does_not_mutate_its_input() -> None:
    ir = {"nodes": [{"id": "x", "type": "shell", "params": {"command": "echo hi"}, "_source_line": 7}]}
    workflow_content_hash(ir)
    assert ir["nodes"][0]["_source_line"] == 7, "the strip must rebuild containers, never mutate resolved.ir"
