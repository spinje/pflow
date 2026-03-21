"""Tests for external file reference detection and resolution."""

from pathlib import Path
from typing import Any

import pytest
import yaml

from pflow.core.file_resolver import (
    get_base_dir,
    has_file_references,
    is_file_reference,
    resolve_file_references,
)

# ---------------------------------------------------------------------------
# is_file_reference
# ---------------------------------------------------------------------------


class TestIsFileReference:
    """Detection heuristic tests."""

    # --- Should detect as file reference ---

    def test_relative_dot_slash(self) -> None:
        assert is_file_reference("./prompts/foo.md") is True

    def test_relative_dot_dot(self) -> None:
        assert is_file_reference("../prompts/foo.md") is True

    def test_path_with_md_extension(self) -> None:
        assert is_file_reference("prompts/foo.md") is True

    def test_path_with_py_extension(self) -> None:
        assert is_file_reference("scripts/build.py") is True

    def test_path_with_yaml_extension(self) -> None:
        assert is_file_reference("config/batch.yaml") is True

    def test_path_with_yml_extension(self) -> None:
        assert is_file_reference("config/batch.yml") is True

    def test_path_with_json_extension(self) -> None:
        assert is_file_reference("config/schema.json") is True

    def test_path_with_sh_extension(self) -> None:
        assert is_file_reference("scripts/run.sh") is True

    def test_path_with_txt_extension(self) -> None:
        assert is_file_reference("prompts/system.txt") is True

    def test_dot_slash_no_extension(self) -> None:
        """Starts with ./ — always detected regardless of extension."""
        assert is_file_reference("./my-config") is True

    def test_nested_path(self) -> None:
        assert is_file_reference("./prompts/shared/hard-rules.md") is True

    # --- Should NOT detect as file reference ---

    def test_plain_text(self) -> None:
        assert is_file_reference("Tell me about life") is False

    def test_no_recognized_extension(self) -> None:
        assert is_file_reference("path/to/enlightenment") is False

    def test_template_variable(self) -> None:
        assert is_file_reference("${item.prompt}") is False

    def test_template_in_path(self) -> None:
        assert is_file_reference("./prompts/${var}.md") is False

    def test_bare_name(self) -> None:
        assert is_file_reference("just-a-name") is False

    def test_multiline(self) -> None:
        assert is_file_reference("line1\nline2") is False

    def test_empty_string(self) -> None:
        assert is_file_reference("") is False

    def test_non_string_int(self) -> None:
        assert is_file_reference(42) is False

    def test_non_string_dict(self) -> None:
        assert is_file_reference({"key": "val"}) is False

    def test_non_string_none(self) -> None:
        assert is_file_reference(None) is False

    def test_bare_filename_md(self) -> None:
        """No slash and no ./ prefix — not a file reference."""
        assert is_file_reference("foo.md") is False

    def test_bare_filename_py(self) -> None:
        assert is_file_reference("build.py") is False

    def test_url_not_matched(self) -> None:
        """URLs should not be treated as file references."""
        assert is_file_reference("https://example.com/path.md") is False

    def test_command_with_path(self) -> None:
        """Shell commands containing paths are not file references."""
        assert is_file_reference("touch /tmp/file.txt") is False

    def test_path_with_spaces(self) -> None:
        """Paths with spaces (e.g., in commands) are not file references."""
        assert is_file_reference("cat /some/file.md | grep test") is False


# ---------------------------------------------------------------------------
# resolve_file_references
# ---------------------------------------------------------------------------


def _make_ir(nodes: list[dict[str, Any]]) -> dict[str, Any]:
    """Helper to create minimal IR dict."""
    return {"nodes": nodes, "edges": []}


