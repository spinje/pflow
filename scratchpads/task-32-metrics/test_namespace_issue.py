"""Test to demonstrate the namespacing issue with LLM usage tracking."""

import sys
from pathlib import Path

# Add paths for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from pflow.runtime.instrumented_wrapper import InstrumentedNodeWrapper
from pflow.runtime.namespaced_wrapper import NamespacedNodeWrapper
from pocketflow import Node


class MockLLMNode(Node):
    """Mock LLM node that sets llm_usage in shared store."""

    def _run(self, shared):
        # This mimics what the real LLMNode does in its post() method
        shared["llm_usage"] = {
            "model": "gpt-4",
            "input_tokens": 100,
            "output_tokens": 50,
            "total_tokens": 150
        }
        shared["response"] = "test response"
        return "default"


def test_without_namespacing():
    """Test that works correctly without namespacing."""
    print("\n=== Test WITHOUT Namespacing ===")

    # Create node without namespacing
    node = MockLLMNode()
    wrapper = InstrumentedNodeWrapper(node, "llm_node_1", None, None)

    shared = {}
    wrapper._run(shared)

    print(f"shared store keys: {list(shared.keys())}")
    print(f"llm_usage in shared: {'llm_usage' in shared}")
    print(f"__llm_calls__ content: {shared.get('__llm_calls__', [])}")

    assert "__llm_calls__" in shared
    assert len(shared["__llm_calls__"]) == 1
    print("✓ LLM usage correctly captured without namespacing")


def test_with_namespacing():
    """Test that shows the issue with namespacing."""
    print("\n=== Test WITH Namespacing (showing the bug) ===")

    # Create node WITH namespacing (as done in compiler.py)
    node = MockLLMNode()
    # Wrap order: Instrumented → Namespaced → Node
    namespaced = NamespacedNodeWrapper(node, "llm_node_1")
    wrapper = InstrumentedNodeWrapper(namespaced, "llm_node_1", None, None)

    shared = {}
    wrapper._run(shared)

    print(f"Root shared store keys: {list(shared.keys())}")
    print(f"llm_usage in root shared: {'llm_usage' in shared}")
    print(f"Namespaced keys: {list(shared.get('llm_node_1', {}).keys())}")
    print(f"llm_usage in namespace: {'llm_usage' in shared.get('llm_node_1', {})}")
    print(f"__llm_calls__ content: {shared.get('__llm_calls__', [])}")

    # The issue: InstrumentedNodeWrapper looks for shared["llm_usage"]
    # but NamespacedNodeWrapper puts it in shared["llm_node_1"]["llm_usage"]
    assert "__llm_calls__" in shared
    print(f"Number of LLM calls captured: {len(shared['__llm_calls__'])}")

    if len(shared["__llm_calls__"]) == 0:
        print("✗ BUG CONFIRMED: LLM usage NOT captured with namespacing!")
        print("  - LLMNode wrote to namespaced location: shared['llm_node_1']['llm_usage']")
        print("  - InstrumentedNodeWrapper checked root: shared.get('llm_usage')")
    else:
        print("✓ LLM usage correctly captured with namespacing")


if __name__ == "__main__":
    test_without_namespacing()
    test_with_namespacing()

    print("\n=== Analysis ===")
    print("The issue is that when namespacing is enabled:")
    print("1. LLMNode writes to shared['llm_usage'] via NamespacedSharedStore")
    print("2. NamespacedSharedStore redirects this to shared['llm_node_1']['llm_usage']")
    print("3. InstrumentedNodeWrapper checks shared.get('llm_usage') at the root level")
    print("4. It doesn't find anything, so no LLM usage is recorded")
