#!/usr/bin/env python3
"""Demo of WorkflowManager functionality."""

from pflow.core.workflow_manager import WorkflowManager

# Sample workflow IR
sample_workflow_ir = {
    "ir_version": "0.1.0",
    "inputs": {"message": {"type": "str", "description": "Message to echo"}},
    "outputs": {"result": {"type": "str", "description": "Echo result"}},
    "nodes": [{"id": "echo_node", "type": "echo", "config": {"message": "{{ inputs.message }}"}}],
    "edges": [],
}


def main():
    # Initialize WorkflowManager
    manager = WorkflowManager()
    print(f"Workflows directory: {manager.workflows_dir}")

    # Save a workflow
    print("\n1. Saving workflow 'echo-demo'...")
    path = manager.save(
        name="echo-demo", workflow_ir=sample_workflow_ir, description="A simple echo workflow demonstration"
    )
    print(f"   Saved to: {path}")

    # Check if it exists
    print("\n2. Checking if workflow exists...")
    exists = manager.exists("echo-demo")
    print(f"   Exists: {exists}")

    # Load the full workflow metadata
    print("\n3. Loading full workflow metadata...")
    metadata = manager.load("echo-demo")
    print(f"   Name: {metadata['name']}")
    print(f"   Description: {metadata['description']}")
    print(f"   Created: {metadata['created_at']}")
    print(f"   Version: {metadata['version']}")

    # Load just the IR
    print("\n4. Loading just the IR...")
    ir = manager.load_ir("echo-demo")
    print(f"   IR version: {ir['ir_version']}")
    print(f"   Number of nodes: {len(ir['nodes'])}")

    # List all workflows
    print("\n5. Listing all workflows...")
    workflows = manager.list_all()
    for wf in workflows:
        print(f"   - {wf['name']}: {wf['description']}")

    # Get workflow path
    print("\n6. Getting workflow path...")
    wf_path = manager.get_path("echo-demo")
    print(f"   Path: {wf_path}")

    # Delete the workflow
    print("\n7. Deleting workflow...")
    manager.delete("echo-demo")
    print("   Workflow deleted")

    # Verify it's gone
    print("\n8. Verifying deletion...")
    exists = manager.exists("echo-demo")
    print(f"   Exists: {exists}")


if __name__ == "__main__":
    main()
