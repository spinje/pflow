"""Simple test to demonstrate the namespacing issue with LLM usage tracking."""

# Mock the essential classes to demonstrate the issue
class NamespacedSharedStore:
    """Simplified version of the actual NamespacedSharedStore."""

    def __init__(self, parent_store, namespace):
        self._parent = parent_store
        self._namespace = namespace

        # Ensure namespace exists
        if namespace not in parent_store:
            parent_store[namespace] = {}

    def __setitem__(self, key, value):
        """All writes go to the namespaced location."""
        self._parent[self._namespace][key] = value

    def get(self, key, default=None):
        """Read from namespace first, then root."""
        if key in self._parent[self._namespace]:
            return self._parent[self._namespace][key]
        if key in self._parent:
            return self._parent[key]
        return default


def simulate_llm_node_without_namespacing():
    """Simulate what happens without namespacing."""
    print("\n=== Without Namespacing ===")

    shared = {}

    # LLMNode writes directly to shared store
    shared["llm_usage"] = {
        "model": "gpt-4",
        "input_tokens": 100,
        "output_tokens": 50,
        "total_tokens": 150
    }

    # InstrumentedNodeWrapper checks for llm_usage
    if shared.get("llm_usage"):
        print("✓ Found llm_usage at root level")
        print(f"  Location: shared['llm_usage']")
        print(f"  Value: {shared['llm_usage']}")
    else:
        print("✗ No llm_usage found")

    return shared


def simulate_llm_node_with_namespacing():
    """Simulate what happens with namespacing."""
    print("\n=== With Namespacing ===")

    shared = {}
    node_id = "llm_node_1"

    # NamespacedNodeWrapper creates a proxy
    namespaced_shared = NamespacedSharedStore(shared, node_id)

    # LLMNode writes through the namespaced proxy
    namespaced_shared["llm_usage"] = {
        "model": "gpt-4",
        "input_tokens": 100,
        "output_tokens": 50,
        "total_tokens": 150
    }

    print(f"After LLMNode writes:")
    print(f"  Root keys: {list(shared.keys())}")
    print(f"  Namespace keys: {list(shared.get(node_id, {}).keys())}")
    print(f"  Actual location: shared['{node_id}']['llm_usage']")

    # InstrumentedNodeWrapper checks the ROOT shared store (not the namespaced proxy)
    if shared.get("llm_usage"):
        print("✓ Found llm_usage at root level")
    else:
        print("✗ No llm_usage found at root level (BUG!)")

    # But the data IS in the namespaced location
    if shared.get(node_id, {}).get("llm_usage"):
        print(f"✓ But llm_usage IS in shared['{node_id}']['llm_usage']")

    return shared


def demonstrate_the_fix():
    """Show how the fix would work."""
    print("\n=== The Fix ===")
    print("InstrumentedNodeWrapper needs to check BOTH locations:")
    print("1. shared.get('llm_usage') - for non-namespaced nodes")
    print("2. shared.get(node_id, {}).get('llm_usage') - for namespaced nodes")
    print("\nOr better: have a special key pattern that bypasses namespacing")
    print("e.g., keys starting with '__' could always go to root level")


if __name__ == "__main__":
    print("=" * 60)
    print("DEMONSTRATING THE LLM USAGE TRACKING BUG")
    print("=" * 60)

    simulate_llm_node_without_namespacing()
    simulate_llm_node_with_namespacing()
    demonstrate_the_fix()

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print("""
The bug occurs because:
1. The wrapper order is: InstrumentedNodeWrapper → NamespacedNodeWrapper → LLMNode
2. When LLMNode writes shared["llm_usage"], it goes through NamespacedSharedStore
3. NamespacedSharedStore redirects the write to shared["llm_node_1"]["llm_usage"]
4. InstrumentedNodeWrapper later checks shared.get("llm_usage") at the root
5. It finds nothing there, so no LLM usage is recorded

This is why the metrics show 0.0 USD for LLM costs and __llm_calls__ is empty!
""")
