"""Tests for cache lint validation warning on input-less shell nodes."""

from pflow.core.workflow.validator import WorkflowValidator


class TestCacheLintWarning:
    """Test that input-less shell nodes generate a cache warning."""

    def test_inputless_shell_node_warns(self):
        """Shell node with no templates should produce a warning."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "get-branch",
                    "type": "shell",
                    "params": {"command": "git branch --show-current"},
                    "purpose": "Get current git branch",
                }
            ],
        }
        errors, warnings = WorkflowValidator.validate(ir, skip_node_types=True)
        assert len(errors) == 0
        assert len(warnings) == 1
        assert warnings[0].node_id == "get-branch"
        assert "cache: false" in warnings[0].message
        assert warnings[0].template is None

    def test_shell_node_with_templates_no_warning(self):
        """Shell node with template inputs should NOT warn."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "upstream",
                    "type": "shell",
                    "params": {"command": "echo hello"},
                    "purpose": "Produce some output to use downstream",
                },
                {
                    "id": "process",
                    "type": "shell",
                    "params": {"command": "echo ${upstream.stdout}"},
                    "purpose": "Process upstream output with template",
                },
            ],
            "edges": [{"from": "upstream", "to": "process"}],
        }
        errors, warnings = WorkflowValidator.validate(ir, skip_node_types=True)
        # upstream should warn (no templates), process should NOT (has template)
        cache_warnings = [w for w in warnings if "cache: false" in w.message]
        assert len(cache_warnings) == 1
        assert cache_warnings[0].node_id == "upstream"

    def test_shell_node_with_cache_false_no_warning(self):
        """Shell node with explicit cache: false should NOT warn."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "get-branch",
                    "type": "shell",
                    "cache": False,
                    "params": {"command": "git branch --show-current"},
                    "purpose": "Get current git branch",
                }
            ],
        }
        errors, warnings = WorkflowValidator.validate(ir, skip_node_types=True)
        cache_warnings = [w for w in warnings if "cache: false" in w.message]
        assert len(cache_warnings) == 0

    def test_shell_node_with_cache_true_no_warning(self):
        """Shell node with explicit cache: true should NOT warn (author made a decision)."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "static-cmd",
                    "type": "shell",
                    "cache": True,
                    "params": {"command": "echo hello"},
                    "purpose": "Deterministic command, author explicitly wants caching",
                }
            ],
        }
        errors, warnings = WorkflowValidator.validate(ir, skip_node_types=True)
        cache_warnings = [w for w in warnings if "cache: false" in w.message]
        assert len(cache_warnings) == 0

    def test_non_shell_node_no_warning(self):
        """Non-shell nodes should NOT get the cache lint warning."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "analyze",
                    "type": "llm",
                    "params": {"prompt": "Static prompt", "model": "test"},
                    "purpose": "LLM with static prompt (fine to cache)",
                }
            ],
        }
        errors, warnings = WorkflowValidator.validate(ir, skip_node_types=True)
        cache_warnings = [w for w in warnings if "cache: false" in w.message]
        assert len(cache_warnings) == 0

    def test_bash_parameter_expansion_still_warns(self):
        """Bash syntax like ${var:-default} is NOT a pflow template — should warn."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "bash-node",
                    "type": "shell",
                    "params": {"command": "echo ${HOME:-/tmp}"},
                    "purpose": "Uses bash default value syntax, not pflow template",
                }
            ],
        }
        errors, warnings = WorkflowValidator.validate(ir, skip_node_types=True)
        cache_warnings = [w for w in warnings if "cache: false" in w.message]
        assert len(cache_warnings) == 1
        assert cache_warnings[0].node_id == "bash-node"

    def test_bash_array_expansion_still_warns(self):
        """Bash array syntax like ${array[@]} is NOT a pflow template — should warn."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "array-node",
                    "type": "shell",
                    "params": {"command": 'for f in ${files[@]}; do echo "$f"; done'},
                    "purpose": "Uses bash array expansion, not pflow template",
                }
            ],
        }
        errors, warnings = WorkflowValidator.validate(ir, skip_node_types=True)
        cache_warnings = [w for w in warnings if "cache: false" in w.message]
        assert len(cache_warnings) == 1

    def test_escaped_template_still_warns(self):
        """Escaped $${var} is NOT a pflow template — should warn."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "escaped-node",
                    "type": "shell",
                    "params": {"command": "echo $${NOT_A_VAR}"},
                    "purpose": "Uses escaped template syntax, not a real input",
                }
            ],
        }
        errors, warnings = WorkflowValidator.validate(ir, skip_node_types=True)
        cache_warnings = [w for w in warnings if "cache: false" in w.message]
        assert len(cache_warnings) == 1

    def test_batch_shell_node_no_warning(self):
        """Shell node with batch config should NOT warn (batch items change keys)."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "process",
                    "type": "shell",
                    "params": {"command": "echo static"},
                    "purpose": "Batch processes items with static command template",
                    "batch": {"items": [1, 2, 3], "as": "item"},
                }
            ],
        }
        errors, warnings = WorkflowValidator.validate(ir, skip_node_types=True)
        cache_warnings = [w for w in warnings if "cache: false" in w.message]
        assert len(cache_warnings) == 0
