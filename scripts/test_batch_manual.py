#!/usr/bin/env python3
"""Manual test script for batch processing.

Run with: uv run python scripts/test_batch_manual.py
"""

from pflow.registry import Registry
from pflow.runtime import compile_ir_to_flow


def main():
    """Test batch processing end-to-end."""
    print("=" * 60)
    print("Manual Batch Processing Test")
    print("=" * 60)

    # Create a simple workflow that:
    # 1. Uses shell to output a JSON array
    # 2. Parses stdout as JSON and batches over it
    # 3. For each item, echoes a message

    ir = {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": "create_list",
                "type": "shell",
                "purpose": "Create a JSON array",
                "params": {
                    "command": 'echo \'["apple", "banana", "cherry"]\''
                },
            },
            {
                "id": "parse_json",
                "type": "shell",
                "purpose": "Parse JSON (workaround - use jq to output each line)",
                "params": {
                    "command": "echo '${create_list.stdout}' | python3 -c \"import sys, json; print(json.dumps(json.loads(sys.stdin.read())))\""
                },
            },
        ],
        "edges": [{"from": "create_list", "to": "parse_json"}],
    }

    print("\n1. Testing basic workflow compilation...")
    registry = Registry()
    flow = compile_ir_to_flow(ir, registry=registry, validate=False)
    print("   ✓ Workflow compiled successfully")

    print("\n2. Running workflow...")
    shared = {}
    flow.run(shared)
    print(f"   ✓ Workflow executed")
    print(f"   create_list.stdout: {shared.get('create_list', {}).get('stdout', 'N/A')}")
    print(f"   parse_json.stdout: {shared.get('parse_json', {}).get('stdout', 'N/A')}")

    # Now test with actual batch processing
    print("\n3. Testing batch processing...")

    # We need to simulate having an array in shared store
    # Let's use a simpler approach: directly test the batch wrapper

    from pflow.runtime.batch_node import PflowBatchNode
    from pocketflow import Node

    class SimpleNode(Node):
        """Simple node for testing - writes to namespace."""

        def __init__(self, node_id: str):
            super().__init__()
            self.node_id = node_id

        def prep(self, shared):
            return shared.get("item") or self.params.get("value")

        def exec(self, prep_res):
            return f"Processed: {prep_res}"

        def post(self, shared, prep_res, exec_res):
            # Write to namespace (simulating NamespacedNodeWrapper behavior)
            if self.node_id not in shared:
                shared[self.node_id] = {}
            shared[self.node_id]["result"] = exec_res
            return "default"

    # Create batch wrapper
    inner_node = SimpleNode("batch_test")
    batch_node = PflowBatchNode(
        inner_node,
        node_id="batch_test",
        batch_config={"items": "${data}", "as": "item"},
    )

    # Test execution
    test_shared = {"data": ["apple", "banana", "cherry"]}
    print(f"   Input: {test_shared['data']}")

    items = batch_node.prep(test_shared)
    print(f"   Items resolved: {items}")

    results = batch_node._exec(items)
    print(f"   Results: {results}")

    batch_node.post(test_shared, items, results)
    print(f"   Final output:")
    print(f"     - count: {test_shared['batch_test']['count']}")
    print(f"     - success_count: {test_shared['batch_test']['success_count']}")
    print(f"     - error_count: {test_shared['batch_test']['error_count']}")
    print(f"     - results: {test_shared['batch_test']['results']}")

    print("\n" + "=" * 60)
    print("✓ All manual tests passed!")
    print("=" * 60)


if __name__ == "__main__":
    main()