class TestResolveFileReferences:
    """IR transformation tests. All use tmp_path."""

    def test_text_param_resolution(self, tmp_path: Path) -> None:
        """Text file content substituted into prompt param."""
        prompt_dir = tmp_path / "prompts"
        prompt_dir.mkdir()
        (prompt_dir / "system.md").write_text("You are helpful\n${concept.title}")

        ir = _make_ir([{"id": "n1", "type": "llm", "params": {"prompt": "./prompts/system.md"}}])
        resolve_file_references(ir, tmp_path)

        assert ir["nodes"][0]["params"]["prompt"] == "You are helpful\n${concept.title}"
        assert ir["nodes"][0]["_source_files"]["prompt"] == "./prompts/system.md"

    def test_yaml_param_resolution(self, tmp_path: Path) -> None:
        """YAML file content parsed into dict for output_schema param."""
        (tmp_path / "schema.yaml").write_text("type: object\nproperties:\n  name:\n    type: string")

        ir = _make_ir([{"id": "n1", "type": "llm", "params": {"output_schema": "./schema.yaml"}}])
        resolve_file_references(ir, tmp_path)

        result = ir["nodes"][0]["params"]["output_schema"]
        assert isinstance(result, dict)
        assert result["type"] == "object"
        assert ir["nodes"][0]["_source_files"]["output_schema"] == "./schema.yaml"

    def test_batch_string_resolution(self, tmp_path: Path) -> None:
        """Entire batch config loaded from external YAML file."""
        (tmp_path / "batch.yaml").write_text("items:\n  - focus: ai\n    prompt: hello\nparallel: true")

        ir = _make_ir([{"id": "n1", "type": "llm", "batch": "./batch.yaml", "params": {}}])
        resolve_file_references(ir, tmp_path)

        batch = ir["nodes"][0]["batch"]
        assert isinstance(batch, dict)
        assert batch["items"] == [{"focus": "ai", "prompt": "hello"}]
        assert batch["parallel"] is True
        assert ir["nodes"][0]["_source_files"]["batch"] == "./batch.yaml"

    def test_batch_items_resolution(self, tmp_path: Path) -> None:
        """File references inside inline batch items resolved."""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        (prompts_dir / "ai.md").write_text("Check for AI tells")
        (prompts_dir / "cliche.md").write_text("Check for cliches")

        ir = _make_ir([
            {
                "id": "n1",
                "type": "llm",
                "batch": {
                    "items": [
                        {"focus": "ai", "prompt": "./prompts/ai.md"},
                        {"focus": "cliche", "prompt": "./prompts/cliche.md"},
                    ],
                    "parallel": True,
                },
                "params": {"prompt": "${item.prompt}"},
            }
        ])
        resolve_file_references(ir, tmp_path)

        items = ir["nodes"][0]["batch"]["items"]
        assert items[0]["prompt"] == "Check for AI tells"
        assert items[1]["prompt"] == "Check for cliches"
        assert "batch.items[0].prompt" in ir["nodes"][0]["_source_files"]
        assert "batch.items[1].prompt" in ir["nodes"][0]["_source_files"]

    def test_multiple_nodes_resolved(self, tmp_path: Path) -> None:
        """File references in different nodes resolved independently."""
        (tmp_path / "prompt.md").write_text("prompt content")
        (tmp_path / "code.py").write_text("result: str = 'hello'")

        ir = _make_ir([
            {"id": "n1", "type": "llm", "params": {"prompt": "./prompt.md"}},
            {"id": "n2", "type": "code", "params": {"code": "./code.py"}},
        ])
        resolve_file_references(ir, tmp_path)

        assert ir["nodes"][0]["params"]["prompt"] == "prompt content"
        assert ir["nodes"][1]["params"]["code"] == "result: str = 'hello'"

    def test_non_file_params_unchanged(self, tmp_path: Path) -> None:
        """Params that aren't file references stay untouched."""
        ir = _make_ir([{"id": "n1", "type": "llm", "params": {"prompt": "Hello world", "model": "gpt-4"}}])
        resolve_file_references(ir, tmp_path)

        assert ir["nodes"][0]["params"]["prompt"] == "Hello world"
        assert ir["nodes"][0]["params"]["model"] == "gpt-4"
        assert "_source_files" not in ir["nodes"][0]

    def test_template_variables_not_resolved(self, tmp_path: Path) -> None:
        """Template variables like ${item.prompt} are not treated as file refs."""
        ir = _make_ir([{"id": "n1", "type": "llm", "params": {"prompt": "${item.prompt}"}}])
        resolve_file_references(ir, tmp_path)

        assert ir["nodes"][0]["params"]["prompt"] == "${item.prompt}"

    def test_file_not_found_error(self, tmp_path: Path) -> None:
        """Missing file raises FileNotFoundError with helpful message."""
        ir = _make_ir([{"id": "n1", "type": "llm", "params": {"prompt": "./nonexistent.md"}}])

        with pytest.raises(FileNotFoundError, match="node 'n1'"):
            resolve_file_references(ir, tmp_path)

    def test_file_not_found_error_details(self, tmp_path: Path) -> None:
        """Error message includes node ID, param, resolved path, and base dir."""
        ir = _make_ir([{"id": "my-node", "type": "llm", "params": {"prompt": "./missing/prompt.md"}}])

        with pytest.raises(FileNotFoundError) as exc_info:
            resolve_file_references(ir, tmp_path)

        msg = str(exc_info.value)
        assert "my-node" in msg
        assert "prompt" in msg
        assert "Resolved to:" in msg
        assert "Relative to:" in msg

    def test_yaml_parse_error(self, tmp_path: Path) -> None:
        """Invalid YAML in batch file raises error."""
        (tmp_path / "bad.yaml").write_text("items:\n  - [broken")

        ir = _make_ir([{"id": "n1", "type": "llm", "batch": "./bad.yaml", "params": {}}])

        with pytest.raises(yaml.YAMLError):
            resolve_file_references(ir, tmp_path)

    def test_relative_path_resolution(self, tmp_path: Path) -> None:
        """Paths resolve relative to base_dir, not CWD."""
        sub = tmp_path / "sub" / "prompts"
        sub.mkdir(parents=True)
        (sub / "foo.md").write_text("from sub")

        ir = _make_ir([{"id": "n1", "type": "llm", "params": {"prompt": "./prompts/foo.md"}}])
        resolve_file_references(ir, tmp_path / "sub")

        assert ir["nodes"][0]["params"]["prompt"] == "from sub"

    def test_provenance_tracking(self, tmp_path: Path) -> None:
        """_source_files records the original relative path."""
        (tmp_path / "p.md").write_text("content")

        ir = _make_ir([{"id": "n1", "type": "llm", "params": {"prompt": "./p.md"}}])
        resolve_file_references(ir, tmp_path)

        assert ir["nodes"][0]["_source_files"] == {"prompt": "./p.md"}

    def test_idempotent(self, tmp_path: Path) -> None:
        """Running resolution twice doesn't break anything or corrupt provenance."""
        (tmp_path / "p.md").write_text("content")

        ir = _make_ir([{"id": "n1", "type": "llm", "params": {"prompt": "./p.md"}}])
        resolve_file_references(ir, tmp_path)

        assert ir["nodes"][0]["params"]["prompt"] == "content"
        assert ir["nodes"][0]["_source_files"] == {"prompt": "./p.md"}

        # Second pass — content doesn't match heuristic, provenance unchanged
        resolve_file_references(ir, tmp_path)

        assert ir["nodes"][0]["params"]["prompt"] == "content"
        assert ir["nodes"][0]["_source_files"] == {"prompt": "./p.md"}

    def test_path_traversal_blocked(self, tmp_path: Path) -> None:
        """Path traversal attempts are blocked."""
        ir = _make_ir([{"id": "n1", "type": "llm", "params": {"prompt": "../../../etc/passwd"}}])

        with pytest.raises(FileNotFoundError, match="escapes workflow directory"):
            resolve_file_references(ir, tmp_path)

    def test_path_traversal_dot_dot_in_middle(self, tmp_path: Path) -> None:
        """Paths that resolve outside base_dir via .. segments are blocked."""
        # Create a file outside the base_dir
        parent = tmp_path / "project"
        parent.mkdir()
        (tmp_path / "secret.md").write_text("secret")

        ir = _make_ir([{"id": "n1", "type": "llm", "params": {"prompt": "../secret.md"}}])

        with pytest.raises(FileNotFoundError, match="escapes workflow directory"):
            resolve_file_references(ir, parent)

    def test_empty_ir(self, tmp_path: Path) -> None:
        """Empty nodes list doesn't error."""
        ir: dict[str, Any] = {"nodes": []}
        resolve_file_references(ir, tmp_path)

    def test_node_without_params(self, tmp_path: Path) -> None:
        """Node with no params key doesn't error."""
        ir = _make_ir([{"id": "n1", "type": "shell"}])
        resolve_file_references(ir, tmp_path)

    def test_mixed_file_and_inline_params(self, tmp_path: Path) -> None:
        """Some params are file refs, others are inline — both handled correctly."""
        (tmp_path / "system.md").write_text("Be helpful")

        ir = _make_ir([
            {
                "id": "n1",
                "type": "llm",
                "params": {
                    "prompt": "./system.md",
                    "model": "gpt-4",
                    "temperature": 0.7,
                },
            }
        ])
        resolve_file_references(ir, tmp_path)

        assert ir["nodes"][0]["params"]["prompt"] == "Be helpful"
        assert ir["nodes"][0]["params"]["model"] == "gpt-4"
        assert ir["nodes"][0]["params"]["temperature"] == 0.7

    def test_batch_items_mixed(self, tmp_path: Path) -> None:
        """Only file-reference values in batch items are resolved."""
        (tmp_path / "p.md").write_text("file content")

        ir = _make_ir([
            {
                "id": "n1",
                "type": "llm",
                "batch": {
                    "items": [{"focus": "test", "prompt": "./p.md", "weight": 1.0}],
                },
                "params": {},
            }
        ])
        resolve_file_references(ir, tmp_path)

        item = ir["nodes"][0]["batch"]["items"][0]
        assert item["prompt"] == "file content"
        assert item["focus"] == "test"
        assert item["weight"] == 1.0

    def test_batch_items_non_resolvable_param_untouched(self, tmp_path: Path) -> None:
        """Non-resolvable params in batch items are not resolved even if they look like paths."""
        (tmp_path / "data.md").write_text("should not be inlined")

        ir = _make_ir([
            {
                "id": "n1",
                "type": "llm",
                "batch": {
                    "items": [{"file_path": "./data.md", "prompt": "inline prompt"}],
                },
                "params": {},
            }
        ])
        resolve_file_references(ir, tmp_path)

        item = ir["nodes"][0]["batch"]["items"][0]
        assert item["file_path"] == "./data.md"  # NOT resolved — not in FILE_RESOLVABLE_PARAMS
        assert item["prompt"] == "inline prompt"

    def test_non_resolvable_param_untouched(self, tmp_path: Path) -> None:
        """Params not in FILE_RESOLVABLE_PARAMS are never resolved."""
        (tmp_path / "target.md").write_text("should not be inlined")

        ir = _make_ir([
            {
                "id": "n1",
                "type": "write-file",
                "params": {
                    "file_path": "./target.md",
                    "content": "some content",
                },
            }
        ])
        resolve_file_references(ir, tmp_path)

        assert ir["nodes"][0]["params"]["file_path"] == "./target.md"


