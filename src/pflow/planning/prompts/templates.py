"""String constants for LLM prompts."""

# Workflow discovery prompt
WORKFLOW_DISCOVERY_PROMPT = """Analyze if existing workflow satisfies the request.

User request: {user_input}
Available workflows: {workflows}

Determine if an existing workflow completely satisfies the request."""

# Workflow generation prompt
WORKFLOW_GENERATION_PROMPT = """You are a workflow planner for pflow, a system that creates deterministic, reusable workflows.

Your task is to generate a complete JSON workflow including:
1. All required nodes in correct sequence
2. Template variables ($var) with path support ($var.field) for dynamic values
3. Natural, descriptive node IDs to avoid collisions
4. Simple, linear workflows (no branching)

{context}

User Request: {user_input}

Important Rules:
- Use $variables in params for dynamic values (e.g., "$issue_number", "$file_path")
- Template variables enable workflow reuse with different parameters
- Use simple, linear sequences (no complex branching for MVP)
- Each node should have a single, clear purpose
- Runtime will handle template substitution

Output only valid JSON matching this structure:
{{
  "ir_version": "0.1.0",
  "nodes": [
    {{"id": "n1", "type": "node-type", "params": {{"key": "$variable", "nested": "$data.field.subfield"}}}}
  ],
  "edges": [
    {{"from": "n1", "to": "n2"}}
  ],
  "start_node": "n1"  // Optional
}}
"""

# Error recovery prompt
ERROR_RECOVERY_PROMPT = """The previous workflow generation failed validation:
{error_message}

Original request: {user_input}

Please generate a corrected workflow that addresses the specific error.
Focus on: {error_hint}

Remember to use template variables ($var) in params for all dynamic values.

Output only valid JSON.
"""

# Template variable extraction prompt
TEMPLATE_VARIABLE_PROMPT = """Given this workflow, identify all template variables used in params:

Workflow: {workflow}

Identify:
1. CLI parameters (e.g., $issue_number, $date)
2. Shared store references (e.g., $issue_data, $content)

Output as JSON:
{{
  "cli_params": ["issue_number", "date"],
  "shared_refs": ["issue_data", "content"]
}}
"""

# Component browsing prompt
COMPONENT_BROWSING_PROMPT = """User wants to: {user_input}

Available components:
{discovery_context}

Select ALL workflows and nodes that would help achieve this goal.
Focus on: Would executing these components satisfy what the user wants?
Be over-inclusive - it's better to include too many than miss important ones.

Return lists of:
- node_ids: Potentially useful nodes
- workflow_names: Potentially useful workflows
"""

# Parameter discovery prompt
PARAMETER_DISCOVERY_PROMPT = """Extract parameters with appropriate names from: "{user_input}"

Examples:
- "generate changelog from last 20 closed issues" → {{"state": "closed", "limit": "20"}}
- "analyze report.pdf from yesterday" → {{"file_path": "report.pdf", "date": "2024-01-15"}}
- "deploy version 2.1.0 to staging" → {{"version": "2.1.0", "environment": "staging"}}

Return a JSON object with parameter names and values.
Consider context to choose appropriate parameter names.
"""
