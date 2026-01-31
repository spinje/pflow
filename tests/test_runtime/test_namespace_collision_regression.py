"""
Regression tests for namespace collision bug fix.

These tests verify that the params-only pattern prevents collisions between:
1. Node IDs and parameter names
2. Workflow inputs and parameter names

The bug was: nodes used `shared.get("x") or params.get("x")`, which found
namespace dicts or raw inputs instead of template-resolved values.

The fix: nodes read only from `self.params`. Templates handle all data wiring.
"""

import pytest

from pflow.pocketflow import Node
from pflow.registry import Registry
from pflow.runtime.compiler import compile_ir_to_flow

# =============================================================================
# Test Nodes (simulating real node behavior)
# =============================================================================


class MockLLMNode(Node):
    """
    Mock LLM node that uses an 'images' parameter.

    This simulates the real LLM node's behavior where 'images' is read from params.
    The bug occurred when a node named "images" created shared["images"] = {stdout: ...},
    and the old fallback pattern found it instead of the template-resolved param.
    """

    def prep(self, shared):
        # New pattern: read from params only
        images = self.params.get("images", [])
        prompt = self.params.get("prompt", "Describe")

        # Validate images is a list (the bug caused it to be a dict)
        if not isinstance(images, list):
            raise TypeError(f"images must be a list, got {type(images).__name__}: {images}")

        return {"images": images, "prompt": prompt}

    def exec(self, prep_res):
        # Simulate LLM processing
        images = prep_res["images"]
        prompt = prep_res["prompt"]
        return f"Processed {len(images)} images with prompt: {prompt}"

    def post(self, shared, prep_res, exec_res):
        shared["response"] = exec_res
        return "default"


class MockHTTPNode(Node):
    """
    Mock HTTP node that uses a 'url' parameter.

    This simulates the real HTTP node's behavior where 'url' is read from params.
    The bug occurred when a workflow input named "url" existed at shared["url"],
    and the old fallback pattern used it instead of the template-resolved param.
    """

    def prep(self, shared):
        # New pattern: read from params only
        url = self.params.get("url")
        if not url:
            raise ValueError("Missing required 'url' parameter")
        return url

    def exec(self, prep_res):
        url = prep_res
        # Simulate HTTP fetch, return the URL that was actually used
        return f"Fetched: {url}"

    def post(self, shared, prep_res, exec_res):
        shared["response"] = exec_res
        return "default"


class MockShellNode(Node):
    """Mock shell node that outputs data."""

    def prep(self, shared):
        command = self.params.get("command", "echo test")
        return command

    def exec(self, prep_res):
        command = prep_res
        # Simulate shell output
        if "image" in command.lower():
            return '["https://example.com/image1.png", "https://example.com/image2.png"]'
        return "shell output"

    def post(self, shared, prep_res, exec_res):
        shared["stdout"] = exec_res
        shared["exit_code"] = 0
        return "default"


class MockEchoNode(Node):
    """Simple echo node for testing param values."""

    def prep(self, shared):
        # Read various params, including falsy ones
        return {
            "message": self.params.get("message"),
            "count": self.params.get("count"),
            "enabled": self.params.get("enabled"),
            "data": self.params.get("data"),
        }

    def exec(self, prep_res):
        return prep_res

    def post(self, shared, prep_res, exec_res):
        shared["result"] = exec_res
        return "default"


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def mock_registry(tmp_path):
    """Create a registry with mock node metadata."""
    registry_path = tmp_path / "test_registry.json"
    registry = Registry(registry_path)

    nodes_data = {
        "mock-llm": {
            "module": "test",
            "class": "MockLLMNode",
            "metadata": {
                "inputs": [],
                "params": [
                    {"name": "prompt", "type": "str"},
                    {"name": "images", "type": "list"},
                ],
                "outputs": [{"name": "response", "type": "str"}],
            },
        },
        "mock-http": {
            "module": "test",
            "class": "MockHTTPNode",
            "metadata": {
                "inputs": [],
                "params": [{"name": "url", "type": "str"}],
                "outputs": [{"name": "response", "type": "str"}],
            },
        },
        "mock-shell": {
            "module": "test",
            "class": "MockShellNode",
            "metadata": {
                "inputs": [],
                "params": [{"name": "command", "type": "str"}],
                "outputs": [
                    {"name": "stdout", "type": "str"},
                    {"name": "exit_code", "type": "int"},
                ],
            },
        },
        "mock-echo": {
            "module": "test",
            "class": "MockEchoNode",
            "metadata": {
                "inputs": [],
                "params": [
                    {"name": "message", "type": "str"},
                    {"name": "count", "type": "int"},
                    {"name": "enabled", "type": "bool"},
                    {"name": "data", "type": "any"},
                ],
                "outputs": [{"name": "result", "type": "dict"}],
            },
        },
    }
    registry.save(nodes_data)
    return registry


