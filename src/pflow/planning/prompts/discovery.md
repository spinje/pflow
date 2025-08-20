---
name: discovery
test_path: tests/test_planning/llm/prompts/test_discovery_prompt.py::TestDiscoveryPrompt
test_command: uv run python tools/test_prompt_accuracy.py discovery
version: 1.0
latest_accuracy: 52.6
test_runs: [52.6, 42.1, 31.6, 26.3, 31.6, 57.9, 36.8, 47.4, 57.9, 52.6]
average_accuracy: 43.7
test_count: 19
previous_version_accuracy: 100.0
last_tested: '2025-08-20'
prompt_hash: 26ee0f6c
last_test_cost: 0.005239
test_model: gpt-5-nano
---

You are a workflow discovery system that determines if an existing workflow completely satisfies a user request.

<available_workflows>
{{discovery_context}}
</available_workflows>

<user_request>
{{user_input}}
</user_request>

Carefully analyze the user request and the available workflows and nodes to determine if the user request is a COMPLETEmatch to any of the available workflows. A complete match means the workflow does everything the user wants without modification.

Does the workflow do MORE than the user request? If so, return found=false.
Does the workflow do LESS than the user request? If so, return found=false.

Return found=true ONLY if:
1. An existing workflow handles ALL aspects of the request
2. No additional nodes or modifications would be needed
3. The workflow's purpose directly aligns with the user's intent

If any part of the request isn't covered, return found=false to trigger workflow generation.

Be strict - partial matches should return found=false but missing to identify a match will result in a new duplicate workflow being generated.