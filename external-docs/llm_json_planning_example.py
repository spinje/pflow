#!/usr/bin/env python3
"""
Example of using LLM library for structured JSON output in a planning context.

This example shows how to use Simon Willison's LLM library to generate
structured JSON output for workflow planning, similar to what would be
needed in the pflow planning system.
"""

import json
from typing import Any, Optional

import llm
from pydantic import BaseModel, Field


# Define Pydantic models for structured workflow planning
class NodeParameter(BaseModel):
    """Parameter definition for a node"""

    name: str = Field(description="Parameter name")
    type: str = Field(description="Parameter type (string, int, float, bool)")
    required: bool = Field(description="Whether this parameter is required")
    description: Optional[str] = Field(None, description="Parameter description")
    default: Optional[Any] = Field(None, description="Default value if not required")


class NodeDefinition(BaseModel):
    """Definition of a workflow node"""

    id: str = Field(description="Unique identifier for the node")
    name: str = Field(description="Human-readable name of the node")
    type: str = Field(description="Node type (e.g., 'read_file', 'llm', 'write_file')")
    description: str = Field(description="What this node does")
    parameters: dict[str, Any] = Field(description="Parameters for this node")
    inputs: list[str] = Field(description="Required inputs from shared store")
    outputs: list[str] = Field(description="Outputs written to shared store")


class WorkflowTransition(BaseModel):
    """Transition between nodes"""

    from_node: str = Field(description="Source node ID")
    to_node: str = Field(description="Target node ID")
    condition: Optional[str] = Field(None, description="Condition for this transition")


class WorkflowPlan(BaseModel):
    """Complete workflow plan"""

    name: str = Field(description="Workflow name")
    description: str = Field(description="What this workflow accomplishes")
    nodes: list[NodeDefinition] = Field(description="List of nodes in the workflow")
    transitions: list[WorkflowTransition] = Field(description="Transitions between nodes")
    initial_inputs: list[str] = Field(description="Required initial inputs to shared store")
    final_outputs: list[str] = Field(description="Expected final outputs in shared store")


def plan_workflow_with_llm(user_request: str, available_nodes: list[str]) -> WorkflowPlan:
    """
    Use LLM to generate a structured workflow plan based on user request.

    Args:
        user_request: Natural language description of what the user wants
        available_nodes: List of available node types

    Returns:
        WorkflowPlan object with structured plan
    """
    model = llm.get_model("gpt-4o-mini")

    system_prompt = f"""You are a workflow planning assistant for the pflow system.
You must generate structured workflow plans that use available nodes to accomplish tasks.

Available node types: {", ".join(available_nodes)}

Rules:
1. Each node must have a unique ID
2. Use descriptive names for inputs/outputs in shared store
3. Create logical transitions between nodes
4. Ensure data flows correctly through shared store keys
5. Only use nodes from the available list
"""

    response = model.prompt(f"Create a workflow plan for: {user_request}", schema=WorkflowPlan, system=system_prompt)

    return json.loads(response.text())


def generate_node_metadata(node_type: str) -> dict[str, Any]:
    """
    Use LLM to generate metadata for a specific node type.
    """

    class NodeMetadata(BaseModel):
        """Metadata for a node type"""

        type: str = Field(description="Node type identifier")
        display_name: str = Field(description="Human-friendly display name")
        description: str = Field(description="Detailed description of what the node does")
        category: str = Field(description="Category (e.g., 'file', 'text', 'llm', 'data')")
        parameters: list[NodeParameter] = Field(description="Available parameters")
        input_keys: list[str] = Field(description="Expected shared store input keys")
        output_keys: list[str] = Field(description="Shared store output keys produced")
        examples: list[dict[str, Any]] = Field(description="Usage examples")

    model = llm.get_model("gpt-4o-mini")

    response = model.prompt(
        f"Generate comprehensive metadata for a '{node_type}' node in a workflow system",
        schema=NodeMetadata,
        system="You are documenting nodes for a workflow system. Be thorough and accurate.",
    )

    return json.loads(response.text())


