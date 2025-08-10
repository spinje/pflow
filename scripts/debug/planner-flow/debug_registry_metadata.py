#!/usr/bin/env python3
"""Simple debug script to examine what the registry captures about node parameters."""

import sys
import os
import re
from pathlib import Path

# Add src to path to import pflow modules
repo_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(repo_root / "src"))

# Import only what we need to avoid the llm import issue
from pflow.registry.metadata_extractor import PflowMetadataExtractor
from pflow.planning.context_builder import _format_node_section_enhanced


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
    print("Raw docstring Interface section:")

    # Extract Interface section manually
    interface_match = re.search(r"Interface:\s*\n((?:[ \t]*-[^\n]+(?:\n(?![ \t]*-)[ \t]+[^\n]+)*\n?)*)", docstring)
    if interface_match:
        interface_content = interface_match.group(1)
        print(interface_content)

        # Look for Params section
        if "Params:" in interface_content:
            print("✅ Found Params section in Interface")
        else:
            print("❌ NO Params section found in Interface")
            print("This explains why no parameters are included in planning context!")

        # Look for individual parameter definitions
        if "file_path" in interface_content:
            print("✅ 'file_path' mentioned in Interface")
            # But is it in Reads (inputs) or Params section?
            if re.search(r'Reads:.*shared\["file_path"\]', interface_content, re.DOTALL):
                print("   → Found in Reads section (input from shared store)")
            if re.search(r'Params:.*file_path', interface_content, re.DOTALL):
                print("   → Found in Params section (node parameter)")
            else:
                print("   → NOT found in Params section - it's only an input!")


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
    print("Raw docstring Interface section:")

    # Extract Interface section manually
    interface_match = re.search(r"Interface:\s*\n((?:[ \t]*-[^\n]+(?:\n(?![ \t]*-)[ \t]+[^\n]+)*\n?)*)", docstring)
    if interface_match:
        interface_content = interface_match.group(1)
        print(interface_content)

        # Look for Params section
        if "Params:" in interface_content:
            print("✅ Found Params section in Interface")

            # Extract Params content
            params_match = re.search(r'Params:(.*?)(?=\n- \w+:|$)', interface_content, re.DOTALL)
            if params_match:
                params_content = params_match.group(1)
                print("\nParams content:")
                print(params_content)

                # Count parameters
                param_lines = [line.strip() for line in params_content.split('\n') if line.strip() and not line.strip().startswith('-')]
                print(f"\nFound {len(param_lines)} parameter definitions")

        else:
            print("❌ NO Params section found in Interface")


def test_metadata_extractor():
    """Test the metadata extractor on a mock class."""
    print("\n=== TESTING METADATA EXTRACTOR ===\n")

    # Create a mock class with the read-file docstring
    class MockReadFileNode:
        '''
        Read content from a file and add line numbers for display.

        This node reads a text file and formats it with 1-indexed line numbers,
        following the Tutorial-Cursor pattern for file display.

        Interface:
        - Reads: shared["file_path"]: str  # Path to the file to read
        - Reads: shared["encoding"]: str  # File encoding (optional, default: utf-8)
        - Writes: shared["content"]: str  # File contents with line numbers
        - Writes: shared["error"]: str  # Error message if operation failed
        - Actions: default (success), error (failure)
        '''
        pass

    # Add a fake parent class to avoid inheritance check
    class MockBaseNode:
        pass
    MockReadFileNode.__bases__ = (MockBaseNode,)

    # Try to extract metadata (this might fail due to inheritance check)
    extractor = PflowMetadataExtractor()
    try:
        # This will likely fail due to inheritance validation, but let's see
        metadata = extractor.extract_metadata(MockReadFileNode)
        print("Extracted metadata:")
        for key, value in metadata.items():
            print(f"  {key}: {value}")
    except Exception as e:
        print(f"Metadata extraction failed (expected): {e}")

        # Try manual parsing of interface
        print("\nTrying manual interface parsing...")
        docstring = MockReadFileNode.__doc__
        interface_data = extractor._parse_interface_section(docstring)
        print("Manually parsed interface:")
        for key, value in interface_data.items():
            print(f"  {key}: {value}")


def main():
    """Run all analysis."""
    analyze_read_file_docstring()
    analyze_llm_node_docstring()
    test_metadata_extractor()

    print("\n=== SUMMARY OF FINDINGS ===")
    print("1. ReadFileNode has NO 'Params:' section - file_path is only in 'Reads:'")
    print("2. LLMNode HAS 'Params:' section with model, temperature, max_tokens")
    print("3. This means the LLM doesn't know file_path is a parameter it can use!")
    print("4. The context_builder only shows parameters from the 'Params:' section")
    print("\n❌ ROOT CAUSE IDENTIFIED:")
    print("   The read-file node doesn't declare file_path as a parameter in its Interface.")
    print("   It only declares it as an input from shared store.")
    print("   The LLM can't know to use $file_path as a template variable!")


if __name__ == "__main__":
    main()
