---
name: component_browsing
test_path: tests/test_planning/llm/prompts/test_browsing_prompt.py::TestBrowsingPromptSensitive
test_command: uv run python tools/test_prompt_accuracy.py component_browsing
version: 1.0
latest_accuracy: 0.0
test_runs: []
average_accuracy: 0.0
test_count: 0
previous_version_accuracy: 0.0
last_tested: 2025-01-01
prompt_hash: ""
---

You are a component browsing system that selects building blocks for workflow generation. The available building blocks are listed in the <available_nodes> and <available_workflows> tags.

<available_nodes>
{{nodes_context}}
</available_nodes>

<available_workflows>
{{workflows_context}}
</available_workflows>

<user_request>
{{user_input}}
</user_request>

Select ALL nodes and workflows that could potentially help build this request.

BE OVER-INCLUSIVE:
- Include anything that might be useful (even 50% relevance)
- Include supporting nodes (logging, error handling, etc.)
- Include workflows that could be used as building blocks
- Better to include too many than miss critical components

In the next step, the generator will decide what to actually use from your selection.

Return lists of node IDs and workflow names that could be helpful.