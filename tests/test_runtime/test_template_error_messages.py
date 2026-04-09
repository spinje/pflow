"""Snapshot-style tests for the rewritten template error messages."""

from pflow.core.diagnostic import format_diagnostic
from pflow.runtime.engine.template_errors import build_template_error_diagnostic
from pflow.runtime.node_state import FAILURE_CATEGORY_SHELL, mark_node_failed


def _shared_with_failed_primary():
    shared = {
        "primary": {
            "stdout": "",
            "stderr": "",
            "exit_code": 1,
            "command": "exit 1",
            "error": "Command failed with exit code 1",
        },
        "fallback": {"stdout": "fallback-content"},
        "__execution__": {
            "completed_nodes": ["fallback"],
            "node_actions": {"fallback": "default"},
            "node_hashes": {},
            "failed_node": None,
            "node_visit_counts": {},
        },
    }
    mark_node_failed(
        shared,
        "primary",
        category=FAILURE_CATEGORY_SHELL,
        error="Command failed with exit code 1",
    )
    return shared


class TestCase1NonCoalesceFailedRef:
    def test_diagnostic_has_failed_status_reference(self):
        shared = _shared_with_failed_primary()
        diag = build_template_error_diagnostic(
            "content",
            "${primary.stdout}",
            shared,
            node_id=None,
        )
        refs = diag.context["unresolved_references"]
        assert len(refs) == 1
        assert refs[0]["status"] == "failed"
        assert refs[0]["root"] == "primary"
        assert refs[0]["failure"]["exit_code"] == 1

    def test_rendered_includes_failed_label(self):
        shared = _shared_with_failed_primary()
        diag = build_template_error_diagnostic("content", "${primary.stdout}", shared)
        rendered = format_diagnostic(diag)
        assert "FAILED" in rendered
        assert "primary" in rendered
        assert "Exit code: 1" in rendered

    # NOTE: ``test_rendered_suggests_coalesce_fix`` used to live here with a
    # ``"??" in rendered`` assertion. Deleted as redundant —
    # ``TestWarning7PeerSuggestions::test_rendered_substitutes_actual_peer_in_fix``
    # is a strict superset: it uses the same fixture, the same template, and
    # the same render path, and asserts the exact paste-able coalesce string
    # ``${primary.stdout ?? fallback.stdout}``. Any mutation that breaks the
    # weak ``"??" in rendered`` assertion would also break the strong test.


class TestCase2AllCoalesceOperandsFailed:
    def test_diagnostic_marks_both_as_failed(self):
        shared = _shared_with_failed_primary()
        mark_node_failed(
            shared,
            "fallback",
            category=FAILURE_CATEGORY_SHELL,
            error="curl: (6) Could not resolve host",
        )
        diag = build_template_error_diagnostic(
            "content",
            "${primary.stdout ?? fallback.stdout}",
            shared,
        )
        refs = diag.context["unresolved_references"]
        assert len(refs) == 2
        assert all(ref["status"] == "failed" for ref in refs)

    def test_rendered_shows_both_failures(self):
        shared = _shared_with_failed_primary()
        mark_node_failed(shared, "fallback", category=FAILURE_CATEGORY_SHELL, error="boom")
        diag = build_template_error_diagnostic(
            "content",
            "${primary.stdout ?? fallback.stdout}",
            shared,
        )
        rendered = format_diagnostic(diag)
        assert "primary" in rendered
        assert "fallback" in rendered


class TestCase3TypoOnFailedNode:
    def test_status_is_failed_with_secondary_typo_hint(self):
        shared = _shared_with_failed_primary()
        diag = build_template_error_diagnostic(
            "content",
            "${primary.stddout}",
            shared,
        )
        refs = diag.context["unresolved_references"]
        assert refs[0]["status"] == "failed"
        assert refs[0]["secondary_hint"] == "primary.stdout"

    def test_rendered_shows_both_failure_and_typo_hint(self):
        shared = _shared_with_failed_primary()
        diag = build_template_error_diagnostic(
            "content",
            "${primary.stddout}",
            shared,
        )
        rendered = format_diagnostic(diag)
        assert "FAILED" in rendered
        assert "Additional issue" in rendered or "typo" in rendered.lower()
        assert "primary.stdout" in rendered

    def test_fix_template_uses_corrected_field_and_real_peer(self):
        """Regression for post-review Fix #5: typo on a failed node used to produce
        a non-paste-able fix like ``${primary.stddout ?? <peer>.stddout}`` (both the
        typo and the placeholder). Post-fix, the fix uses the corrected path AND a
        real peer node name.
        """
        shared = _shared_with_failed_primary()
        diag = build_template_error_diagnostic(
            "content",
            "${primary.stddout}",
            shared,
        )
        refs = diag.context["unresolved_references"]
        # The classifier found a real peer (fallback has stdout)
        assert "fallback" in refs[0]["peer_suggestions"]
        # And exposes the corrected var for the renderer
        assert refs[0]["corrected_var"] == "primary.stdout"

        rendered = format_diagnostic(diag)
        # Paste-able fix uses the CORRECTED field name, not the typo
        assert "${primary.stdout ?? fallback.stdout}" in rendered
        # Original typo line is still shown (so the agent sees what they wrote)
        assert "${primary.stddout}" in rendered
        # No <peer> placeholder in the fix
        assert "<peer>" not in rendered


