#!/usr/bin/env python3
"""Audit ``@mutation_contract`` markers across the test suite (ad-hoc, not per-PR).

This is an **audit tool**, not a quality gate. Operational data shows the
contracts catch line-shift drift after refactors more often than real test
rot — useful as a periodic honesty check (before releases, when reviewing
sketchy refactors, when test count balloons), not as a continuous-integration
signal. Run via ``make mutation-audit``.

For each test decorated with ``@mutation_contract``:

1. Backs up the production file.
2. Replaces the matched line with ``<indent>pass  # MUTATED: <original>``.
3. Runs ``pytest <test_module>::<test_name>`` and asserts the test fails.
4. Restores the production file unconditionally (try/finally).

Exits 0 if every contract is verified; non-zero otherwise. Prints a per-
contract status line and a summary of failures.

Usage::

    make mutation-audit                                    # full audit, parallel
    uv run python scripts/check_mutation_contracts.py      # full audit, serial
    uv run python scripts/check_mutation_contracts.py --filter trace_tree
    uv run python scripts/check_mutation_contracts.py --jobs 4

The ``--filter`` flag matches against either the test name or the test file
path. ``--jobs`` runs contracts in parallel (default: serial — safer because
each contract mutates a production file). Parallel mode requires that no two
contracts mutate the same file concurrently; the script groups by file and
serializes within a group.
"""

from __future__ import annotations

import argparse
import contextlib
import importlib
import inspect
import subprocess
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = REPO_ROOT / "tests"


def discover_marked_tests(
    filter_substr: str | None = None,
) -> tuple[list[tuple[str, str, Any]], list[str]]:
    """Walk tests/ and return ``([(rel_test_path, pytest_node_id, contract), ...], skipped_modules)``.

    ``pytest_node_id`` is the ``test_name`` for module-level functions and
    ``ClassName::method_name`` for class-method tests — pytest accepts both
    when invoked as ``pytest path::node_id``.

    ``skipped_modules`` is a list of ``"module: error"`` strings — non-empty
    when any test module failed to import (its markers, if any, are invisible
    to the verifier). Caller MUST surface skips as failures: a marker hidden
    behind an import error is silently disabled, exactly the regression the
    verifier exists to prevent.
    """
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    results: list[tuple[str, str, Any]] = []
    skipped: list[str] = []
    for test_file in sorted(TESTS_DIR.rglob("test_*.py")):
        rel = test_file.relative_to(REPO_ROOT)
        module_name = ".".join(rel.with_suffix("").parts)
        try:
            module = importlib.import_module(module_name)
        except Exception as e:
            skipped.append(f"{module_name}: {e}")
            continue
        # Module-level test functions.
        for name, obj in inspect.getmembers(module, inspect.isfunction):
            contract = getattr(obj, "_mutation_contract", None)
            if contract is None:
                continue
            if filter_substr and filter_substr not in name and filter_substr not in str(rel):
                continue
            results.append((str(rel), name, contract))
        # Class-method test functions (TestX classes following pytest convention).
        for cls_name, cls in inspect.getmembers(module, inspect.isclass):
            if cls.__module__ != module_name:
                continue  # Skip imported classes.
            for method_name, method in inspect.getmembers(cls, inspect.isfunction):
                contract = getattr(method, "_mutation_contract", None)
                if contract is None:
                    continue
                node_id = f"{cls_name}::{method_name}"
                if filter_substr and filter_substr not in node_id and filter_substr not in str(rel):
                    continue
                results.append((str(rel), node_id, contract))
    return results, skipped


def _invalidate_pyc(file_path: Path) -> None:
    """Delete cached bytecode for ``file_path`` so subprocess pytest recompiles.

    Python's pyc invalidation compares ``int(source_mtime)`` against the mtime
    stored in the pyc header — second-resolution. When mutations happen within
    the same wall-clock second, the pyc is incorrectly judged fresh and the
    subprocess executes stale (pre-mutation) bytecode. Deleting the pyc forces
    a fresh compile on the next import.
    """
    cache_dir = file_path.parent / "__pycache__"
    if not cache_dir.is_dir():
        return
    stem = file_path.stem
    for pyc in cache_dir.glob(f"{stem}.*.pyc"):
        with contextlib.suppress(OSError):
            pyc.unlink()


