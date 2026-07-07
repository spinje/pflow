"""Validate the runnable workflow examples embedded in the pflow guide.

Sibling of ``test_example_validation.py``: that one validates shipped files
under ``examples/``; this one validates the workflow examples written inline
in the guide source (``src/pflow/guide/**/*.md``) that an agent reads via
``pflow guide``.

Why this exists
---------------
The guide is the agent-facing surface. A guide example that doesn't compile,
references a sub-workflow file that doesn't exist, or names an upstream node
that isn't there teaches the agent a broken pattern. Those exact failure
classes (phantom sub-workflow ref, drifted node reference, unknown node type)
shipped in the guide before and were only caught by hand. This test makes the
guard automatic.

Determinism / gap-proofness
---------------------------
A fenced block is treated as a complete-workflow claim iff it contains a
``## Steps`` header. ``## Steps`` is *required* in every real pflow workflow
and never appears in a single-node fragment excerpt, so the extraction set is
defined by a format invariant, not a heuristic. Any complete workflow added
to the guide later carries ``## Steps`` and is covered automatically — there
is no marker to forget.

Two tiers, both in-process
--------------------------
1. **Validation** (every complete example): same path as CLI
   ``--validate-only`` — parse → inject dummy params →
   ``WorkflowValidator.validate``.
2. **Execution** (the self-contained subset only — ``code``/``shell`` nodes,
   no caller-supplied inputs): runs via ``WorkflowRunner`` and asserts the run
   reaches a terminal state without raising or ending FAILED. This catches
   runtime drift validation can't see — a documented loop that errors or never
   produces its condition, a code body that raises. It replaces the former
   hand-copied ``test_loop_example.py``, which mirrored one guide loop by hand.

Both tiers are in-process and run in the default ``make test`` suite (no
``e2e`` marker, or the guard would not run by default). The execution subset is
deliberately narrow: no network (http/mcp), no LLM cost (llm/claude-code), and
no missing-input failures, so it stays hermetic and fast.

Tolerances (deliberate, not false-failure suppression)
------------------------------------------------------
- **Excerpts that omit ``## Inputs``.** Many examples reference ``${api_url}``
  style placeholders to teach a pattern without declaring a full input
  surface. Bare ``${name}`` refs (no dot) that aren't node ids are injected as
  optional inputs before validation. Dotted refs (``${node.key}``) are left
  untouched, so node-reference typos and phantom sub-workflows STILL fail —
  verified by the negative cases in ``test_negative_cases_still_fail``.
- **MCP nodes.** Blocks whose only unregistered node types are ``mcp-*`` are
  skipped (MCP interfaces depend on user-configured servers) — same contract
  as the sibling example test.
"""

import re
from pathlib import Path

import pytest

from pflow.core.diagnostic import Severity
from pflow.core.exceptions import MarkdownParseError, SchemaValidationError
from pflow.core.file_resolver import get_base_dir, resolve_file_references
from pflow.core.ir_schema import normalize_ir
from pflow.core.markdown_parser import parse_markdown
from pflow.core.validation_utils import generate_dummy_parameters
from pflow.core.workflow.status import WorkflowStatus
from pflow.core.workflow.validator import WorkflowValidator
from pflow.execution.result import RunnerConfig
from pflow.execution.runner import WorkflowRunner
from pflow.registry import Registry

GUIDE_DIR = Path(__file__).parent.parent.parent / "src" / "pflow" / "guide"

# Outermost fenced block; the backreference closes on the same fence width, so
# a ````markdown wrapper containing ```shell blocks is captured as ONE block.
_FENCE_RE = re.compile(r"(?m)^(`{3,})([^\n`]*)\n(.*?)^\1[ \t]*$", re.S)
# A filename hint in the prose just before a block, e.g. ``(`to-uppercase.pflow.md`)``.
_HINT_RE = re.compile(r"`([A-Za-z0-9._-]+\.pflow\.md)`")
# A bare template var ``${name}`` — no dot, no index. Dotted refs are node outputs.
_BARE_VAR_RE = re.compile(r"\$\{([a-zA-Z_][\w-]*)\}")
_STEPS_RE = re.compile(r"(?m)^##\s+Steps\b", re.I)
_TITLE_RE = re.compile(r"(?m)^#\s+\S")