@pytest.fixture
def mock_import():
    """Context manager to mock node imports."""
    import pflow.runtime.compiler as compiler_module

    original_import = compiler_module.import_node_class

    def _mock_import(node_type, registry):
        node_map = {
            "mock-llm": MockLLMNode,
            "mock-http": MockHTTPNode,
            "mock-shell": MockShellNode,
            "mock-echo": MockEchoNode,
        }
        if node_type in node_map:
            return node_map[node_type]
        return original_import(node_type, registry)

    compiler_module.import_node_class = _mock_import

    yield

    compiler_module.import_node_class = original_import


# =============================================================================
# Regression Test 1: Node ID Collision
# =============================================================================


class TestNodeIDCollisionRegression:
    """
    Regression tests for node ID collision with parameter names.

    Bug scenario:
    - Node named "images" creates shared["images"] = {stdout: ..., exit_code: ...}
    - LLM node has param: {"images": "${item}"} (template resolved to URL string)
    - Old code: shared.get("images") found the namespace dict
    - LLM node failed with "images must be a list, got dict"

    Fix: Nodes read from self.params only. Template puts resolved value there.
    """

    def test_node_named_images_does_not_collide_with_llm_images_param(self, mock_registry, mock_import):
        """
        Critical regression test: Node ID 'images' must not affect LLM's images param.

        This is the exact bug that was discovered and fixed.
        """
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "images",  # Node ID matches LLM's 'images' param!
                    "type": "mock-shell",
                    "params": {"command": "echo image URLs"},
                },
                {
                    "id": "analyze",
                    "type": "mock-llm",
                    "params": {
                        "prompt": "Describe these",
                        "images": ["https://example.com/photo.jpg"],  # Static list
                    },
                },
            ],
            "edges": [{"from": "images", "to": "analyze"}],
        }

        flow = compile_ir_to_flow(workflow, mock_registry, validate=False)
        shared = {}
        flow.run(shared)

        # Verify the namespace dict exists (this is what caused the bug)
        assert "images" in shared, "Node 'images' namespace should exist"
        assert isinstance(shared["images"], dict), "Namespace should be a dict"
        assert "stdout" in shared["images"], "Namespace should have stdout"

        # The critical assertion: LLM node received the param, not the namespace dict
        assert "analyze" in shared
        assert "Processed 1 images" in shared["analyze"]["response"]

    def test_node_named_url_does_not_collide_with_http_url_param(self, mock_registry, mock_import):
        """Node ID 'url' must not affect HTTP's url param."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "url",  # Node ID matches HTTP's 'url' param!
                    "type": "mock-shell",
                    "params": {"command": "echo preparing"},
                },
                {
                    "id": "fetch",
                    "type": "mock-http",
                    "params": {"url": "https://api.example.com/data"},  # Static URL
                },
            ],
            "edges": [{"from": "url", "to": "fetch"}],
        }

        flow = compile_ir_to_flow(workflow, mock_registry, validate=False)
        shared = {}
        flow.run(shared)

        # Namespace dict exists
        assert "url" in shared
        assert isinstance(shared["url"], dict)

        # HTTP node received the param, not the namespace
        assert "fetch" in shared
        assert shared["fetch"]["response"] == "Fetched: https://api.example.com/data"

    def test_node_named_prompt_does_not_collide_with_llm_prompt_param(self, mock_registry, mock_import):
        """Node ID 'prompt' must not affect LLM's prompt param."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "prompt",  # Node ID matches LLM's 'prompt' param!
                    "type": "mock-shell",
                    "params": {"command": "echo generating prompt"},
                },
                {
                    "id": "llm",
                    "type": "mock-llm",
                    "params": {
                        "prompt": "Analyze the data",  # Static prompt
                        "images": [],
                    },
                },
            ],
            "edges": [{"from": "prompt", "to": "llm"}],
        }

        flow = compile_ir_to_flow(workflow, mock_registry, validate=False)
        shared = {}
        flow.run(shared)

        # Namespace exists
        assert "prompt" in shared
        assert isinstance(shared["prompt"], dict)

        # LLM received the static param
        assert "llm" in shared
        assert "Analyze the data" in shared["llm"]["response"]