def apply_mutation(file_path: Path, line_number: int, revert: str) -> tuple[bool, str, str]:
    """Comment out the matched line. Returns ``(mutated, original_content, message)``."""
    content = file_path.read_text()
    lines = content.split("\n")
    if line_number < 1 or line_number > len(lines):
        return False, content, f"line {line_number} out of range (file has {len(lines)} lines)"
    target = lines[line_number - 1]
    if revert not in target:
        return False, content, f"revert substring not found on line {line_number}: {target!r}"
    stripped = target.lstrip()
    indent = target[: len(target) - len(stripped)]
    lines[line_number - 1] = f"{indent}pass  # MUTATED: {stripped}"
    file_path.write_text("\n".join(lines))
    _invalidate_pyc(file_path)
    return True, content, ""


def restore(file_path: Path, original_content: str) -> None:
    file_path.write_text(original_content)
    _invalidate_pyc(file_path)


_SUBPROCESS_TIMEOUT_SEC = 60


def run_test(test_path: str, test_name: str) -> tuple[bool, int, str]:
    """Return ``(test_failed, exit_code, message)``. ``test_failed=True`` means mutation caught.

    A timeout is treated as test_failed=True with a marker message — a
    mutation that hangs the test IS catching the mutation (the original
    code completed; the mutated code didn't). Without the timeout a hung
    test would freeze ``make mutation-check`` indefinitely.
    """
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        f"{test_path}::{test_name}",
        "-x",
        "--no-header",
        "-q",
        "--tb=no",
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            check=False,
            timeout=_SUBPROCESS_TIMEOUT_SEC,
        )
    except subprocess.TimeoutExpired:
        return True, -1, f"timeout (>{_SUBPROCESS_TIMEOUT_SEC}s)"
    return proc.returncode != 0, proc.returncode, ""


def verify_one(test_path: str, test_name: str, contract: Any) -> tuple[str, bool, str]:
    """Verify a single contract. Returns ``(test_name, ok, message)``."""
    prod_file = REPO_ROOT / contract.file
    if not prod_file.exists():
        return test_name, False, f"production file missing: {contract.file}"
    mutated, original, msg = apply_mutation(prod_file, contract.line, contract.revert)
    if not mutated:
        return test_name, False, msg
    try:
        test_failed, exit_code, run_msg = run_test(test_path, test_name)
    finally:
        restore(prod_file, original)
    if not test_failed:
        return test_name, False, (
            f"contract not enforced: test passed under mutation at "
            f"{contract.file}:{contract.line} (pytest exit={exit_code})"
        )
    return test_name, True, run_msg


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--filter",
        help="Only check contracts whose test name or file path contains this substring",
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=1,
        help="Number of parallel verifications (default: 1 — serial). Within a "
        "production file, contracts are always serialized.",
    )
    args = parser.parse_args()

    marked, skipped = discover_marked_tests(args.filter)

    if skipped:
        print(f"FAILED: {len(skipped)} test module(s) failed to import:", file=sys.stderr)
        for entry in skipped:
            print(f"  ✗ {entry}", file=sys.stderr)
        print(
            "Markers in failed-to-import modules are invisible to the verifier — "
            "fix the import error before claiming verification.",
            file=sys.stderr,
        )
        return 1

    if not marked:
        print("No @mutation_contract markers found.")
        return 0

    print(f"Verifying {len(marked)} mutation contracts...")
    failures: list[tuple[str, str]] = []

    if args.jobs <= 1:
        for test_path, test_name, contract in marked:
            name, ok, msg = verify_one(test_path, test_name, contract)
            if ok:
                print(f"  ✓ {name}")
            else:
                print(f"  ✗ {name}: {msg}", file=sys.stderr)
                failures.append((name, msg))
    else:
        # Group contracts by production file so a parallel worker never
        # mutates a file two contracts share. Each file's group runs serially;
        # files run in parallel.
        by_file: dict[str, list[tuple[str, str, Any]]] = defaultdict(list)
        for test_path, test_name, contract in marked:
            by_file[contract.file].append((test_path, test_name, contract))

        def _verify_group(group: list[tuple[str, str, Any]]) -> list[tuple[str, bool, str]]:
            return [verify_one(*t) for t in group]

        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            future_to_file = {pool.submit(_verify_group, group): file for file, group in by_file.items()}
            for fut in as_completed(future_to_file):
                for name, ok, msg in fut.result():
                    if ok:
                        print(f"  ✓ {name}")
                    else:
                        print(f"  ✗ {name}: {msg}", file=sys.stderr)
                        failures.append((name, msg))

    if failures:
        print(f"\n{len(failures)} of {len(marked)} contracts FAILED:", file=sys.stderr)
        for name, reason in failures:
            print(f"  ✗ {name}: {reason}", file=sys.stderr)
        return 1
    print(f"\nAll {len(marked)} contracts verified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