def _has_steps(body: str) -> bool:
    """A block is a complete-workflow claim iff it declares ``## Steps``."""
    return bool(_STEPS_RE.search(body))


def _filename_hint(prose_before: str) -> str | None:
    """Recover the child filename a block is presented as, from preceding prose."""
    hits = _HINT_RE.findall(prose_before)
    return hits[-1] if hits else None


def _collect_guide_workflows(tmp_root: Path) -> list[tuple[str, Path]]:
    """Extract every ``## Steps`` block and materialize it on disk.

    Blocks from the same guide file are written into one directory so that
    sub-workflow cross-references (``workflow: ./child.pflow.md``) resolve
    against sibling blocks — the guide presents child and parent as separate
    fenced blocks. Returns ``(label, path)`` pairs.
    """
    collected: list[tuple[str, Path]] = []
    for md_file in sorted(GUIDE_DIR.rglob("*.md")):
        text = md_file.read_text()
        blocks: list[tuple[str | None, str]] = []
        for match in _FENCE_RE.finditer(text):
            body = match.group(3)
            if not _has_steps(body):
                continue
            prose_before = "\n".join(text[: match.start()].rstrip().splitlines()[-3:])
            blocks.append((_filename_hint(prose_before), body))
        if not blocks:
            continue

        file_dir = tmp_root / md_file.stem
        file_dir.mkdir(parents=True, exist_ok=True)
        for idx, (hint, body) in enumerate(blocks):
            name = hint or f"guide_block_{idx}.pflow.md"
            # Near-complete excerpts omit the H1 title; synthesize one so the
            # parser accepts the document. Content is otherwise verbatim.
            content = (
                body if _TITLE_RE.search(body) else f"# Guide Example {idx}\n\nExtracted from {md_file.name}.\n\n{body}"
            )
            path = file_dir / name
            path.write_text(content)
            collected.append((f"{md_file.name}:{name}", path))
    return collected


def _validate(path: Path, registry: Registry) -> list:
    """Run the CLI ``--validate-only`` pipeline on one extracted block.

    Bare undeclared ``${name}`` refs are injected as optional inputs so
    pattern-teaching excerpts that omit ``## Inputs`` validate structurally;
    dotted node refs are left alone so typos/phantom children still fail.
    Returns ERROR-severity diagnostics.
    """
    ir = parse_markdown(path.read_text(encoding="utf-8")).ir
    normalize_ir(ir)

    node_ids = {n.get("id") for n in ir.get("nodes", [])}
    inputs = ir.setdefault("inputs", {})
    for var in set(_BARE_VAR_RE.findall(path.read_text(encoding="utf-8"))):
        if var in node_ids or var in inputs:
            continue
        inputs[var] = {"type": "string", "required": False, "default": "dummy"}

    dummy = generate_dummy_parameters(ir.get("inputs", {}))
    dummy["_pflow_workflow_file"] = str(path)
    resolve_file_references(ir, get_base_dir(dummy))

    diagnostics = WorkflowValidator.validate(
        ir,
        extracted_params=dummy,
        registry=registry,
        workflow_file=path,
    )
    return [d for d in diagnostics if d.severity == Severity.ERROR]


def _unregistered_types(path: Path, registered: set[str]) -> set[str]:
    ir = parse_markdown(path.read_text(encoding="utf-8")).ir
    normalize_ir(ir)
    used = {n.get("type") for n in ir.get("nodes", []) if n.get("type")}
    return used - registered