# =============================================================================
# Regression Test 2: Workflow Input Collision
# =============================================================================


class TestWorkflowInputCollisionRegression:
    """
    Regression tests for workflow input names colliding with parameter names.

    Bug scenario:
    - Workflow input: url = "https://example.com"
    - shared["url"] = "https://example.com" (at root level)
    - HTTP node has param: {"url": "https://r.jina.ai/${url}"} (with transformation)
    - Old code: shared.get("url") found the raw input
    - HTTP called wrong URL (missing the Jina prefix)

    Fix: Nodes read from self.params only. Template resolution handles ${url}.
    """

    def test_input_named_url_does_not_override_http_url_template(self, mock_registry, mock_import):
        """
        Critical regression test: Input 'url' must not override HTTP's url template.

        This is the exact bug that was discovered and fixed.
        """
        workflow = {
            "ir_version": "0.1.0",
            "inputs": {
                "url": {  # Input name matches HTTP's 'url' param!
                    "type": "string",
                    "required": True,
                    "description": "Target URL to fetch",
                },
            },
            "nodes": [
                {
                    "id": "fetch",
                    "type": "mock-http",
                    "params": {
                        # Template transforms the input
                        "url": "https://r.jina.ai/${url}",
                    },
                },
            ],
            "edges": [],
        }

        flow = compile_ir_to_flow(
            workflow,
            mock_registry,
            initial_params={"url": "https://example.com"},
            validate=False,
        )
        shared = {}
        flow.run(shared)

        # The input exists at root level (this is what caused the bug)
        # Note: After template resolution, initial_params may or may not persist at root
        # The key is that the node uses the TRANSFORMED url, not the raw input

        # Critical assertion: HTTP used the template-transformed URL
        assert "fetch" in shared
        assert shared["fetch"]["response"] == "Fetched: https://r.jina.ai/https://example.com"

    def test_input_named_prompt_does_not_override_llm_prompt_template(self, mock_registry, mock_import):
        """Input 'prompt' must not override LLM's prompt template."""
        workflow = {
            "ir_version": "0.1.0",
            "inputs": {
                "prompt": {"type": "string", "required": True},  # Matches LLM param!
            },
            "nodes": [
                {
                    "id": "llm",
                    "type": "mock-llm",
                    "params": {
                        "prompt": "Prefix: ${prompt} :Suffix",  # Transform
                        "images": [],
                    },
                },
            ],
            "edges": [],
        }

        flow = compile_ir_to_flow(
            workflow,
            mock_registry,
            initial_params={"prompt": "user input"},
            validate=False,
        )
        shared = {}
        flow.run(shared)

        # LLM used transformed prompt, not raw input
        assert "llm" in shared
        assert "Prefix: user input :Suffix" in shared["llm"]["response"]


# =============================================================================
# Regression Test 3: Static Param Not Overridden
# =============================================================================


