---
name: metadata_generation
test_path: none
test_command: uv run python tools/test_prompt_accuracy.py metadata_generation
version: 1.0
latest_accuracy: 0.0
test_runs: []
average_accuracy: 0.0
test_count: 0
previous_version_accuracy: 0.0
last_tested: 2025-01-01
prompt_hash: ""
---

# Metadata Generation Prompt

Analyze this workflow and generate high-quality metadata for future discovery.

<original_request>
{{user_input}}
</original_request>

<workflow_structure>
   <nodes>{{nodes_summary}}</nodes>
   <inputs>{{workflow_inputs}}</inputs>
   <discovered_parameters>{{discovered_params}}</discovered_parameters>
</workflow_structure>

CRITICAL REQUIREMENT: Generate metadata that enables this workflow to be found with various search queries.

CRITICAL RULES for description and keywords:
- NEVER include specific parameter values (like "30 issues" or "pflow repo")
- NEVER mention specific file names or paths from the user's request
- DO describe capabilities generically ("fetches closed issues", not "fetches 30 issues")
- DO focus on what the workflow CAN do, not what it WAS configured to do
- Example BAD: "Fetches the last 30 closed issues from pflow repo"
- Example GOOD: "Fetches closed issues from any GitHub repository"

The workflow is REUSABLE with different parameters - the metadata must reflect this!

Generate the following metadata:

1. suggested_name (kebab-case, max 50 chars):
   - Concise, memorable, searchable
   - Indicates primary function
   - Examples: "github-changelog-generator", "issue-triage-analyzer"

2. description (100-500 chars):
   - Explain WHAT it does, WHY it's useful, WHEN to use it
   - Include key technologies (GitHub, LLM, etc.)
   - Make it searchable - think about different phrasings
   - Focus on value, not implementation

3. search_keywords (3-10 terms):
   - Alternative ways users might search for this
   - Include synonyms and related concepts
   - Think: What would someone type when looking for this?
   - Example: "changelog" → also include "release notes", "version history"

4. capabilities (2-6 bullet points):
   - What this workflow can do
   - User-focused benefits
   - Example: "Fetches GitHub issues", "Categorizes changes automatically"

5. typical_use_cases (1-3 scenarios):
   - Real-world problems it solves
   - When someone would use this
   - Example: "Preparing release documentation"

REMEMBER: The metadata determines whether this workflow will be discovered and reused.
Poor metadata means duplicate workflows will be created instead of reusing this one.