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

Not an e2e test
---------------
Validation is in-process (same path as CLI ``--validate-only``): parse →
inject dummy params → ``WorkflowValidator.validate``. Guide examples are never
*executed*, so there are no network calls, no LLM cost, and no shell side
effects. It runs in the default ``make test`` suite — which is the point: an
``e2e`` marker would exclude it and the guard would not run by default.

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
from pflow.core.workflow.validator import WorkflowValidator
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
    ir = parse_markdown(path.read_text()).ir
    normalize_ir(ir)

    node_ids = {n.get("id") for n in ir.get("nodes", [])}
    inputs = ir.setdefault("inputs", {})
    for var in set(_BARE_VAR_RE.findall(path.read_text())):
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
    ir = parse_markdown(path.read_text()).ir
    normalize_ir(ir)
    used = {n.get("type") for n in ir.get("nodes", []) if n.get("type")}
    return used - registered


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
