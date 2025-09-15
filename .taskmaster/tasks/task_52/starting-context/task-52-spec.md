# Feature: planner_requirements_planning

## Objective

Add requirements extraction and planning steps to planner pipeline.

## Requirements

- Planner pipeline must exist
- LLM library must support Conversation class
- Parameter Discovery must produce templatized input
- Component Browsing must select available components
- Workflow Generator must accept conversation context

## Scope

- Does not modify Path A (workflow reuse)
- Does not change existing validation logic
- Does not create new error handler nodes
- Does not modify existing retry limit (3 attempts)
- Does not include all nodes in conversation

## Inputs

- `user_input`: str - Original user request
- `templatized_input`: str - User input with ${param} placeholders
- `discovered_params`: dict[str, str] - Extracted parameter values
- `browsed_components`: dict - Contains node_ids, workflow_names, reasoning fields
- `model_name`: str - LLM model identifier
- `temperature`: float - LLM temperature setting

## Outputs

Side effects:
- `requirements_result` added to shared store by RequirementsAnalysisNode
- `planning_result` added to shared store by PlanningNode
- `planner_conversation` added to shared store by PlanningNode (new Conversation object)
- `planner_conversation` preserved across retries by WorkflowGeneratorNode
- `error` added to shared store on failure

Returns:
- RequirementsAnalysisNode: action string ("success" | "clarification_needed")
- PlanningNode: action string ("continue" | "impossible_requirements" | "partial_solution")

## Structured Formats

```python
class RequirementsSchema(BaseModel):
    is_clear: bool
    clarification_needed: Optional[str]
    steps: list[str]
    estimated_nodes: int
    required_capabilities: list[str]
    complexity_indicators: dict

class ComponentSelection(BaseModel):
    node_ids: list[str]
    workflow_names: list[str]  # Always empty until Task 59
    reasoning: str

class PlanningResult(TypedDict):
    plan_markdown: str
    status: Literal["FEASIBLE", "PARTIAL", "IMPOSSIBLE"]
    node_chain: str
    missing_capabilities: list[str]
```

## State/Flow Changes

- `discovery` - "not_found" → `parameter_discovery` (moved from after to before component_browsing)
- `parameter_discovery` → `requirements_analysis` (new node)
- `requirements_analysis` → `component_browsing`
- `component_browsing` - "generate" → `planning` (new node, replaces direct to parameter_discovery)
- `planning` → `workflow_generator`
- `workflow_generator` - "validate" → `parameter_mapping` → `validator`
- `validator` - "retry" → `workflow_generator` (retry with preserved conversation)

## Constraints

- RequirementsAnalysisNode uses standalone LLM call
- PlanningNode starts new conversation with model.conversation()
- WorkflowGeneratorNode continues conversation from shared["planner_conversation"]
- Maximum 3 validation retries enforced by ValidatorNode
- Planning uses only nodes from browsed_components["node_ids"]
- Requirements output must abstract values
- Current pipeline has Parameter Discovery after Component Browsing (must be moved)

## Rules

1. RequirementsAnalysisNode must extract abstract operations from templatized input.
2. RequirementsAnalysisNode must keep services explicit in requirements.
3. RequirementsAnalysisNode must not include template variables in output.
4. RequirementsAnalysisNode must return "clarification_needed" if input is too vague.
5. PlanningNode must start a new conversation with model.conversation().
6. PlanningNode must include requirements and components in initial prompt.
7. PlanningNode must output markdown with parseable Status field.
8. PlanningNode must output markdown with parseable Node Chain field.
9. PlanningNode must use only nodes from browsed_components.
10. PlanningNode must parse its own markdown output before returning.
11. WorkflowGeneratorNode must use conversation from shared store.
12. WorkflowGeneratorNode must continue conversation for generation.
13. WorkflowGeneratorNode must include validation errors in retry prompt.
14. ComponentBrowsingNode must consider requirements_result in selection.
15. Pipeline must preserve conversation across retries.
16. Flow routing in flow.py must be updated to insert new nodes.

## Edge Cases

- Empty user_input → RequirementsAnalysisNode returns clarification_needed
- No matching components → PlanningNode returns impossible_requirements
- Some requirements cannot be fulfilled → PlanningNode returns partial_solution
- Missing conversation in retry → WorkflowGeneratorNode creates new conversation
- Unparseable planning markdown → PlanningNode returns default FEASIBLE
- Mixed templatized input → RequirementsAnalysisNode handles gracefully
- Conversation exceeds 3 retries → Flow terminates with error

## Error Handling

- Vague input → Route to ResultPreparationNode with clarification message
- Impossible requirements → Route to ResultPreparationNode with alternatives
- Partial solution → Continue with available components or request user decision
- LLM failure → Raise CriticalPlanningError
- Parsing failure → Use default values and continue

## Non-Functional Criteria

- Context caching must reduce retry costs by ≥60%
- Requirements extraction must complete in ≤2 seconds
- Planning must complete in ≤3 seconds
- Conversation memory usage must stay under 100KB

## Examples

