#!/usr/bin/env python3
"""
Practical example showing how to use the template system TODAY.
This can be run immediately without waiting for the planner (Task 17).
"""

import json
import os
import tempfile

from pflow.registry import Registry
from pflow.runtime.compiler import compile_ir_to_flow


def main():
    """Demonstrate template system with a real use case."""

    # 1. Define a reusable workflow for processing documents
    document_processor_workflow = {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": "read_input",
                "type": "read-file",
                "params": {"file_path": "$input_document", "encoding": "$encoding"},
            },
            {
                "id": "process_content",
                "type": "write-file",  # Using write-file as example processor
                "params": {
                    "file_path": "$output_document",
                    "content": "$content",  # Will come from read_input via shared store
                    "encoding": "$encoding",
                    "overwrite": True,
                },
            },
        ],
        "edges": [{"from": "read_input", "to": "process_content"}],
    }

    # 2. Create test files
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create input files
        doc1 = os.path.join(tmpdir, "report_2024_01.txt")
        doc2 = os.path.join(tmpdir, "report_2024_02.txt")

        with open(doc1, "w") as f:
            f.write("January 2024 Sales Report\nTotal: $50,000")

        with open(doc2, "w") as f:
            f.write("February 2024 Sales Report\nTotal: $65,000")

        # 3. Process multiple documents with same workflow
        registry = Registry()

        print("Processing multiple documents with template-based workflow...\n")

        for month, input_file in [("January", doc1), ("February", doc2)]:
            output_file = os.path.join(tmpdir, f"processed_{month.lower()}.txt")

            # These parameters would come from:
            # - CLI arguments (pflow run --input-document X --output-document Y)
            # - Configuration files
            # - User prompts
            # - Task 17 planner (future)
            initial_params = {"input_document": input_file, "output_document": output_file, "encoding": "utf-8"}

            print(f"Processing {month} report...")
            print(f"  Input: {input_file}")
            print(f"  Output: {output_file}")

            # Compile and run with specific parameters
            flow = compile_ir_to_flow(document_processor_workflow, registry, initial_params=initial_params)

            shared = {}
            flow.run(shared)

            # Verify output
            with open(output_file) as f:
                content = f.read()
                # Note: read-file adds line numbers
                print(f"  Result: {content[:50]}...")
            print()

        # 4. Show how to save and load workflows
        workflow_file = os.path.join(tmpdir, "document_processor.json")
        with open(workflow_file, "w") as f:
            json.dump(document_processor_workflow, f, indent=2)

        print(f"Workflow saved to: {workflow_file}")
        print("\nTo reuse this workflow:")
        print("1. Load the JSON file")
        print("2. Provide different initial_params")
        print("3. Compile and run")

        # 5. Example of runtime parameter resolution
        print("\n--- Runtime Resolution Example ---")

        workflow_with_mixed_params = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "writer",
                    "type": "write-file",
                    "params": {
                        "file_path": "$output_path",  # From initial_params
                        "content": "$processed_content",  # From shared store at runtime
                        "encoding": "utf-8",
                    },
                }
            ],
            "edges": [],
        }

        # Only provide output_path initially
        flow = compile_ir_to_flow(
            workflow_with_mixed_params,
            registry,
            initial_params={"output_path": os.path.join(tmpdir, "runtime_example.txt")},
            validate=False,  # Skip validation since processed_content comes at runtime
        )

        # Provide content at runtime via shared store
        shared = {"processed_content": "This content was provided at runtime!"}
        flow.run(shared)

        print("Runtime resolution completed!")
        with open(os.path.join(tmpdir, "runtime_example.txt")) as f:
            print(f"Content: {f.read()}")


def advanced_example():
    """Show more advanced template usage patterns."""

    # Example with nested parameters and path traversal
    api_workflow = {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": "config_writer",
                "type": "write-file",
                "params": {
                    "file_path": "$paths.config",
                    "content": json.dumps({
                        "api": {
                            "endpoint": "$api.base_url",
                            "version": "$api.version",
                            "auth": {"type": "$auth.method", "token": "$auth.credentials.token"},
                        },
                        "options": {"timeout": "$timeouts.api", "retries": "$timeouts.max_retries"},
                    }),
                },
            }
        ],
        "edges": [],
    }

    # Complex nested parameters
    params = {
        "paths": {"config": "api_config.json"},
        "api": {"base_url": "https://api.example.com", "version": "v2"},
        "auth": {"method": "bearer", "credentials": {"token": "secret-token-123"}},
        "timeouts": {"api": 30, "max_retries": 3},
    }

    registry = Registry()
    flow = compile_ir_to_flow(api_workflow, registry, initial_params=params)
    flow.run({})

    print("\nAdvanced example completed!")
    print("Generated config file with nested template resolution")


def cli_simulation():
    """Simulate how CLI will work with templates (preview of future)."""

    print("\n--- Future CLI Usage (Simulation) ---")
    print("$ pflow run process_images --input-dir ./photos --output-dir ./processed --format webp")
    print("\nThis would translate to:")
    print("""
    initial_params = {
        "input_dir": "./photos",
        "output_dir": "./processed",
        "format": "webp"
    }
    """)

    print("\nOr with natural language (Task 17):")
    print('$ pflow run "convert all images in photos folder to webp format"')
    print("\nPlanner would extract the same parameters automatically!")


if __name__ == "__main__":
    main()
    # advanced_example()  # Uncomment to see advanced patterns
    # cli_simulation()   # Uncomment to see future CLI usage