# Node types safe to execute in-process with no external dependencies and
# deterministic behavior. NOT http/mcp (network), llm/claude-code (cost), or
# file ops (would need a hermetic-cwd guarantee before widening).
_RUNNABLE_NODE_TYPES = {"code", "shell"}


def _is_self_contained_runnable(path: Path) -> bool:
    """True if the example runs with ``{}`` — only ``code``/``shell`` nodes and
    no caller-supplied required inputs. Keeps the execution tier hermetic: no
    network, no LLM cost, no missing-input failures.
    """
    ir = parse_markdown(path.read_text(encoding="utf-8")).ir
    normalize_ir(ir)
    types = {n.get("type") for n in ir.get("nodes", []) if n.get("type")}
    if not types or not types <= _RUNNABLE_NODE_TYPES:
        return False
    # pflow inputs are required-by-default: a declared input needs a caller value
    # unless it has a `default` or is explicitly `required: false`.
    for spec in (ir.get("inputs") or {}).values():
        if isinstance(spec, dict) and "default" not in spec and spec.get("required") is not False:
            return False
    return True


class TestGuideExampleValidation:
    """Every complete workflow shown in the guide must pass structural validation."""

    @pytest.fixture(scope="class")
    def guide_workflows(self, tmp_path_factory: pytest.TempPathFactory) -> list[tuple[str, Path]]:
        if not GUIDE_DIR.exists():
            pytest.skip("Guide directory not found")
        return _collect_guide_workflows(tmp_path_factory.mktemp("guide_examples"))

    def test_guide_examples_pass_validation(self, guide_workflows: list[tuple[str, Path]]) -> None:
        """All ``## Steps`` blocks in the guide validate (MCP-only excerpts skipped)."""
        assert guide_workflows, "No guide workflow examples found — extraction likely broke"

        registry = Registry()
        registered = set(registry.load().keys())

        failures: list[tuple[str, str]] = []
        skipped: list[str] = []
        for label, path in guide_workflows:
            missing = _unregistered_types(path, registered)
            if missing and all(t.startswith("mcp-") for t in missing):
                skipped.append(label)
                continue
            try:
                errors = _validate(path, registry)
            except (MarkdownParseError, SchemaValidationError, ValueError) as exc:
                failures.append((label, f"{type(exc).__name__}: {exc}"))
                continue
            failures.extend((label, e.message) for e in errors)

        if failures:
            rendered = "\n".join(f"  {label}: {msg}" for label, msg in failures)
            pytest.fail(
                f"{len(failures)} validation error(s) in guide examples "
                f"({len(skipped)} MCP-only block(s) skipped):\n{rendered}"
            )

    def test_extraction_coverage_is_meaningful(self, guide_workflows: list[tuple[str, Path]]) -> None:
        """Guard against extraction silently finding nothing (regex/format drift)."""
        assert len(guide_workflows) >= 7, (
            f"Expected >=7 guide workflow examples, found {len(guide_workflows)}. "
            "The ## Steps extraction may have broken, or examples were removed."
        )

    def test_negative_cases_still_fail(self, tmp_path: Path) -> None:
        """The tolerances must not mask real bugs.

        Phantom sub-workflow refs, drifted node references, and unknown node
        types must all still produce ERROR diagnostics — otherwise the
        bare-var input injection would have made the whole test toothless.
        """
        registry = Registry()
        cases = {
            "phantom_child": (
                "# P\n\nReferences a missing child.\n\n## Steps\n\n### c\n\n"
                "Call a child that does not exist.\n\n- type: workflow\n"
                "- workflow: ./does-not-exist.pflow.md\n- inputs:\n    x: hi\n"
            ),
            "drifted_node_ref": (
                "# D\n\nReferences a ghost node.\n\n## Steps\n\n### a\n\nFirst.\n\n"
                "- type: shell\n\n```shell command\necho hi\n```\n\n### b\n\n"
                "Second references a node that isn't there.\n\n- type: shell\n\n"
                '```shell command\necho "${ghost-node.result}"\n```\n'
            ),
            "unknown_node_type": (
                "# T\n\nUses a node type that doesn't exist.\n\n## Steps\n\n### a\n\n"
                "Bad type.\n\n- type: not-a-real-node\n\n```shell command\necho hi\n```\n"
            ),
        }
        for label, content in cases.items():
            path = tmp_path / f"{label}.pflow.md"
            path.write_text(content)
            try:
                errors = _validate(path, registry)
            except (MarkdownParseError, SchemaValidationError, ValueError):
                continue  # raising is also an acceptable "caught it"
            assert errors, f"{label!r} should have produced a validation error but passed"

    def test_self_contained_examples_execute(self, guide_workflows: list[tuple[str, Path]]) -> None:
        """The self-contained subset must RUN, not just validate.

        Validation proves a workflow is structurally sound; it cannot prove the
        loop terminates or the code body doesn't raise. Running the
        ``code``/``shell``-only, no-input examples closes that gap — a documented
        example that crashes or ends FAILED breaks CI. A run that ends DEGRADED
        is allowed: the ``on-error:`` fallback example legitimately completes
        with a warning. Examples needing network/LLM or caller inputs are
        validated above but not executed here.
        """
        runnable = [(label, path) for label, path in guide_workflows if _is_self_contained_runnable(path)]
        assert len(runnable) >= 2, (
            f"Expected >=2 self-contained runnable examples (the loop and error-handling demos), "
            f"found {len(runnable)}. The runnable filter or a code fence may have broken."
        )

        failures: list[tuple[str, str]] = []
        for label, path in runnable:
            try:
                result = WorkflowRunner().run(str(path), {}, RunnerConfig(cache_enabled=False))
            except Exception as exc:
                failures.append((label, f"raised {type(exc).__name__}: {exc}"))
                continue
            if result.status == WorkflowStatus.FAILED:
                msgs = "; ".join(d.message for d in result.errors) or "(no error message)"
                failures.append((label, f"ended FAILED: {msgs}"))

        if failures:
            rendered = "\n".join(f"  {label}: {msg}" for label, msg in failures)
            pytest.fail(f"{len(failures)} self-contained guide example(s) failed to run:\n{rendered}")

    def test_loop_example_terminates_by_condition(self, guide_workflows: list[tuple[str, Path]]) -> None:
        """Documented ``loop:`` examples must stop on their own condition.

        The breadth execution test above only proves a loop example doesn't
        crash — it would still pass if the loop silently ran to ``max_iterations``
        instead of terminating on its ``until:``/``while:`` condition. This pins
        the behavior that makes the example *correct*: the loop ends because its
        condition was met (``loop_stopped == "condition"``), not because it hit
        the iteration cap. A regression in condition-termination fails here.
        """
        loop_examples: list[tuple[str, Path, str]] = []
        for label, path in guide_workflows:
            if not _is_self_contained_runnable(path):
                continue
            ir = parse_markdown(path.read_text()).ir
            normalize_ir(ir)
            loop_examples.extend(
                (label, path, n["id"]) for n in ir.get("nodes", []) if n.get("loop") is not None and n.get("id")
            )

        assert loop_examples, (
            "No self-contained loop: example found in the guide (expected the Count Up demo in loop.md). "
            "The runnable filter or the loop example may have broken."
        )

        for label, path, loop_id in loop_examples:
            result = WorkflowRunner().run(str(path), {}, RunnerConfig(cache_enabled=False))
            assert result.status != WorkflowStatus.FAILED, f"{label}: loop example ended FAILED"
            output = result.shared_after.get(loop_id) or {}
            assert output.get("loop_stopped") == "condition", (
                f"{label}: loop node {loop_id!r} stopped via {output.get('loop_stopped')!r}, expected "
                "'condition' — the documented loop no longer terminates on its own condition "
                "(it ran to max_iterations instead)."
            )