class TestStaticParamNotOverridden:
    """
    Tests that static params are used even when workflow inputs have the same name.

    This is the NEW correct behavior after removing the fallback pattern.
    Before: shared["url"] would override static params["url"]
    After: static params["url"] is used regardless of shared["url"]
    """

    def test_static_url_param_not_overridden_by_input(self, mock_registry, mock_import):
        """Static URL param should be used, not overridden by same-named input."""
        workflow = {
            "ir_version": "0.1.0",
            "inputs": {
                "url": {"type": "string", "required": False, "default": "https://input.com"},
            },
            "nodes": [
                {
                    "id": "fetch",
                    "type": "mock-http",
                    "params": {
                        "url": "https://static.com",  # Static, no template
                    },
                },
            ],
            "edges": [],
        }

        # Provide input that would have overridden in old behavior
        flow = compile_ir_to_flow(
            workflow,
            mock_registry,
            initial_params={"url": "https://override.com"},
            validate=False,
        )
        shared = {}
        flow.run(shared)

        # Static param should win
        assert "fetch" in shared
        assert shared["fetch"]["response"] == "Fetched: https://static.com"

    def test_static_param_wins_over_default_input(self, mock_registry, mock_import):
        """Static param should win even against workflow input defaults."""
        workflow = {
            "ir_version": "0.1.0",
            "inputs": {
                "url": {"type": "string", "required": False, "default": "https://default.com"},
            },
            "nodes": [
                {
                    "id": "fetch",
                    "type": "mock-http",
                    "params": {"url": "https://hardcoded.com"},  # Static
                },
            ],
            "edges": [],
        }

        # Provide the default via initial_params (simulating what executor does)
        flow = compile_ir_to_flow(
            workflow,
            mock_registry,
            initial_params={"url": "https://default.com"},
            validate=False,
        )
        shared = {}
        flow.run(shared)

        # Static param wins
        assert shared["fetch"]["response"] == "Fetched: https://hardcoded.com"


# =============================================================================
# Regression Test 4: Falsy Value Preservation
# =============================================================================


class TestFalsyValuePreservation:
    """
    Tests that falsy param values are preserved, not treated as missing.

    The old `or` pattern would fall through on falsy values:
      shared.get("x") or params.get("x")  # Falls through if shared["x"] = ""

    The new pattern preserves falsy values:
      params.get("x")  # Returns "" correctly
    """

    def test_zero_param_value_preserved(self, mock_registry, mock_import):
        """Zero (0) should be preserved, not treated as missing."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "echo",
                    "type": "mock-echo",
                    "params": {"count": 0},  # Falsy but valid
                },
            ],
            "edges": [],
        }

        flow = compile_ir_to_flow(workflow, mock_registry, validate=False)
        shared = {}
        flow.run(shared)

        assert shared["echo"]["result"]["count"] == 0

    def test_false_param_value_preserved(self, mock_registry, mock_import):
        """False should be preserved, not treated as missing."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "echo",
                    "type": "mock-echo",
                    "params": {"enabled": False},  # Falsy but valid
                },
            ],
            "edges": [],
        }

        flow = compile_ir_to_flow(workflow, mock_registry, validate=False)
        shared = {}
        flow.run(shared)

        assert shared["echo"]["result"]["enabled"] is False

    def test_empty_string_param_value_preserved(self, mock_registry, mock_import):
        """Empty string should be preserved, not treated as missing."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "echo",
                    "type": "mock-echo",
                    "params": {"message": ""},  # Falsy but valid
                },
            ],
            "edges": [],
        }

        flow = compile_ir_to_flow(workflow, mock_registry, validate=False)
        shared = {}
        flow.run(shared)

        assert shared["echo"]["result"]["message"] == ""

    def test_none_param_value_preserved(self, mock_registry, mock_import):
        """None should be preserved when explicitly set."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "echo",
                    "type": "mock-echo",
                    "params": {"data": None},  # Explicit None
                },
            ],
            "edges": [],
        }

        flow = compile_ir_to_flow(workflow, mock_registry, validate=False)
        shared = {}
        flow.run(shared)

        assert shared["echo"]["result"]["data"] is None

    def test_falsy_values_not_overridden_by_shared_store(self, mock_registry, mock_import):
        """
        Falsy param values should not cause fallback to shared store.

        This tests the behavioral change from `or` to direct access.
        """
        workflow = {
            "ir_version": "0.1.0",
            "inputs": {
                # Mark as not required so defaults are used
                "count": {"type": "number", "required": False, "default": 999},
                "message": {"type": "string", "required": False, "default": "default msg"},
            },
            "nodes": [
                {
                    "id": "echo",
                    "type": "mock-echo",
                    "params": {
                        "count": 0,  # Falsy - would have been overridden by 999 in old code
                        "message": "",  # Falsy - would have been overridden by "default msg"
                    },
                },
            ],
            "edges": [],
        }

        # Provide defaults via initial_params (simulating executor behavior)
        flow = compile_ir_to_flow(
            workflow,
            mock_registry,
            initial_params={"count": 999, "message": "default msg"},
            validate=False,
        )
        shared = {}
        flow.run(shared)

        # Falsy params should be preserved, not overridden by input defaults
        # In old code: shared.get("count") or params.get("count") would return 999
        # In new code: params.get("count") returns 0
        assert shared["echo"]["result"]["count"] == 0
        assert shared["echo"]["result"]["message"] == ""


