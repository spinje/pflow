"""Test to see the actual context format sent to LLM."""

from pflow.planning.context_builder import build_planning_context

# Create mock registry metadata for a few nodes
registry_metadata = {
    "read-file": {
        "module": "pflow.nodes.file.read_file",
        "class": "ReadFileNode",
        "interface": {
            "inputs": [
                {"key": "file_path", "type": "str", "description": "Path to the file to read"},
                {"key": "encoding", "type": "str", "description": "File encoding"},
            ],
            "outputs": [
                {"key": "content", "type": "str", "description": "File contents with line numbers"},
                {"key": "error", "type": "str", "description": "Error message if operation failed"},
            ],
        },
        "params": ["file_path", "encoding"],
        "description": "Read content from a file and add line numbers",
    },
    "write-file": {
        "module": "pflow.nodes.file.write_file",
        "class": "WriteFileNode",
        "interface": {
            "inputs": [
                {"key": "content", "type": "str", "description": "Content to write"},
                {"key": "file_path", "type": "str", "description": "Path to the file"},
            ],
            "outputs": [{"key": "written", "type": "bool", "description": "Success status"}],
        },
        "params": ["content", "file_path", "append"],
        "description": "Write content to a file",
    },
    "llm": {
        "module": "pflow.nodes.llm.llm",
        "class": "LLMNode",
        "interface": {
            "inputs": [{"key": "prompt", "type": "str", "description": "Prompt for the LLM"}],
            "outputs": [{"key": "response", "type": "str", "description": "LLM response"}],
        },
        "params": ["prompt", "model", "temperature"],  # model and temperature are exclusive params
        "description": "General-purpose LLM node with model selection",
    },
}

# Build the planning context
context = build_planning_context(
    selected_node_ids=["read-file", "write-file", "llm"],
    selected_workflow_names=[],
    registry_metadata=registry_metadata,
)

print("=" * 80)
print("ACTUAL PLANNING CONTEXT SENT TO LLM:")
print("=" * 80)
print(context)
print("=" * 80)
