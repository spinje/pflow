#!/usr/bin/env python3
"""
Debug script to test WorkflowGeneratorNode directly and analyze template variable usage.

This script will:
1. Run WorkflowGeneratorNode with a simple request
2. Log the exact generated workflow
3. Show what's wrong with template variable usage
4. Test the prompt improvements
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
logging.basicConfig(level=logging.DEBUG, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

def setup_environment():
    """Set up environment for testing."""
    # Set environment variable for LLM testing
    os.environ["RUN_LLM_TESTS"] = "1"

    # Check if we have an API key for real LLM calls
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if api_key:
        print(f"✅ Using Anthropic API key: {api_key[:10]}...{api_key[-10:]}")
        return True
    else:
        print("⚠️  ANTHROPIC_API_KEY not found - will analyze prompts only")
        print("   Set it with: export ANTHROPIC_API_KEY='your_key' for real LLM calls")
        return False

def create_mock_planning_context():
    """Create a comprehensive planning context with file operations."""
    return """Available Components:

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
- Outputs:
  - file_content (string): Content of the file

### write-file
**Type**: write-file
**Description**: Write content to a file from shared store
**Parameters**: none
**Reads**: shared['file_path'], shared['file_content']
**Writes**: none (writes to filesystem)
**Interface Format**:
- Inputs:
  - file_path (string, required): Path where to write the file
  - file_content (string, required): Content to write to the file

## Text Processing

### llm
**Type**: llm
**Description**: Process text using a language model
**Parameters**: none
**Reads**: shared['prompt'], shared['model']
**Writes**: shared['llm_response'], shared['llm_usage']
**Interface Format**:
- Inputs:
  - prompt (string, required): The prompt to send to the LLM
  - model (string, optional): The model to use (default: gpt-4o-mini)
- Outputs:
  - llm_response (string): The LLM's response
  - llm_usage (object): Usage statistics from the LLM call