### Valid Requirements Extraction
Input: "Get last ${issue_limit} ${issue_state} issues from GitHub repo ${repo_owner}/${repo_name}"
Output: ["Fetch filtered issues from GitHub repository"]

### Impossible Requirements
Requirements: ["Deploy to Kubernetes", "Monitor with Prometheus"]
Components: {"node_ids": ["read-file", "write-file", "llm"], "workflow_names": [], "reasoning": "Selected file and LLM nodes"}
Planning Status: IMPOSSIBLE

### Successful Planning
Requirements: ["Fetch issues from GitHub", "Generate changelog", "Write to file"]
Components: {"node_ids": ["github-list-issues", "llm", "write-file"], "workflow_names": [], "reasoning": "Selected GitHub and file nodes"}
Node Chain: "github-list-issues >> llm >> write-file"

## Test Criteria

1. RequirementsAnalysisNode with clear input produces is_clear=true
2. RequirementsAnalysisNode with vague input produces is_clear=false
3. RequirementsAnalysisNode abstracts "20 closed issues" to "filtered issues"
4. RequirementsAnalysisNode keeps "GitHub" service explicit
5. RequirementsAnalysisNode excludes template variables from steps
6. RequirementsAnalysisNode returns clarification_needed for vague input
7. PlanningNode creates new conversation object
8. PlanningNode includes requirements in initial prompt
9. PlanningNode outputs Status: FEASIBLE for matching components
10. PlanningNode outputs valid node chain format
11. PlanningNode uses only browsed component nodes
12. PlanningNode parses markdown to extract status
13. WorkflowGeneratorNode retrieves conversation from shared
14. WorkflowGeneratorNode continues existing conversation
15. WorkflowGeneratorNode includes errors in retry prompt
16. ComponentBrowsingNode reads requirements_result
17. Conversation persists across 3 retries
18. Empty input triggers clarification_needed
19. No components triggers impossible_requirements
20. Some unmet requirements trigger partial_solution
21. Missing conversation creates new one
22. Unparseable markdown returns FEASIBLE
23. Mixed templatization processes successfully
24. Fourth retry attempt terminates flow
25. ComponentSelection has node_ids, workflow_names, reasoning fields

## Notes (Why)

- Requirements before Planning follows natural WHAT→HOW progression
- Conversation approach leverages context caching for 70% cost reduction
- Standalone calls for extraction keeps conversation focused
- Abstract requirements enable component reusability
- Planning constraints prevent suggesting unavailable components
- Multi-turn conversation enables learning from validation errors

## Compliance Matrix

| Rule # | Covered By Test Criteria # |
| ------ | -------------------------- |
| 1      | 1, 3                      |
| 2      | 4                         |
| 3      | 5                         |
| 4      | 2, 6                      |
| 5      | 7                         |
| 6      | 8                         |
| 7      | 9                         |
| 8      | 10                        |
| 9      | 11                        |
| 10     | 12                        |
| 11     | 13                        |
| 12     | 14                        |
| 13     | 15                        |
| 14     | 16                        |
| 15     | 17                        |
| 16     | 25                        |

## Versioning & Evolution

- v1.0.0 — Initial specification for planner enhancement with requirements and planning steps

## Epistemic Appendix

### Assumptions & Unknowns

- Assumes llm library Conversation class maintains history correctly (verified: exists and works)
- Assumes Anthropic context caching applies to conversation objects
- Assumes templatized_input always available from Parameter Discovery (verified: implemented)
- Assumes workflow_names in ComponentSelection always empty until Task 59 implemented
- Unknown: Exact cost reduction percentage from context caching
- Unknown: Memory growth rate with multiple retries

### Conflicts & Resolutions

- Initial design had all nodes in conversation → Resolution: Only Planning and Generator participate
- Requirements could include template variables → Resolution: Must abstract all values
- Planning could suggest any nodes → Resolution: Constrained to browsed components only
- Assumed coverage_assessment field exists → Resolution: Use ComponentSelection structure with node_ids, workflow_names, reasoning

### Decision Log / Tradeoffs

- Chose two separate nodes over combined node for single responsibility
- Chose multi-turn conversation over context accumulation for simplicity
- Chose new conversation per workflow over reuse for clean state
- Chose Planning parsing its own output over consumer parsing for encapsulation

### Ripple Effects / Impact Map

- Affects flow.py routing configuration
- Affects all planner nodes' prep() methods to pass conversation
- Affects ComponentBrowsingNode prompt building
- Affects WorkflowGeneratorNode retry logic
- May affect performance monitoring for conversation memory

### Residual Risks & Confidence

- Risk: Conversation memory could grow unbounded; Mitigation: 3 retry limit; Confidence: High
- Risk: Context caching might not apply; Mitigation: Still functional without; Confidence: Medium
- Risk: Parsing planning markdown could fail; Mitigation: Default values; Confidence: High

### Epistemic Audit (Checklist Answers)

1. Assumed conversation persistence and caching behavior
2. Wrong assumptions would increase costs but not break functionality
3. Prioritized robustness with fallbacks over elegant parsing
4. All rules have corresponding tests
5. Touches planner pipeline routing and node communication patterns
6. Uncertainty on exact performance gains; Confidence: High on functionality