# ---------------------------------------------------------------------------
# has_file_references
# ---------------------------------------------------------------------------


class TestHasFileReferences:
    """Scan IR for file references without resolving."""

    def test_detects_prompt_file_ref(self) -> None:
        ir = _make_ir([{"id": "n1", "type": "llm", "params": {"prompt": "./foo.md"}}])
        assert has_file_references(ir) == ["./foo.md"]

    def test_detects_batch_string_file_ref(self) -> None:
        ir = _make_ir([{"id": "n1", "type": "llm", "batch": "./config.yaml", "params": {}}])
        assert has_file_references(ir) == ["./config.yaml"]

    def test_detects_batch_item_file_ref(self) -> None:
        ir = _make_ir([
            {
                "id": "n1",
                "type": "llm",
                "batch": {"items": [{"prompt": "./p.md"}]},
                "params": {},
            }
        ])
        assert has_file_references(ir) == ["./p.md"]

    def test_no_file_refs(self) -> None:
        ir = _make_ir([{"id": "n1", "type": "llm", "params": {"prompt": "Hello world"}}])
        assert has_file_references(ir) == []

    def test_ignores_non_resolvable_params(self) -> None:
        ir = _make_ir([{"id": "n1", "type": "write-file", "params": {"file_path": "./foo.md"}}])
        assert has_file_references(ir) == []

    def test_multiple_refs(self) -> None:
        ir = _make_ir([
            {"id": "n1", "type": "llm", "params": {"prompt": "./a.md"}},
            {"id": "n2", "type": "shell", "params": {"command": "./run.sh"}},
        ])
        result = has_file_references(ir)
        assert "./a.md" in result
        assert "./run.sh" in result

    def test_empty_ir(self) -> None:
        assert has_file_references({"nodes": []}) == []


# ---------------------------------------------------------------------------
# get_base_dir
# ---------------------------------------------------------------------------


class TestGetBaseDir:
    def test_with_workflow_file(self) -> None:
        result = get_base_dir({"_pflow_workflow_file": "/home/user/project/workflow.pflow.md"})
        assert result == Path("/home/user/project")

    def test_without_workflow_file(self) -> None:
        result = get_base_dir({})
        assert result == Path.cwd()

    def test_with_none_value(self) -> None:
        result = get_base_dir({"_pflow_workflow_file": None})
        assert result == Path.cwd()