class TestCase4SucceededNodeFieldTypo:
    def test_diagnostic_marks_path_error(self):
        shared = {
            "node": {"stdout": "ok", "stderr": "", "exit_code": 0},
            "__execution__": {
                "completed_nodes": ["node"],
                "node_actions": {"node": "default"},
                "node_hashes": {},
                "failed_node": None,
                "node_visit_counts": {},
            },
        }
        diag = build_template_error_diagnostic(
            "content",
            "${node.stddout}",
            shared,
        )
        refs = diag.context["unresolved_references"]
        assert refs[0]["status"] == "path_error"
        assert refs[0]["did_you_mean"] == "node.stdout"

    def test_rendered_shows_did_you_mean(self):
        shared = {
            "node": {"stdout": "ok"},
            "__execution__": {
                "completed_nodes": ["node"],
                "node_actions": {"node": "default"},
                "node_hashes": {},
                "failed_node": None,
                "node_visit_counts": {},
            },
        }
        diag = build_template_error_diagnostic(
            "content",
            "${node.stddout}",
            shared,
        )
        rendered = format_diagnostic(diag)
        assert "did you mean" in rendered.lower() or "Did you mean" in rendered
        assert "node.stdout" in rendered


class TestCase5AbsentNode:
    def test_diagnostic_marks_absent(self):
        shared = {
            "__execution__": {
                "completed_nodes": [],
                "node_actions": {},
                "node_hashes": {},
                "failed_node": None,
                "node_visit_counts": {},
            },
        }
        diag = build_template_error_diagnostic(
            "content",
            "${missing.field}",
            shared,
        )
        refs = diag.context["unresolved_references"]
        assert refs[0]["status"] == "absent"

    def test_rendered_says_did_not_execute(self):
        shared = {
            "__execution__": {
                "completed_nodes": [],
                "node_actions": {},
                "node_hashes": {},
                "failed_node": None,
                "node_visit_counts": {},
            },
        }
        diag = build_template_error_diagnostic("content", "${missing.field}", shared)
        rendered = format_diagnostic(diag)
        assert "did not execute" in rendered


def test_diagnostic_message_is_specific_per_param():
    shared = _shared_with_failed_primary()
    d1 = build_template_error_diagnostic("command", "${primary.stdout}", shared)
    d2 = build_template_error_diagnostic("script", "${primary.stdout}", shared)
    assert d1 != d2


class TestWarning7PeerSuggestions:
    def test_failed_ref_includes_peer_with_same_field(self):
        shared = _shared_with_failed_primary()
        diag = build_template_error_diagnostic("content", "${primary.stdout}", shared)
        refs = diag.context["unresolved_references"]
        assert "fallback" in refs[0]["peer_suggestions"]

    def test_rendered_substitutes_actual_peer_in_fix(self):
        shared = _shared_with_failed_primary()
        diag = build_template_error_diagnostic("content", "${primary.stdout}", shared)
        rendered = format_diagnostic(diag)
        assert "<fallback>" not in rendered
        assert "${primary.stdout ?? fallback.stdout}" in rendered


class TestWarning9CategoryAwareFailureRendering:
    def test_http_failure_renders_status_code_not_shell_fields(self):
        from pflow.runtime.node_state import FAILURE_CATEGORY_API_WARNING

        shared = {
            "api": {
                "status_code": 503,
                "url": "https://api.example.com/data",
                "response": "Service Unavailable",
            },
            "fallback": {"stdout": "fallback-content"},
            "__execution__": {
                "completed_nodes": ["fallback"],
                "node_actions": {"fallback": "default"},
                "node_hashes": {},
                "failed_node": None,
                "node_visit_counts": {},
            },
        }
        mark_node_failed(
            shared,
            "api",
            category=FAILURE_CATEGORY_API_WARNING,
            error="503 Service Unavailable",
        )
        diag = build_template_error_diagnostic("content", "${api.body}", shared)
        rendered = format_diagnostic(diag)
        assert "503" in rendered
        assert "https://api.example.com/data" in rendered
        assert "Exit code" not in rendered


