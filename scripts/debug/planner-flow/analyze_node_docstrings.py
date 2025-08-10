#!/usr/bin/env python3
"""Direct docstring analysis without imports to avoid module issues."""

import re


def analyze_read_file_docstring():
    """Analyze the ReadFileNode docstring to see what parameters should be extracted."""

    # The docstring from ReadFileNode
    docstring = '''
    Read content from a file and add line numbers for display.

    This node reads a text file and formats it with 1-indexed line numbers,
    following the Tutorial-Cursor pattern for file display.

    Interface:
    - Reads: shared["file_path"]: str  # Path to the file to read
    - Reads: shared["encoding"]: str  # File encoding (optional, default: utf-8)
    - Writes: shared["content"]: str  # File contents with line numbers
    - Writes: shared["error"]: str  # Error message if operation failed
    - Actions: default (success), error (failure)

    Security Note: This node can read ANY accessible file on the system.
    Do not expose to untrusted input without proper validation.
    '''

    print("=== ANALYZING READ-FILE NODE DOCSTRING ===\n")

    # Extract Interface section manually
    interface_match = re.search(r"Interface:\s*\n((?:[ \t]*-[^\n]+(?:\n(?![ \t]*-)[ \t]+[^\n]+)*\n?)*)", docstring)
    if interface_match:
        interface_content = interface_match.group(1)
        print("Interface section found:")
        print(interface_content)

        # Look for Params section
        if "- Params:" in interface_content:
            print("✅ Found Params section in Interface")
        else:
            print("❌ NO Params section found in Interface")
            print("   → This means NO parameters are documented for the LLM to see!")

        # Show what IS documented
        sections = re.findall(r'- (\w+):', interface_content)
        print(f"   → Documented sections: {sections}")

        # Look for file_path usage
        if "file_path" in interface_content:
            print("✅ 'file_path' mentioned in Interface")
            if re.search(r'- Reads:.*file_path', interface_content):
                print("   → Found in Reads section (shared store input)")
            if re.search(r'- Params:.*file_path', interface_content):
                print("   → Found in Params section (node parameter)")
            else:
                print("   → NOT in Params section - LLM won't know it's a parameter!")


def analyze_llm_node_docstring():
    """Analyze the LLMNode docstring to see what parameters should be extracted."""

    # The docstring from LLMNode
    docstring = '''
    General-purpose LLM node for text processing.

    Interface:
    - Reads: shared["prompt"]: str  # Text prompt to send to model
    - Reads: shared["system"]: str  # System prompt (optional)
    - Writes: shared["response"]: str  # Model's text response
    - Writes: shared["llm_usage"]: dict  # Token usage metrics (empty dict {} if unavailable)
        - model: str  # Model identifier used
        - input_tokens: int  # Number of input tokens consumed
        - output_tokens: int  # Number of output tokens generated
        - total_tokens: int  # Total tokens (input + output)
        - cache_creation_input_tokens: int  # Tokens used for cache creation
        - cache_read_input_tokens: int  # Tokens read from cache
    - Params: model: str  # Model to use (default: gpt-4o-mini)
    - Params: temperature: float  # Sampling temperature (default: 0.7)
    - Params: max_tokens: int  # Max response tokens (optional)
    - Actions: default (always)
    '''

    print("\n=== ANALYZING LLM NODE DOCSTRING ===\n")

    # Extract Interface section manually
    interface_match = re.search(r"Interface:\s*\n((?:[ \t]*-[^\n]+(?:\n(?![ \t]*-)[ \t]+[^\n]+)*\n?)*)", docstring)
    if interface_match:
        interface_content = interface_match.group(1)
        print("Interface section found:")
        print(interface_content)

        # Look for Params section
        if "- Params:" in interface_content:
            print("✅ Found Params section in Interface")

            # Extract all Params lines
            params_lines = re.findall(r'- Params: ([^\n]+)', interface_content)
            print(f"✅ Found {len(params_lines)} parameter definitions:")
            for i, param_line in enumerate(params_lines, 1):
                print(f"   {i}. {param_line}")

        else:
            print("❌ NO Params section found in Interface")

        # Show what IS documented
        sections = re.findall(r'- (\w+):', interface_content)
        print(f"   → Documented sections: {sections}")


def simulate_planning_context():
    """Simulate what the planning context would look like."""
    print("\n=== SIMULATING PLANNING CONTEXT ===\n")

    print("For read-file node, the LLM would see:")
    print("### read-file")
    print("Read content from a file and add line numbers for display.")
    print("")
    print("**Inputs**:")
    print("- `file_path: str` - Path to the file to read")
    print("- `encoding: str` - File encoding (optional, default: utf-8)")
    print("")
    print("**Outputs**:")
    print("- `content: str` - File contents with line numbers")
    print("- `error: str` - Error message if operation failed")
    print("")
    print("**Parameters**: none")  # ❌ This is the problem!
    print("")

    print("For llm node, the LLM would see:")
    print("### llm")
    print("General-purpose LLM node for text processing.")
    print("")
    print("**Inputs**:")
    print("- `prompt: str` - Text prompt to send to model")
    print("- `system: str` - System prompt (optional)")
    print("")
    print("**Outputs**:")
    print("- `response: str` - Model's text response")
    print("- `llm_usage: dict` - Token usage metrics")
    print("")
    print("**Parameters**:")
    print("- `model: str` - Model to use (default: gpt-4o-mini)")
    print("- `temperature: float` - Sampling temperature (default: 0.7)")
    print("- `max_tokens: int` - Max response tokens (optional)")
    print("")


def main():
    """Run all analysis."""
    analyze_read_file_docstring()
    analyze_llm_node_docstring()
    simulate_planning_context()

    print("=== ROOT CAUSE ANALYSIS ===")
    print("")
    print("❌ PROBLEM IDENTIFIED:")
    print("1. read-file node has NO 'Params:' section in its Interface")
    print("2. file_path is only documented under 'Reads:' (shared store input)")
    print("3. The planning context only shows 'Parameters: none' for read-file")
    print("4. The LLM doesn't know file_path can be used as a node parameter!")
    print("")
    print("✅ SOLUTION:")
    print("1. Add 'Params:' sections to node docstrings for configurable parameters")
    print("2. Document file_path as both an input AND a parameter")
    print("3. Update the Enhanced Interface Format to include both:")
    print("   - Reads: shared['file_path']: str  # Input from shared store")
    print("   - Params: file_path: str  # Node parameter (fallback)")
    print("")
    print("This way the LLM will know it can use $file_path in node params!")


if __name__ == "__main__":
    main()