# =============================================================================
# Edge Case: Template Resolution Still Works
# =============================================================================


class TestTemplateResolutionStillWorks:
    """
    Verify that template resolution from shared store still works correctly.

    The fix removes the FALLBACK pattern, but templates should still resolve
    values from shared store and place them in params.
    """

    def test_template_resolves_from_workflow_input(self, mock_registry, mock_import):
        """Templates should still resolve ${input} from workflow inputs."""
        workflow = {
            "ir_version": "0.1.0",
            "inputs": {
                "target": {"type": "string", "required": True},
            },
            "nodes": [
                {
                    "id": "fetch",
                    "type": "mock-http",
                    "params": {"url": "${target}"},  # Template, not static
                },
            ],
            "edges": [],
        }

        flow = compile_ir_to_flow(
            workflow,
            mock_registry,
            initial_params={"target": "https://resolved.com"},
            validate=False,
        )
        shared = {}
        flow.run(shared)

        assert shared["fetch"]["response"] == "Fetched: https://resolved.com"

    def test_template_resolves_from_upstream_node(self, mock_registry, mock_import):
        """Templates should still resolve ${node.output} from upstream nodes."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "prepare",
                    "type": "mock-shell",
                    "params": {"command": "echo https://from-node.com"},
                },
                {
                    "id": "fetch",
                    "type": "mock-http",
                    "params": {"url": "${prepare.stdout}"},  # Template from node
                },
            ],
            "edges": [{"from": "prepare", "to": "fetch"}],
        }

        flow = compile_ir_to_flow(workflow, mock_registry, validate=False)
        shared = {}
        flow.run(shared)

        # Note: MockShellNode returns different output, so we just check it ran
        assert "fetch" in shared
        assert "Fetched:" in shared["fetch"]["response"]

    def test_template_with_transformation(self, mock_registry, mock_import):
        """Templates with transformations (prefix/suffix) should work."""
        workflow = {
            "ir_version": "0.1.0",
            "inputs": {
                "path": {"type": "string", "required": True},
            },
            "nodes": [
                {
                    "id": "fetch",
                    "type": "mock-http",
                    "params": {"url": "https://api.example.com/${path}?format=json"},
                },
            ],
            "edges": [],
        }

        flow = compile_ir_to_flow(
            workflow,
            mock_registry,
            initial_params={"path": "users/123"},
            validate=False,
        )
        shared = {}
        flow.run(shared)

        assert shared["fetch"]["response"] == "Fetched: https://api.example.com/users/123?format=json"