class TestWarning6Case2AllCoalesceFailed:
    def test_summary_block_emitted(self):
        shared = _shared_with_failed_primary()
        mark_node_failed(
            shared,
            "fallback",
            category=FAILURE_CATEGORY_SHELL,
            error="curl: (6) Could not resolve host",
        )
        diag = build_template_error_diagnostic(
            "content",
            "${primary.stdout ?? fallback.stdout}",
            shared,
        )
        rendered = format_diagnostic(diag)
        assert "All coalesce operands failed" in rendered
        assert "?? " in rendered

    def test_mixed_absent_and_failed_coalesce_emits_summary_fix(self):
        """Regression for post-review Fix #4: a coalesce with one absent and one
        failed operand used to produce ZERO fix suggestions (per-ref fixes were
        suppressed via in_coalesce=True, and the summary block gated on ALL refs
        being ``failed``). Post-fix, the summary fires for mixed absent+failed.
        """
        # primary failed via _shared_with_failed_primary helper; never_run is absent
        shared = _shared_with_failed_primary()
        diag = build_template_error_diagnostic(
            "content",
            "${never_run.stdout ?? primary.stdout}",
            shared,
        )
        refs = diag.context["unresolved_references"]
        statuses = {r["var"]: r["status"] for r in refs}
        assert statuses == {"never_run.stdout": "absent", "primary.stdout": "failed"}

        rendered = format_diagnostic(diag)
        # Summary block fires on mixed absent+failed
        assert "All coalesce operands are unavailable" in rendered
        # Paste-able fix with another fallback operand
        assert "Add another fallback" in rendered
        # Investigation line only renders when any ref is failed — primary IS failed here
        assert "Investigate the underlying failures" in rendered

    def test_all_absent_coalesce_summary_omits_investigate_line(self):
        """The 'Investigate the underlying failures' line should only render when
        at least one operand actually failed (not when all are absent)."""
        shared = {
            "__execution__": {
                "completed_nodes": [],
                "node_actions": {},
                "node_hashes": {},
                "failed_node": None,
                "node_visit_counts": {},
            },
        }
        diag = build_template_error_diagnostic(
            "content",
            "${branch_a.stdout ?? branch_b.stdout}",
            shared,
        )
        rendered = format_diagnostic(diag)
        assert "All coalesce operands are unavailable" in rendered
        # All-absent case: no failures to investigate
        assert "Investigate the underlying failures" not in rendered


class TestWarning10OutputResolutionStructured:
    def test_to_diagnostics_uses_template_error_category(self):
        from pflow.core.user_errors import OutputResolutionError

        failures = [
            {
                "output_name": "content",
                "source_expr": "${primary.stdout}",
                "template": "${primary.stdout}",
                "unresolved_references": [
                    {
                        "var": "primary.stdout",
                        "root": "primary",
                        "status": "failed",
                        "in_coalesce": False,
                        "coalesce_expr": None,
                        "failure": {
                            "category": "shell_failure",
                            "error": "boom",
                            "data": {"exit_code": 1, "command": "exit 1"},
                            "exit_code": 1,
                            "command": "exit 1",
                        },
                        "peer_suggestions": [],
                        "secondary_hint": None,
                    }
                ],
                "available_context_keys": ["fallback"],
            }
        ]
        err = OutputResolutionError(failures=failures)

        diags = err.to_diagnostics()
        assert len(diags) == 1
        assert diags[0].context["category"] == "template_error"
        assert "unresolved_references" in diags[0].context
        # New path: no stale node_id annotation, no legacy canned suggestions
        assert diags[0].node_id is None
        assert diags[0].suggestions is None


class TestPermissiveModeWarningRendering:
    """Permissive-mode template errors pass through as WARNING-severity
    Diagnostics (via Fix #6 in ``runner._extract_runtime_warnings``). The
    rendered text output must surface the same structured block as the
    strict-mode ERROR path, otherwise agents in permissive mode silently
    lose per-ref details, peer suggestions, and paste-able fixes.

    Regression guard for the hypothesis confirmed during the third-pass
    review: ``_format_warning_or_info_diagnostic`` used to render warnings as
    one-liners regardless of category, dropping the structured data.
    """

    def test_warning_severity_template_error_renders_structured_block(self):
        from dataclasses import replace

        from pflow.core.diagnostic import Severity

        shared = _shared_with_failed_primary()
        error_diag = build_template_error_diagnostic(
            "command",
            "${primary.stdout}",
            shared,
            node_id="consumer",
        )
        warning_diag = replace(error_diag, severity=Severity.WARNING)

        rendered = format_diagnostic(warning_diag)

        # Must still carry the warning icon and node_id header
        assert "⚠" in rendered
        assert "[consumer]" in rendered

        # Structured block must appear — same content the ERROR path shows
        assert "In parameter 'command':" in rendered
        assert "${primary.stdout}" in rendered
        assert "FAILED" in rendered
        assert "shell command failed" in rendered
        # Paste-able fix uses a real peer, not a placeholder
        assert "${primary.stdout ?? fallback.stdout}" in rendered
        assert "<peer>" not in rendered

    def test_warning_severity_non_template_error_stays_compact(self):
        """Non-template_error warnings still render as compact one-liners —
        the structured block only fires for template_error category, so
        cache lint / API warnings / etc. are unaffected.
        """
        from pflow.core.diagnostic import Diagnostic, Severity

        api_warning = Diagnostic(
            severity=Severity.WARNING,
            message="HTTP 503 Service Unavailable from api.example.com",
            node_id="fetch",
            source="runtime",
            context={"type": "api_warning"},
        )
        rendered = format_diagnostic(api_warning)
        # One-line format, no structured block
        assert "\n" not in rendered
        assert "[fetch]" in rendered
        assert "In parameter" not in rendered