"""

def test_basic_generation(has_api_key=False):
    """Test basic workflow generation with simple file processing request."""
    print("\n🔬 Testing Basic Workflow Generation")
    print("=" * 50)

    from pflow.planning.nodes import WorkflowGeneratorNode

    # Create generator node
    generator = WorkflowGeneratorNode()

    # Create shared store with test data
    shared = {
        "user_input": "Read the file input.txt and write to output.txt",
        "planning_context": create_mock_planning_context(),
        "browsed_components": {
            "read-file": {"type": "read-file", "description": "Read content from a file"},
            "write-file": {"type": "write-file", "description": "Write content to a file"}
        },
        "discovered_params": {
            "input_file": "input.txt",
            "output_file": "output.txt"
        },
        "validation_errors": [],
        "generation_attempts": 0
    }

    try:
        # Run the generator
        print(f"🎯 User Input: {shared['user_input']}")
        print(f"📊 Discovered Params: {shared['discovered_params']}")

        # Prepare data
        prep_result = generator.prep(shared)
        print(f"📋 Prep Result Keys: {list(prep_result.keys())}")

        # Always analyze the prompt
        prompt = generator._build_prompt(prep_result)
        print(f"\n📝 Generated Prompt Analysis:")
        print("=" * 40)
        analyze_prompt(prompt)

        if has_api_key:
            # Execute generation with real LLM
            print("\n🚀 Executing generation with real LLM...")
            exec_result = generator.exec(prep_result)

            # Process result
            result = generator.post(shared, prep_result, exec_result)

            print(f"🎯 Generation Result: {result}")
            print(f"🔢 Generation Attempts: {shared.get('generation_attempts', 'N/A')}")

            # Analyze the generated workflow
            workflow = shared.get("generated_workflow")
            if workflow:
                print("\n📄 Generated Workflow Analysis:")
                print("=" * 30)
                analyze_workflow(workflow)
            else:
                print("❌ No workflow was generated!")
        else:
            print("⏭️  Skipping LLM execution (no API key)")

    except Exception as e:
        print(f"❌ Generation failed: {e}")
        import traceback
        traceback.print_exc()

def test_generation_with_validation_errors(has_api_key=False):
    """Test how generator handles validation errors on retry."""
    print("\n🔬 Testing Generation with Validation Errors")
    print("=" * 50)

    from pflow.planning.nodes import WorkflowGeneratorNode

    # Create generator node
    generator = WorkflowGeneratorNode()

    # Simulate a retry scenario with validation errors
    shared = {
        "user_input": "Read the file data.csv and extract the first column",
        "planning_context": create_mock_planning_context(),
        "browsed_components": {
            "read-file": {"type": "read-file", "description": "Read content from a file"},
            "llm": {"type": "llm", "description": "Process text using a language model"}
        },
        "discovered_params": {
            "csv_file": "data.csv"
        },
        "validation_errors": [
            "Declared input(s) never used as template variable: csv_file_path",
            "Structure: outputs.extraction_result: '$extract_column.result' should reference valid node output"
        ],
        "generation_attempts": 1  # This is a retry
    }

    try:
        print(f"🎯 User Input: {shared['user_input']}")
        print(f"📊 Discovered Params: {shared['discovered_params']}")
        print(f"⚠️ Previous Validation Errors:")
        for error in shared['validation_errors']:
            print(f"   - {error}")

        # Build and examine the prompt
        prep_result = generator.prep(shared)
        prompt = generator._build_prompt(prep_result)

        print(f"\n📝 Retry Prompt Analysis:")
        print("=" * 40)
        analyze_prompt(prompt, focus_on_errors=True)

        if has_api_key:
            # Execute generation with real LLM
            print("\n🚀 Executing retry generation with real LLM...")
            exec_result = generator.exec(prep_result)

            # Process result
            result = generator.post(shared, prep_result, exec_result)

            # Analyze the generated workflow
            workflow = shared.get("generated_workflow")
            if workflow:
                print("\n📄 Retry Generated Workflow Analysis:")
                print("=" * 30)
                analyze_workflow(workflow)
            else:
                print("❌ No workflow was generated on retry!")
        else:
            print("⏭️  Skipping LLM retry execution (no API key)")

    except Exception as e:
        print(f"❌ Retry generation failed: {e}")
        import traceback
        traceback.print_exc()

def analyze_prompt(prompt, focus_on_errors=False):
    """Analyze a generated prompt for key elements."""
    print(f"📏 Prompt Length: {len(prompt)} characters")

    # Check for key sections
    sections = {
        "CRITICAL Requirements": "⚠️ FIX THESE VALIDATION ERRORS" if focus_on_errors else "CRITICAL Requirements:",
        "Template Examples": "EXAMPLE showing proper template variable usage:",
        "Discovered Parameters": "Discovered parameters (use as hints",
        "Validation Errors": "⚠️ FIX THESE VALIDATION ERRORS"
    }

    print(f"\n📝 Prompt Sections Found:")
    for section_name, marker in sections.items():
        if marker in prompt:
            print(f"   ✅ {section_name}")
            if section_name == "Template Examples":
                # Extract and show the example
                try:
                    example_start = prompt.index(marker)
                    # Find the end of the JSON example (look for closing brackets)
                    example_section = prompt[example_start:example_start + 1500]
                    print(f"      📋 Example preview: ...{example_section[50:200]}...")
                except:
                    pass
            elif section_name == "Validation Errors" and focus_on_errors:
                # Extract error handling section
                try:
                    error_start = prompt.index(marker)
                    error_section = prompt[error_start:error_start + 800]
                    print(f"      🔧 Error guidance preview:")
                    lines = error_section.split('\n')[:8]
                    for line in lines:
                        print(f"         {line}")
                except:
                    pass
        else:
            print(f"   ❌ {section_name} - MISSING!")

    # Check for specific template guidance
    template_guidance = [
        "Use template variables ($variable) for ALL dynamic values",
        "Even if a node shows \"Parameters: none\"",
        "This is the \"Exclusive Params\" pattern",
        "Every declared input MUST be used as a template variable"
    ]

    print(f"\n🎯 Template Variable Guidance:")
    for guidance in template_guidance:
        if guidance in prompt:
            print(f"   ✅ '{guidance[:40]}...'")
        else:
            print(f"   ❌ Missing: '{guidance[:40]}...'")

    # Check for parameter hints section
    if "Discovered parameters" in prompt:
        # Extract parameter hints
        try:
            param_start = prompt.index("Discovered parameters")
            param_end = prompt.find("Remember:", param_start)
            if param_end > param_start:
                param_section = prompt[param_start:param_end]
                print(f"\n📊 Parameter Hints Section:")
                print(f"      {param_section}")
        except:
            pass

def analyze_workflow(workflow):
    """Analyze a generated workflow for template variable usage."""
    print(f"📊 Workflow Structure:")
    print(f"   - IR Version: {workflow.get('ir_version', 'N/A')}")
    print(f"   - Nodes: {len(workflow.get('nodes', []))}")
    print(f"   - Edges: {len(workflow.get('edges', []))}")
    print(f"   - Start Node: {workflow.get('start_node', 'N/A')}")

    # Analyze inputs
    inputs = workflow.get('inputs', {})
    print(f"\n🎯 Declared Inputs ({len(inputs)}):")
    if inputs:
        for input_name, input_spec in inputs.items():
            print(f"   - {input_name}: {input_spec.get('description', 'No description')}")
            print(f"     Type: {input_spec.get('type', 'N/A')}, Required: {input_spec.get('required', 'N/A')}")
    else:
        print("   - None declared")

    # Analyze nodes for template variable usage
    nodes = workflow.get('nodes', [])
    print(f"\n🔧 Node Analysis ({len(nodes)}):")
    template_vars_used = set()

    for i, node in enumerate(nodes):
        node_id = node.get('id', f'node_{i}')
        node_type = node.get('type', 'unknown')
        params = node.get('params', {})

        print(f"   Node {i+1}: {node_id} (type: {node_type})")

        # Check params for template variables
        if params:
            print(f"     Params:")
            for param_name, param_value in params.items():
                print(f"       - {param_name}: {param_value}")

                # Check if this is a template variable
                if isinstance(param_value, str) and param_value.startswith('$'):
                    template_var = param_value[1:]  # Remove the $
                    template_vars_used.add(template_var)
                    print(f"         ✅ Uses template variable: {template_var}")
                else:
                    print(f"         ❌ Hardcoded value (should be template?)")
        else:
            print(f"     Params: None")

    # Check for unused inputs
    declared_inputs = set(inputs.keys())
    unused_inputs = declared_inputs - template_vars_used

    print(f"\n🎯 Template Variable Analysis:")
    print(f"   - Template vars used: {template_vars_used}")
    print(f"   - Declared inputs: {declared_inputs}")

    if unused_inputs:
        print(f"   ❌ Unused inputs (validation will fail): {unused_inputs}")
    else:
        print(f"   ✅ All inputs are used as template variables")

    # Analyze outputs
    outputs = workflow.get('outputs', {})
    print(f"\n📤 Outputs ({len(outputs)}):")
    if outputs:
        for output_name, output_spec in outputs.items():
            print(f"   - {output_name}: {output_spec}")
            if isinstance(output_spec, dict):
                print(f"     Description: {output_spec.get('description', 'N/A')}")
            else:
                print(f"     ❌ Should be object with description, not: {type(output_spec)}")
    else:
        print("   - None declared")

def main():
    """Run all debug tests."""
    print("🔬 Debug Script: Testing WorkflowGeneratorNode")
    print("=" * 60)

    has_api_key = setup_environment()

    # Test basic generation
    test_basic_generation(has_api_key)

    # Wait for user input before next test
    print("\n" + "="*60)
    input("Press Enter to continue to retry test...")

    # Test generation with validation errors
    test_generation_with_validation_errors(has_api_key)

    print("\n🏁 Debug testing complete!")

if __name__ == "__main__":
    main()
