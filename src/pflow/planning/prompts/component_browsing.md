---
name: component_browsing
test_path: tests/test_planning/llm/prompts/test_browsing_prompt.py::TestComponentBrowsingPrompt
test_command: uv run python tools/test_prompt_accuracy.py component_browsing
version: '1.2'
latest_accuracy: 91.7
test_runs: [50.0, 50.0, 91.7, 66.7, 0.0, 91.7]
average_accuracy: 58.4
test_count: 12
previous_version_accuracy: 75.0
last_tested: '2025-08-21'
prompt_hash: c5607421
last_test_cost: 0.07053
---

You are a smart component curator for workflow generation.

## Your Task

Your job is to select the right building blocks (see <available_nodes> and <available_workflows>) based on the user's request (see <user_request>) and requirements (see <extracted_requirements>).

## Selection Process

### Step 1: Consider Extracted Requirements
If requirements have been extracted, use them to guide component selection. Each requirement needs corresponding components to fulfill it.

### Step 2: Identify the Workflow Domain & Complexity
Analyze the user request to understand both domain AND workflow pattern:

**GitHub Domain Patterns**:
- *Simple Read*: "get issue 1234", "summarize issue" → github-get-issue + llm + write-file
- *Analysis Workflow*: "triage issues", "analyze issues" → github-list-issues + llm + write-file
- *Content Creation*: "generate changelog", "create release notes" → github-list-issues + llm + write-file + git-checkout + git-commit + github-create-pr

**Data Processing Domain**: File analysis, CSV processing, report generation
**Cross-Domain**: Explicitly combines GitHub data with local processing

### Step 2: Select Domain-Relevant Components
**Primary Evidence**: Direct functionality match within the identified domain

**GitHub Simple Read** (get/summarize single item):
- `github-get-issue` for single item retrieval
- `llm` for analysis/processing
- output to stdout (default)
- NO save operations unless explicitly mentioned

**GitHub Simple Read and Save** (get/summarize single item):
- `github-get-issue` for single item retrieval
- `llm` for analysis/processing
- `write-file` for output
- NO git operations (no content creation)

**GitHub Analysis Workflow** (analyze multiple items):
- `github-list-issues` for data gathering
- `llm` for processing/analysis
- `write-file` for report output
- NO git operations (analysis only, no commits)

**GitHub Content Creation** (generate/create deliverables):
- `github-list-issues` for data gathering
- `llm` for content generation
- `write-file` for artifact creation
- `git-checkout` + `git-commit` + `github-create-pr` for delivery

**Data Processing Workflows**:
- `read-file` for data input
- `llm` for analysis and processing
- `write-file` for results and reports
- NO GitHub/Git nodes unless explicitly mentioned

**Cross-Domain Workflows** (GitHub data + local processing):
- Include GitHub nodes for data gathering
- Include file/LLM nodes for local processing
- EXCLUDE git operations unless explicitly mentioned

### Step 3: Apply Smart Over-Inclusive Logic

**Include when**:
- Component directly supports the identified domain
- Component provides essential supporting functionality (e.g., LLM for analysis)
- Workflow demonstrates relevant patterns for the domain

**Exclude when**:
- Component belongs to a different domain (e.g., GitHub nodes for pure data processing)
- Component adds unnecessary complexity (e.g., PR creation for simple read operations)
- File management operations not relevant to the workflow (e.g., delete-file for changelog generation)

## Selection Principles

1. **Domain-First**: Stay within the primary workflow domain
2. **Essential Over-Inclusive**: Include related components within the domain, exclude cross-domain noise
3. **Support Analysis**: Include LLM node when processing/analysis is implied
4. **Output Generation**: Include write-file when results need to be saved
5. **Workflow Reuse**: Select existing workflows that match the domain

## Pattern Recognition Examples

**"generate changelog"** → GitHub Content Creation Pattern
✅ Include: github-list-issues, llm, write-file, git-checkout, git-commit, github-create-pr
❌ Exclude: delete-file, move-file (irrelevant), github-get-issue (need list, not single)

**"get GitHub issue 1234 and summarize"** → GitHub Simple Read Pattern
✅ Include: github-get-issue, llm, write-file
❌ Exclude: git-commit, github-create-pr (no content creation), github-list-issues (need single, not list)

**"triage issues"** → GitHub Analysis Pattern
✅ Include: github-list-issues, llm, write-file
❌ Exclude: git-commit (analysis only, no deliverable creation)

**"analyze GitHub issues and generate local report"** → Cross-Domain Pattern
✅ Include: github-list-issues, llm, write-file
❌ Exclude: git-commit (local processing, no GitHub deliverable)

**"analyze data"** → Data Processing Domain
✅ Include: read-file, llm, write-file
❌ Exclude: github-list-issues, git-commit (no GitHub operations needed)

Return node IDs and workflow names that fit the identified domain and support the workflow requirements (see <extracted_requirements>).

## Context

<available_nodes>
{{nodes_context}}
</available_nodes>

<available_workflows>
{{workflows_context}}
</available_workflows>

<user_request>
{{user_input}}
</user_request>

<extracted_requirements>
{{requirements}}
</extracted_requirements>