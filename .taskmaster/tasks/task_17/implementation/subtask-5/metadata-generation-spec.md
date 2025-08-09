# MetadataGenerationNode LLM Enhancement Specification

## Critical Issue Identified

The current MetadataGenerationNode implementation uses simple string manipulation instead of LLM analysis, which **fundamentally breaks Path A (workflow reuse)**. Without high-quality, searchable metadata, workflows cannot be discovered for reuse, defeating the "Plan Once, Run Forever" philosophy.

## The Problem with Current Implementation

### Current Approach (String Manipulation)
```python
# Current: Simple, inadequate metadata
suggested_name = user_input.lower()[:30].split()  # "create-changelog-from"
description = user_input[:100]  # "Create a changelog by fetching the last 30 closed issues from..."
```

### Why This Fails
1. **Poor Discoverability**: Future searches won't match truncated descriptions
2. **No Semantic Understanding**: Misses what the workflow actually does
3. **Breaks Path A**: Users create duplicate workflows instead of reusing existing ones

### Real-World Impact Example
```
Day 1: User says "Create a changelog by fetching the last 30 closed issues from github repo pflow"
       → Saves with description: "Create a changelog by fetching the last 30 closed issues from github repo pflow"

Day 7: User says "generate release notes"
       → WorkflowDiscoveryNode searches... NO MATCH (doesn't contain "release notes")
       → Creates DUPLICATE workflow

Day 14: User says "make a changelog"
       → WorkflowDiscoveryNode searches... NO MATCH (description too specific)
       → Creates ANOTHER DUPLICATE

Result: 3 identical workflows, Path A completely broken
```

## Proposed LLM-Based Solution

### Core Concept
Use LLM to analyze the generated workflow and create **rich, searchable metadata** that captures:
- Multiple ways users might describe the need
- The actual problem being solved
- Key technologies and integrations used
- Input/output expectations

### Example of Quality Metadata

```json
{
  "suggested_name": "github-changelog-generator",
  "description": "Automated changelog generation from GitHub issues. Fetches closed issues from a repository, analyzes them using LLM to categorize changes (features, fixes, breaking changes), and produces formatted markdown suitable for release notes. Ideal for release documentation, sprint summaries, and project history tracking. Works with any GitHub repository, customizable issue count and date ranges.",
  "search_keywords": [
    "changelog",
    "release notes",
    "github issues",
    "release documentation",
    "sprint summary",
    "version history",
    "change summary",
    "issue analysis"
  ],
  "capabilities": [
    "Fetches GitHub issues",
    "Categorizes changes",
    "Generates markdown",
    "Supports date filtering"
  ]
}
```

## Detailed Implementation Specification

### 1. Pydantic Model for Structured Output

```python
from pydantic import BaseModel, Field
from typing import List, Optional

class WorkflowMetadata(BaseModel):
    """Structured metadata for workflow discovery and reuse."""

    suggested_name: str = Field(
        description="Concise, searchable name in kebab-case (max 50 chars)",
        max_length=50,
        pattern="^[a-z0-9]+(?:-[a-z0-9]+)*$"
    )

    description: str = Field(
        description="Comprehensive description for discovery (100-500 chars)",
        min_length=100,
        max_length=500
    )

    search_keywords: List[str] = Field(
        description="Alternative terms users might search for",
        min_items=3,
        max_items=10
    )

    capabilities: List[str] = Field(
        description="What this workflow can do (bullet points)",
        min_items=2,
        max_items=6
    )

    typical_use_cases: List[str] = Field(
        description="When/why someone would use this",
        min_items=1,
        max_items=3
    )
```

### 2. Enhanced MetadataGenerationNode Implementation

