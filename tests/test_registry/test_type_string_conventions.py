"""Test type string conventions are enforced.

WHEN TO RUN:
- Always (part of standard test suite)
- After modifying metadata extractor type parsing
- After adding new nodes or MCP integrations

WHAT IT VALIDATES:
- All type strings in registry are lowercase
- Prevents case-sensitivity bugs like 'Any' vs 'any'
"""

from pflow.registry import Registry


def _collect_type_strings(interface: dict) -> list[tuple[str, str, str]]:
    """Collect all type strings from a node interface.

    Returns:
        List of (location, key, type_string) tuples
    """
    results = []

    # Check outputs
    for output in interface.get("outputs", []):
        type_str = output.get("type", "")
        if type_str:
            results.append(("output", output.get("key", "unknown"), type_str))

    # Check params
    for param in interface.get("params", []):
        type_str = param.get("type", "")
        if type_str:
            key = param.get("key") or param.get("name", "unknown")
            results.append(("param", key, type_str))

    # Check inputs
    for inp in interface.get("inputs", []):
        type_str = inp.get("type", "")
        if type_str:
            key = inp.get("key") or inp.get("name", "unknown")
            results.append(("input", key, type_str))

    return results


class TestTypeStringConventions:
    """Ensure all type strings follow lowercase convention."""

    def test_all_registry_type_strings_are_lowercase(self):
        """All type strings in the registry must be lowercase.

        This prevents case-sensitivity bugs where 'Any' != 'any' causes
        validation failures. See: scratchpads/mcp-any-type-case-sensitivity/
        """
        registry = Registry()
        nodes = registry.load()

        violations = []

        for node_name, metadata in nodes.items():
            interface = metadata.get("interface", {})
            type_strings = _collect_type_strings(interface)

            for location, key, type_str in type_strings:
                # Check each part of union types (e.g., "dict|str")
                for part in type_str.split("|"):
                    # Extract base type (handle generics like "list[dict]")
                    base_type = part.split("[")[0].strip()
                    if base_type and base_type != base_type.lower():
                        violations.append(
                            f"{node_name}: {location} '{key}' has type '{type_str}' "
                            f"('{base_type}' should be '{base_type.lower()}')"
                        )

        assert not violations, f"Found {len(violations)} uppercase type string(s):\n" + "\n".join(
            f"  - {v}" for v in violations
        )

    def test_type_convention_examples(self):
        """Document expected type string conventions."""
        # These are the valid lowercase type strings
        valid_types = [
            "str",
            "int",
            "float",
            "bool",
            "dict",
            "list",
            "any",
            "bytes",
            # Union types
            "dict|str",
            "str|bytes",
            # Generic types
            "list[str]",
            "list[dict]",
            "dict[str, any]",
        ]

        for type_str in valid_types:
            for part in type_str.split("|"):
                base_type = part.split("[")[0].strip()
                assert base_type == base_type.lower(), f"Convention violation: {type_str}"
