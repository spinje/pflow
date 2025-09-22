"""Simple test for RuntimeValidationNode template path detection."""

from pflow.planning.nodes import RuntimeValidationNode


def test_template_path_detection():
    """Test that we can detect missing template paths correctly."""

    node = RuntimeValidationNode()

    # Test the helper method directly
    # Simulate shared store after execution
    shared_after = {
        "http": {
            "response": {"login": "torvalds", "bio": "Linux creator", "id": 1024025, "name": "Linus Torvalds"},
            "status_code": 200,
        }
    }

    # Test cases
    test_cases = [
        # (template, should_exist)
        ("${http.response.login}", True),
        ("${http.response.bio}", True),
        ("${http.response.username}", False),  # Wrong field name
        ("${http.response.biography}", False),  # Wrong field name
        ("${http.status_code}", True),
        ("${http.response.nested.field}", False),  # Doesn't exist
        ("${api_key}", True),  # Workflow input (not node output)
    ]

    print("Testing template path detection:")
    for template, expected_exists in test_cases:
        exists = node._check_template_exists(template, shared_after)
        status = "✓" if exists == expected_exists else "✗"
        print(
            f"  {status} {template}: {'exists' if exists else 'missing'} (expected: {'exists' if expected_exists else 'missing'})"
        )
        assert exists == expected_exists, f"Failed for {template}"

    print("\n✓ All template path detection tests passed!")


def test_available_paths_helper():
    """Test the helper method that finds available paths."""

    node = RuntimeValidationNode()

    shared_after = {
        "http": {
            "response": {
                "login": "torvalds",
                "bio": "Linux creator",
                "items": [{"id": 1, "name": "item1"}, {"id": 2, "name": "item2"}],
            }
        }
    }

    # Test getting available paths at different levels
    test_cases = [
        ("http", "", ["response"]),
        ("http", "response", ["login", "bio", "items"]),
        ("http", "response.items", ["[0]", "[1]"]),
        ("http", "nonexistent", []),
    ]

    print("Testing available paths helper:")
    for node_id, path, expected in test_cases:
        available = node._get_available_paths(shared_after, node_id, path)
        print(f"  {node_id}.{path if path else '(root)'}: {available}")
        assert set(available) == set(expected), f"Failed for {node_id}.{path}"

    print("\n✓ All available paths tests passed!")


def test_template_extraction():
    """Test extraction of templates from workflow IR."""

    node = RuntimeValidationNode()

    workflow_ir = {
        "nodes": [
            {
                "id": "test",
                "params": {
                    "simple": "Value with ${http.response.login}",
                    "multiple": "${http.response.bio} and ${http.status_code}",
                    "nested_dict": {"field": "${nested.template}"},
                    "list": ["item1", "${list.template}"],
                    "no_template": "plain text",
                },
            }
        ]
    }

    templates = node._extract_templates_from_ir(workflow_ir)

    expected = [
        "${http.response.login}",
        "${http.response.bio}",
        "${http.status_code}",
        "${nested.template}",
        "${list.template}",
    ]

    print("Testing template extraction from IR:")
    print(f"  Found {len(templates)} templates")
    for t in templates:
        print(f"    - {t}")

    assert set(templates) == set(expected), f"Expected {expected}, got {templates}"
    print("\n✓ Template extraction test passed!")


if __name__ == "__main__":
    test_template_path_detection()
    test_available_paths_helper()
    test_template_extraction()
    print("\n🎉 All RuntimeValidationNode helper tests passed!")