```python
class MetadataGenerationNode(Node):
    """Generates high-quality metadata using LLM analysis.

    Path B only: Creates searchable metadata that enables Path A reuse.
    Critical for workflow discoverability and the two-path architecture.
    """

    def __init__(self, wait: int = 0) -> None:
        """Initialize metadata generator."""
        super().__init__(wait=wait)
        self.name = "metadata_generator"

    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        """Prepare workflow and context for LLM analysis."""
        return {
            "workflow": shared.get("generated_workflow", {}),
            "user_input": shared.get("user_input", ""),
            "planning_context": shared.get("planning_context", ""),
            "discovered_params": shared.get("discovered_params", {}),
            "model_name": self.params.get("model", "anthropic/claude-sonnet-4-0"),
            "temperature": self.params.get("temperature", 0.3),  # Lower for consistency
        }

    def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
        """Use LLM to generate high-quality searchable metadata."""
        from pflow.planning.utils.llm_helpers import parse_structured_response
        import llm
        import json

        workflow = prep_res.get("workflow", {})

        # Build comprehensive prompt for metadata generation
        prompt = self._build_metadata_prompt(
            workflow=workflow,
            user_input=prep_res.get("user_input", ""),
            discovered_params=prep_res.get("discovered_params", {})
        )

        # Get LLM to analyze and generate metadata
        model = llm.get_model(prep_res["model_name"])
        response = model.prompt(
            prompt,
            schema=WorkflowMetadata,
            temperature=prep_res["temperature"]
        )

        # Parse the structured response
        metadata = parse_structured_response(response, WorkflowMetadata)

        # Extract additional workflow info
        return {
            "suggested_name": metadata.suggested_name,
            "description": metadata.description,
            "search_keywords": metadata.search_keywords,
            "capabilities": metadata.capabilities,
            "typical_use_cases": metadata.typical_use_cases,
            "declared_inputs": list(workflow.get("inputs", {}).keys()),
            "declared_outputs": self._extract_outputs(workflow),
        }

    def _build_metadata_prompt(self, workflow: dict, user_input: str,
                               discovered_params: dict) -> str:
        """Build comprehensive prompt for metadata generation."""
        import json

        # Analyze workflow to understand what it does
        nodes_summary = self._summarize_nodes(workflow.get("nodes", []))

        return f"""Analyze this workflow and generate high-quality metadata for future discovery.

ORIGINAL USER REQUEST:
{user_input}

WORKFLOW STRUCTURE:
{json.dumps(workflow, indent=2)}

WORKFLOW ANALYSIS:
- Nodes used: {nodes_summary}
- Inputs required: {', '.join(workflow.get('inputs', {}).keys()) or 'none'}
- Parameters discovered: {', '.join(discovered_params.keys()) if discovered_params else 'none'}

GENERATION REQUIREMENTS:

1. suggested_name:
   - Concise, memorable, searchable
   - Kebab-case, max 50 characters
   - Should indicate primary function
   - Examples: "github-changelog-generator", "issue-triage-analyzer"

2. description:
   - 100-500 characters
   - Explain WHAT it does, WHY it's useful, WHEN to use it
   - Include key technologies (GitHub, LLM, etc.)
   - Make it searchable - think about how users might describe this need
   - Avoid implementation details, focus on value

3. search_keywords:
   - 3-10 alternative terms users might search for
   - Include synonyms and related concepts
   - Think about different ways to describe the same need
   - Examples: "changelog" → ["release notes", "version history", "change log"]

4. capabilities:
   - 2-6 bullet points of what this workflow can do
   - Focus on user value, not technical details
   - Examples: "Fetches GitHub issues", "Categorizes changes automatically"

5. typical_use_cases:
   - 1-3 scenarios when someone would use this
   - Real-world problems it solves
   - Examples: "Preparing release documentation", "Creating sprint summaries"

CRITICAL: The description and keywords determine whether this workflow will be found and reused.
Think about discoverability - what would someone type when looking for this functionality?"""

    def _summarize_nodes(self, nodes: list) -> str:
        """Summarize the types of nodes used."""
        node_types = [node.get("type", "unknown") for node in nodes]
        unique_types = list(dict.fromkeys(node_types))  # Preserve order, remove duplicates
        return ", ".join(unique_types[:5])  # Limit to first 5 for brevity
```

### 3. Impact on WorkflowDiscoveryNode

The enhanced metadata directly improves discovery:

```python
# WorkflowDiscoveryNode can now search across:
# - description (rich, comprehensive)
# - search_keywords (alternative terms)
# - capabilities (what it does)
# - typical_use_cases (when to use it)

# This dramatically increases Path A success rate
```

## Testing Strategy

### 1. Unit Tests (test_validation.py)

```python
def test_metadata_generation_uses_llm():
    """Verify LLM is called for metadata generation."""

def test_metadata_includes_search_keywords():
    """Verify search keywords are extracted."""

def test_metadata_description_quality():
    """Verify description is comprehensive and searchable."""
```

### 2. LLM Tests (test_planning/llm/behavior/)

```python
def test_metadata_enables_discovery():
    """Test that generated metadata allows workflow to be found."""
    # Generate metadata for "github changelog" workflow
    # Then verify it can be found with queries like:
    # - "release notes"
    # - "sprint summary"
    # - "issue summary"
    # - "version history"
```

### 3. Integration Tests

```python
def test_path_a_reuse_after_metadata_generation():
    """Verify Path A works after Path B generates metadata."""
    # 1. Generate workflow with Path B
    # 2. MetadataGenerationNode creates rich metadata
    # 3. Save workflow
    # 4. New query with different wording
    # 5. Verify WorkflowDiscoveryNode finds it (Path A)
```

## Success Metrics

1. **Discovery Rate**: >80% of semantically similar queries find existing workflows
2. **Metadata Quality**: Descriptions average 200-400 chars with 5+ search keywords
3. **Path A Usage**: >60% of requests reuse existing workflows (after initial creation)
4. **User Satisfaction**: Workflows are found with natural language variations

## Migration Plan

1. **Update MetadataGenerationNode**: Implement LLM-based generation
2. **Add WorkflowMetadata model**: Create Pydantic model for structured output
3. **Update tests**: Add new tests for LLM-based metadata
4. **Update WorkflowManager**: Store additional metadata fields (search_keywords, etc.)
5. **Enhance WorkflowDiscoveryNode**: Search across all metadata fields

## Risk Mitigation

### Risk 1: LLM Generates Poor Metadata
**Mitigation**:
- Use structured output with validation
- Provide detailed prompt with examples
- Test with multiple queries
- Fallback to basic extraction if LLM fails

### Risk 2: Increased Latency
**Mitigation**:
- Cache metadata after generation
- Use faster model for metadata (claude-3-haiku)
- Run metadata generation async (future)

### Risk 3: Search Keywords Don't Match
**Mitigation**:
- Generate diverse keywords
- Include synonyms and related terms
- Test discovery with real queries

## Conclusion

This enhancement is **CRITICAL** for Task 17's success. Without high-quality, searchable metadata:
- Path A (workflow reuse) fails
- Users create duplicate workflows
- "Plan Once, Run Forever" philosophy breaks

With LLM-generated metadata:
- Workflows are discoverable with natural language
- Path A succeeds most of the time
- System truly delivers on its promise

The implementation adds complexity but is absolutely necessary for the two-path architecture to function correctly.