#!/usr/bin/env python3
"""
Simple demonstration of Runtime Validation detecting missing template paths.

This shows the core functionality without the full planner flow complexity.
"""

from pflow.planning.nodes import RuntimeValidationNode


def main():
    print("\n" + "="*70)
    print("RUNTIME VALIDATION DEMONSTRATION")
    print("="*70)

    # Create RuntimeValidationNode
    node = RuntimeValidationNode()

    print("\nScenario: GitHub API workflow with wrong field names")
    print("-" * 50)

    # Workflow that tries to use wrong field names
    workflow = {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": "api",
                "type": "http",
                "params": {"url": "https://api.github.com/users/torvalds"}
            },
            {
                "id": "display",
                "type": "write-file",
                "params": {
                    "file_path": "/tmp/user.txt",
                    "content": "User: ${api.response.username}, Bio: ${api.response.biography}"
                }
            }
        ],
        "edges": [{"from": "api", "to": "display"}],
        "start_node": "api"
    }

    # Simulate the actual API response structure
    actual_api_response = {
        "api": {
            "response": {
                "login": "torvalds",          # NOT "username"
                "id": 1024025,
                "name": "Linus Torvalds",
                "bio": "No bio",               # NOT "biography"
                "company": "Linux Foundation",
                "followers": 200000,
                "following": 0,
                "public_repos": 8,
                "created_at": "2011-09-03T15:26:22Z"
            },
            "status_code": 200
        }
    }

    print("\n1️⃣  DETECTING MISSING TEMPLATE PATHS:")
    print("-" * 40)

    # Extract templates from workflow
    templates = node._extract_templates_from_ir(workflow)

    missing_count = 0
    for template in sorted(templates):
        exists = node._check_template_exists(template, actual_api_response)

        if not exists:
            missing_count += 1
            print(f"\n❌ Missing: {template}")

            # Parse the template to get node and path
            import re
            match = re.match(r"\$\{([^.]+)\.(.+)\}", template)
            if match:
                node_id = match.group(1)
                path = match.group(2)

                # Get parent path for available fields
                path_parts = path.rsplit(".", 1)
                parent_path = path_parts[0] if len(path_parts) > 1 else ""

                available = node._get_available_paths(actual_api_response, node_id, parent_path)
                if available:
                    print(f"   📝 Available at '{node_id}.{parent_path}':")
                    print(f"      {', '.join(sorted(available)[:10])}")

    if missing_count > 0:
        print(f"\n⚠️  Found {missing_count} missing template paths!")
        print("\n2️⃣  RUNTIME FEEDBACK TO GENERATOR:")
        print("-" * 40)
        print("\nThe WorkflowGeneratorNode would receive:")
        print("• List of missing paths")
        print("• Available fields at each level")
        print("• Can now generate corrected workflow")

        print("\n3️⃣  CORRECTED WORKFLOW:")
        print("-" * 40)
        print("\nAfter receiving feedback, the generator would produce:")
        print("  ${api.response.username} → ${api.response.login}")
        print("  ${api.response.biography} → ${api.response.bio}")

        # Verify corrections work
        corrected_templates = [
            "${api.response.login}",
            "${api.response.bio}"
        ]

        print("\n4️⃣  VERIFICATION:")
        print("-" * 40)
        all_good = True
        for template in corrected_templates:
            exists = node._check_template_exists(template, actual_api_response)
            if exists:
                value = node._extract_value(template, actual_api_response)
                print(f"✅ {template} = '{value if value else '(none)'}'")
            else:
                print(f"❌ {template} still missing")
                all_good = False

        if all_good:
            print("\n🎉 All corrected paths work!")
    else:
        print("\n✅ All template paths are valid!")

    print("\n" + "="*70)
    print("KEY INSIGHTS:")
    print("="*70)
    print("1. RuntimeValidationNode detects missing template paths")
    print("2. It provides available fields for correction")
    print("3. WorkflowGeneratorNode uses this feedback to fix the workflow")
    print("4. The corrected workflow runs successfully")
    print("\nThis enables 'Plan Once, Run Forever' - workflows self-correct!")
    print("="*70)


def _extract_value_helper(node, template, data):
    """Helper to extract actual value from template path."""
    import re
    match = re.match(r"\$\{([^.]+)\.(.+)\}", template)
    if not match:
        return None

    node_id = match.group(1)
    path = match.group(2)

    current = data.get(node_id, {})
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None

    return current


# Add helper method to node for demo
RuntimeValidationNode._extract_value = lambda self, t, d: _extract_value_helper(self, t, d)


if __name__ == "__main__":
    main()