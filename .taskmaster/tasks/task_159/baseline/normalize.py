#!/usr/bin/env python3
"""Normalize pflow CLI output for byte-stable baseline comparison.

Reads stdin, applies redaction rules in fixed order, writes stdout.
Rules are deliberately conservative: warning IDs, severity levels, JSON keys,
section ordering, and confidence labels are NEVER normalized.

Used by both regenerate.sh (writes expected-*.txt) and verify.sh (compares
re-run output to committed expected-*.txt).
"""

from __future__ import annotations

import os
import re
import sys


def _abspath_pattern(env_var: str) -> str | None:
    val = os.environ.get(env_var)
    if not val:
        return None
    return re.escape(val)


def _strip_litellm_cost_map_warnings(text: str) -> str:
    """Remove dependency-network noise from baseline stderr.

    LiteLLM may try to refresh its remote model-cost map before falling back to
    the bundled local copy. Network availability and the emitted timestamp vary
    by sandbox run, while pflow's rendered analysis is unchanged.
    """
    marker = "LiteLLM: Failed to fetch remote model cost map"
    return "\n".join(line for line in text.split("\n") if marker not in line)


def apply_rules(text: str) -> str:
    home = _abspath_pattern("BASELINE_HOME")
    case_dir = _abspath_pattern("BASELINE_CASE_DIR")
    repo_root = _abspath_pattern("BASELINE_REPO_ROOT")

    if case_dir:
        text = re.sub(case_dir, "<BASELINE_CASE_DIR>", text)
    if home:
        text = re.sub(home, "<BASELINE_HOME>", text)
    if repo_root:
        text = re.sub(repo_root, "<REPO_ROOT>", text)

    text = re.sub(r"/Users/[^/\s\"']+", "<HOME>", text)
    text = re.sub(r"/private/var/folders/[^\s\"']+", "<TMPDIR>", text)
    text = re.sub(r"/var/folders/[^\s\"']+", "<TMPDIR>", text)
    # ruff S108: literal "/tmp/" used as a redaction REGEX, not a tmp-file
    # write target. Suppression is correct here.
    text = re.sub(r"/tmp/[^\s\"']+", "<TMP>", text)  # noqa: S108

    text = re.sub(r"\d{8}-\d{6}", "<TIMESTAMP>", text)
    text = re.sub(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?",
        "<TIMESTAMP>",
        text,
    )
    text = re.sub(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", "<TIMESTAMP>", text)

    text = re.sub(
        r"(workflow-trace-[A-Za-z0-9_.-]+?-)[a-f0-9]{8,16}(\.json)",
        r"\1<HASH>\2",
        text,
    )
    text = re.sub(r"\bir-hash:[a-f0-9]{32}", "ir-hash:<HASH:32>", text)
    text = re.sub(r"\b[a-f0-9]{32}\b", "<HASH:32>", text)
    text = re.sub(r"\b[a-f0-9]{16}\b", "<HASH:16>", text)
    text = re.sub(r"\b[a-f0-9]{12}\b", "<HASH:12>", text)

    text = re.sub(r"\bpython[\s/]+\d+\.\d+\.\d+", "python <VERSION>", text)
    text = re.sub(r"pflow\s+version\s+\d+\.\d+\.\d+", "pflow version <VERSION>", text)
    text = re.sub(r"\bv?\d+\.\d+\.\d+\b(?=\s|$|\))", "<VERSION>", text)

    text = re.sub(
        r'("cache_age_sec"\s*:\s*)\d+',
        r'\1"<AGE>"',
        text,
    )
    text = re.sub(
        r'("created"\s*:\s*)\d{10,}',
        r'\1"<EPOCH>"',
        text,
    )
    text = re.sub(
        r'("started_at"\s*:\s*)"[^"]+"',
        r'\1"<TIMESTAMP>"',
        text,
    )
    text = re.sub(
        r'("ended_at"\s*:\s*)"[^"]+"',
        r'\1"<TIMESTAMP>"',
        text,
    )
    text = re.sub(
        r'("duration_ms"\s*:\s*)\d+',
        r"\1<DURATION>",
        text,
    )

    text = re.sub(
        r"\(partial — \d+ of \d+ nodes use unpriced models\)",
        "(partial — <N> of <M> nodes use unpriced models)",
        text,
    )
    text = _strip_litellm_cost_map_warnings(text)

    # Strip per-line trailing whitespace so pre-commit's
    # trailing-whitespace hook (run by `make check`) doesn't fight us
    # on table rows that pflow pads with spaces for column alignment.
    text = "\n".join(line.rstrip() for line in text.split("\n"))

    return text


def main() -> int:
    raw = sys.stdin.read()
    sys.stdout.write(apply_rules(raw))
    return 0


if __name__ == "__main__":
    sys.exit(main())