def extract_workflow_from_description(description: str) -> dict[str, Any]:
    """
    Extract a structured workflow from a natural language description.
    """

    # Simpler schema using DSL syntax
    simple_schema = llm.schema_dsl("""
        workflow_name,
        workflow_description,
        steps: [{
            step_number int,
            action,
            input_data,
            output_data,
            node_type
        }],
        expected_result
    """)

    model = llm.get_model("gpt-4o-mini")

    response = model.prompt(
        f"Extract a structured workflow from this description:\n\n{description}", schema=simple_schema
    )

    return json.loads(response.text())


def validate_workflow_connections(workflow: WorkflowPlan) -> dict[str, Any]:
    """
    Use LLM to validate workflow connections and suggest improvements.
    """

    class ValidationResult(BaseModel):
        """Workflow validation result"""

        is_valid: bool = Field(description="Whether the workflow is valid")
        issues: list[str] = Field(description="List of identified issues")
        suggestions: list[str] = Field(description="Suggestions for improvement")
        missing_connections: list[dict[str, str]] = Field(description="Missing connections between nodes")
        redundant_nodes: list[str] = Field(description="Nodes that might be redundant")

    model = llm.get_model("gpt-4o-mini")

    workflow_json = json.dumps(
        {
            "nodes": [node.model_dump() for node in workflow.nodes],
            "transitions": [trans.model_dump() for trans in workflow.transitions],
        },
        indent=2,
    )

    response = model.prompt(
        f"Validate this workflow and identify any issues:\n\n{workflow_json}",
        schema=ValidationResult,
        system="You are a workflow validation expert. Check for logical flow, "
        "missing connections, and potential improvements.",
    )

    return json.loads(response.text())


def main():
    """Demonstrate workflow planning with structured JSON output"""

    print("=== Workflow Planning with LLM Structured Output ===\n")

    # Example 1: Plan a simple workflow
    print("--- Example 1: Plan a Text Processing Workflow ---")
    available_nodes = ["read_file", "llm", "write_file", "extract_text", "summarize"]
    user_request = "Read a PDF file, extract its text, summarize it, and save the summary"

    workflow_plan = plan_workflow_with_llm(user_request, available_nodes)
    print(json.dumps(workflow_plan, indent=2))

    # Example 2: Generate node metadata
    print("\n--- Example 2: Generate Node Metadata ---")
    metadata = generate_node_metadata("read_file")
    print(json.dumps(metadata, indent=2))

    # Example 3: Extract workflow from description
    print("\n--- Example 3: Extract Workflow from Description ---")
    description = """
    I need to process customer feedback emails. First, I'll read emails from a folder,
    then extract the sentiment from each email, categorize them as positive, negative,
    or neutral, and finally create a summary report with statistics.
    """
    extracted = extract_workflow_from_description(description)
    print(json.dumps(extracted, indent=2))

    # Example 4: Validate a workflow
    print("\n--- Example 4: Validate Workflow ---")
    # Create a sample workflow with potential issues
    sample_workflow = WorkflowPlan(
        name="Email Processing",
        description="Process customer emails",
        nodes=[
            NodeDefinition(
                id="read_1",
                name="Read Emails",
                type="read_file",
                description="Read email files",
                parameters={"path": "emails/*.txt"},
                inputs=[],
                outputs=["email_content"],
            ),
            NodeDefinition(
                id="sentiment_1",
                name="Analyze Sentiment",
                type="llm",
                description="Extract sentiment",
                parameters={"prompt": "Analyze sentiment"},
                inputs=["email_text"],  # Note: wrong input key
                outputs=["sentiment"],
            ),
        ],
        transitions=[WorkflowTransition(from_node="read_1", to_node="sentiment_1")],
        initial_inputs=[],
        final_outputs=["sentiment"],
    )

    validation = validate_workflow_connections(sample_workflow)
    print(json.dumps(validation, indent=2))

    # Example 5: Using response_json directly
    print("\n--- Example 5: Direct JSON Access ---")
    model = llm.get_model("gpt-4o-mini")
    response = model.prompt(
        "Create a simple data pipeline plan",
        schema=llm.schema_dsl("pipeline_name, steps: [string], data_sources: [string]"),
    )

    # Access JSON directly from response
    result = response.json()
    print("Direct JSON access:", json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
