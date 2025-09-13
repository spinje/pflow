---
name: metadata_generation
test_path: tests/test_planning/llm/prompts/test_metadata_generation_prompt.py
test_command: uv run python tools/test_prompt_accuracy.py metadata_generation
version: '1.5'
latest_accuracy: 90.0
test_runs: [100.0, 90.0]
average_accuracy: 95.0
test_count: 10
previous_version_accuracy: 50.0
last_tested: '2025-08-22'
prompt_hash: 43623f04
last_test_cost: 0.084984
---

# Metadata Generation Prompt

Analyze this workflow and generate metadata that enables accurate discovery and reuse.

Generate the following metadata:

1. suggested_name (kebab-case, max 50 chars):
   - Make it distinctive and searchable
   - Reflect the primary domain and action
   - Examples: "github-changelog-generator", "csv-data-analyzer", "file-backup-creator"

2. description (100-500 chars):
   - Explain what the workflow accomplishes end-to-end
   - Highlight what's configurable (from optional parameters) and whats required (from required parameters)
   - Mention key technologies if relevant (GitHub, LLM, CSV, etc.)
   - Describe what nodes are used, what their purpose is and how the data flows between them.
   - Focus on value to the user
   - Make sure to mention everything the workflow does

3. search_keywords (2-10 terms):
   - Think: What would users type when looking for this functionality?
   - Extract core concepts from the flow and purposes
   - Include both specific terms (from nodes) and general concepts (from actions)
   - Cover different search angles: domain, action, purpose, technology
   - Dont add too many keywords, just the most relevant ones. Quality over quantity.

4. capabilities (2-10 bullet points):
   - Focus on what users can achieve with this workflow
   - Highlight key configurability from optional parameters
   - Think outcomes, not technical steps
   - Only add capabilities that are actually possible with the workflow.

5. typical_use_cases (1-3 scenarios):
   - Concrete situations where this workflow saves time
   - Focus on the "when" and "why" someone needs this

Goal: Enable users to find this workflow when they need it, understand what it does, and know it fits their use case.

## Notes

Notice: Values in the user input have been replaced with ${parameter_name} to show what's configurable.

Key insight: The workflow stages show WHAT it does, the inputs show WHAT'S CONFIGURABLE.

Important: Keep all metadata generic and reusable. Even though specific values have been replaced with ${parameter_name} in the input, avoid introducing any specific values, time periods, or file names in your metadata.

## Context

<user_input>
{{user_input}}
</user_input>

<workflow_structure>
   <flow>{{node_flow}}</flow>

   <stages>
   {{workflow_stages}}
   </stages>

   <inputs>
   {{workflow_inputs}}
   </inputs>

   <parameter_bindings>
   {{parameter_bindings}}
   </parameter_bindings>
</workflow_structure>

