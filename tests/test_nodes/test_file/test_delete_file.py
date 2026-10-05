"""Test DeleteFileNode functionality."""

import os
import tempfile

import pytest

from pflow.core.exceptions import NodeError
from pflow.nodes.file import DeleteFileNode


class TestDeleteFileNode:
    """Test DeleteFileNode functionality."""

    def test_successful_delete(self):
        """Test successful file deletion with confirmation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "test.txt")
            with open(file_path, "w", encoding="utf-8") as f:
                f.write("Test content")

            node = DeleteFileNode()
            node.set_params({"file_path": file_path})
            shared = {"confirm_delete": True}

            prep_res = node.prep(shared)
            exec_res = node.exec(prep_res)
            action = node.post(shared, prep_res, exec_res)

            assert action == "default"
            assert "deleted" in shared
            # Check semantic meaning rather than exact string
            success_msg = shared["deleted"]
            assert "delet" in success_msg.lower()  # Covers "delete" or "deleted"
            assert file_path in success_msg  # Shows actual file path

            # Verify file no longer exists
            assert not os.path.exists(file_path)

    def test_delete_without_confirmation(self):
        """Test delete fails without confirmation as a safety feature.

        FIX HISTORY:
        - Removed dual testing approach (exception testing + behavior testing)
        - Fixed string assertion fragility with semantic checking
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "test.txt")
            with open(file_path, "w", encoding="utf-8") as f:
                f.write("Test content")

            node = DeleteFileNode()
            node.set_params({"file_path": file_path})
            shared = {"confirm_delete": False}

            # BEHAVIOR: Should fail for safety and preserve file
            action = node.run(shared)

            assert action == "error"
            error_msg = shared["error"]
            # Check semantic meaning rather than exact string
            assert "confirm" in error_msg.lower() or "confirmation" in error_msg.lower()

            # BEHAVIOR: File should remain untouched
            assert os.path.exists(file_path)

    def test_delete_missing_confirmation_flag(self):
        """Test delete fails when confirmation flag is missing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "test.txt")
            with open(file_path, "w", encoding="utf-8") as f:
                f.write("Test content")

            node = DeleteFileNode()
            node.set_params({"file_path": file_path})
            shared = {}  # No confirm_delete

            with pytest.raises(NodeError, match="Missing required 'confirm_delete'"):
                node.prep(shared)

    def test_delete_nonexistent_file(self):
        """Test delete succeeds for non-existent file (idempotent)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "missing.txt")

            node = DeleteFileNode()
            node.set_params({"file_path": file_path})
            shared = {"confirm_delete": True}

            prep_res = node.prep(shared)
            exec_res = node.exec(prep_res)
            action = node.post(shared, prep_res, exec_res)

            assert action == "default"
            assert "deleted" in shared
            # Check semantic meaning - operation succeeded even though file was missing
            success_msg = shared["deleted"]
            assert (
                "not exist" in success_msg.lower()
                or "already" in success_msg.lower()
                or "missing" in success_msg.lower()
            )
            assert file_path in success_msg  # Shows which file was checked

    def test_delete_with_params_safety(self):
        """Test that confirm_delete cannot come from params."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "test.txt")
            with open(file_path, "w", encoding="utf-8") as f:
                f.write("Test content")

            node = DeleteFileNode()
            node.set_params({"file_path": file_path, "confirm_delete": True})
            shared = {}  # Empty shared store

            # Should fail because confirm_delete must be in shared
            with pytest.raises(NodeError, match="Missing required 'confirm_delete'"):
                node.prep(shared)


class TestConfirmDeleteRequiresBooleanTrue:
    """Only the boolean ``True`` authorizes deletion (#617).

    A string-typed workflow input coerces CLI ``confirm_delete=false`` to the
    non-empty string ``"False"``; generic truthiness must never read that — or any
    other non-bool — as permission to delete.
    """

    @pytest.mark.parametrize(
        "value",
        ["False", "false", "True", "true", "no", "", 1, 0, None, {"stdout": "x"}, [True]],
    )
    def test_non_boolean_value_refuses_and_preserves_file(self, tmp_path, value):
        target = tmp_path / "keep.txt"
        target.write_text("KEEP", encoding="utf-8")

        node = DeleteFileNode()
        node.set_params({"file_path": str(target)})
        shared = {"confirm_delete": value}

        action = node.run(shared)

        assert action == "error"
        assert "deleted" not in shared
        assert "boolean" in shared["error"]
        assert "type: boolean" in shared["error"]
        assert target.read_text(encoding="utf-8") == "KEEP"


class TestConfirmDeleteThroughCli:
    """Regression for #617 on the real CLI entry path (input coercion included)."""

    @pytest.mark.parametrize(
        ("input_type", "cli_value", "refusal_hint"),
        [
            ("string", "false", "- type: boolean"),  # the reported bug: coerced to "False", was truthy
            ("string", "true", "- type: boolean"),  # a string is never authorization, even "True"
            ("boolean", "false", "confirm_delete=true"),
            ("boolean", "true", None),  # the one authorizing case
        ],
    )
    def test_only_boolean_true_input_deletes(self, tmp_path, input_type, cli_value, refusal_hint):
        from click.testing import CliRunner

        from pflow.cli.main import main

        target = tmp_path / "target.txt"
        target.write_text("KEEP", encoding="utf-8")
        workflow = tmp_path / "delete.pflow.md"
        workflow.write_text(
            f"""# Delete confirmation

## Inputs

### confirm_delete

Whether to delete the file.

- type: {input_type}
- required: true

## Steps

### act

Delete the disposable file if confirmed.

- type: delete-file
- file_path: {target.as_posix()}
- inputs:
    confirm_delete: ${{confirm_delete}}
""",
            encoding="utf-8",
        )

        result = CliRunner().invoke(main, [str(workflow), f"confirm_delete={cli_value}"])

        if refusal_hint is None:
            assert result.exit_code == 0, result.output
            assert not target.exists()
        else:
            assert result.exit_code == 1, result.output
            assert target.read_text(encoding="utf-8") == "KEEP"
            assert refusal_hint in result.output
