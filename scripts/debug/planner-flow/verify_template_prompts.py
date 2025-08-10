#!/usr/bin/env python3
"""
Focused test to verify the template variable fix is working.
This test focuses specifically on template variable usage.
"""

import os
import sys
import json
import logging
from pathlib import Path

# Add the src directory to Python path
src_dir = Path(__file__).parent.parent.parent / "src"
sys.path.insert(0, str(src_dir))

# Set up logging to see detailed output
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

def test_workflow_generator_prompt_fix():
    """Test that the WorkflowGeneratorNode prompt includes proper template guidance."""
    print("🔬 Testing Template Variable Prompt Fix")
    print("=" * 50)

    from pflow.planning.nodes import WorkflowGeneratorNode

    # Create generator node
    generator = WorkflowGeneratorNode()

    # Create test data similar to what would cause the "unused template variable" error
    prep_result = {
        "model_name": "gpt-4o-mini",  # Use OpenAI for testing without API key issues
        "temperature": 0.0,
        "user_input": "Read input.txt and write to output.txt",
        "planning_context": """Available Components:

## File Operations

### read-file
**Type**: read-file
**Description**: Read content from a file and store in shared store
**Parameters**: none
**Reads**: shared['file_path']
**Writes**: shared['file_content']
**Interface Format**:
- Inputs:
  - file_path (string, required): Path to the file to read

### write-file
**Type**: write-file
**Description**: Write content to a file from shared store
**Parameters**: none
**Reads**: shared['file_path'], shared['file_content']
**Writes**: none (writes to filesystem)
**Interface Format**:
- Inputs:
  - file_path (string, required): Path where to write the file
  - file_content (string, required): Content to write to the file""",
        "discovered_params": {
            "input_file": "input.txt",
            "output_file": "output.txt"
        },
        "browsed_components": {},
        "validation_errors": [],
        "generation_attempts": 0,
    }

    # Build and analyze the prompt
    prompt = generator._build_prompt(prep_result)

    print(f"📏 Prompt length: {len(prompt)} characters\n")

    # Test 1: Check for critical template guidance
    critical_elements = [
        "Use template variables ($variable) for ALL dynamic values",
        "NEVER hardcode values",
        "Every declared input MUST be used as a template variable",
        "IMPORTANT: Nodes can accept template variables for ANY of their input keys",
        "Even if a node shows \"Parameters: none\"",
        "This is the \"Exclusive Params\" pattern"
    ]

    print("🎯 Critical Template Guidance Check:")
    all_present = True
    for element in critical_elements:
        if element in prompt:
            print(f"   ✅ {element}")
        else:
            print(f"   ❌ MISSING: {element}")
            all_present = False

    # Test 2: Check for complete example
    print(f"\n📋 Example Section Check:")
    if "EXAMPLE showing proper template variable usage:" in prompt:
        print(f"   ✅ Example section present")

        # Check for key parts of the example
        example_elements = [
            '"file_path": "$input_file"',
            'USE template variable even though read-file shows "Parameters: none"',
            '"inputs": {',
            '"input_file": {',
            'MUST match the $input_file used above'
        ]

        for element in example_elements:
            if element in prompt:
                print(f"   ✅ Example contains: {element}")
            else:
                print(f"   ❌ Example missing: {element}")
                all_present = False
    else:
        print(f"   ❌ Example section missing!")
        all_present = False

    # Test 3: Check parameter hints integration
    print(f"\n📊 Parameter Hints Check:")
    if "Discovered parameters (use as hints" in prompt:
        print(f"   ✅ Parameter hints section present")
        if "input_file: input.txt" in prompt:
            print(f"   ✅ input_file parameter hint found")
        if "output_file: output.txt" in prompt:
            print(f"   ✅ output_file parameter hint found")
    else:
        print(f"   ❌ Parameter hints section missing!")
        all_present = False

    print(f"\n🏁 Overall Assessment:")
    if all_present:
        print(f"   ✅ All critical elements present - prompt should guide LLM correctly")
        return True
    else:
        print(f"   ❌ Some elements missing - prompt may not fix template issues")
        return False

def test_retry_error_handling():
    """Test that validation errors are properly handled in retry scenarios."""
    print("\n🔬 Testing Retry Error Handling")
    print("=" * 50)

    from pflow.planning.nodes import WorkflowGeneratorNode

    # Create generator node
    generator = WorkflowGeneratorNode()

    # Simulate a retry with template variable validation errors
    prep_result = {
        "model_name": "gpt-4o-mini",
        "temperature": 0.0,
        "user_input": "Read data.csv and extract first column",
        "planning_context": "Mock context",
        "discovered_params": {"csv_file": "data.csv"},
        "browsed_components": {},
        "validation_errors": [
            "Declared input(s) never used as template variable: csv_file_path",
            "Structure: outputs.result: '$invalid.output' should reference valid node output"
        ],
        "generation_attempts": 1,  # This is a retry
    }

    # Build and analyze the retry prompt
    prompt = generator._build_prompt(prep_result)

    print(f"📏 Retry prompt length: {len(prompt)} characters\n")

    # Test retry error handling
    print("🔧 Retry Error Handling Check:")

    if "⚠️ FIX THESE VALIDATION ERRORS from the previous attempt:" in prompt:
        print("   ✅ Error section header present")

        # Check for specific error feedback
        error_checks = [
            "Declared input(s) never used as template variable: csv_file_path",
            "FIX: Use $csv_file_path in the appropriate node's params field",
            'Example: If read-file node, use: "params": {"file_path": "$csv_file_path"}',
            "Keep the rest of the workflow unchanged but FIX the template variable usage"
        ]

        all_error_handling = True
        for check in error_checks:
            if check in prompt:
                print(f"   ✅ {check}")
            else:
                print(f"   ❌ Missing: {check}")
                all_error_handling = False

        return all_error_handling
    else:
        print("   ❌ Error section missing!")
        return False

def main():
    """Run focused template variable tests."""
    print("🔬 Template Variable Fix Verification")
    print("=" * 60)

    # Test 1: Basic prompt structure
    basic_test = test_workflow_generator_prompt_fix()

    # Test 2: Retry error handling
    retry_test = test_retry_error_handling()

    print(f"\n🏁 Final Assessment:")
    print("=" * 60)

    if basic_test and retry_test:
        print("✅ All tests passed - Template variable fix appears complete!")
        print("✅ Prompt should properly guide LLM to use template variables")
        print("✅ Error handling should fix validation issues on retry")
        print("\n📝 Next Steps:")
        print("   1. Test with real LLM calls to verify effectiveness")
        print("   2. Monitor e2e tests to see if validation errors are resolved")
        return True
    else:
        print("❌ Some tests failed - Template variable fix may be incomplete")
        print("❌ Review prompt template for missing guidance")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
