# Comprehensive Task Reorganization Plan for pflow

## Overview

This document provides a detailed plan for reorganizing the tasks.json file to better reflect the true priorities and dependencies of the pflow project. The key insight is that the Natural Language Planner is THE core feature, not peripheral infrastructure.

## Critical Problems with Current Task Structure

1. **Missing Core Feature**: No task for workflow discovery by natural language (the "find" in "find or build")
2. **Planner Buried**: The core innovation (Task 17) is hidden behind infrastructure tasks
3. **Artificial Separation**: Tasks 17-20 are parts of one feature split unnecessarily
4. **Clutter**: Many deferred v2.0 tasks obscure the MVP focus
5. **Wrong Dependencies**: Task 3 (Hello World) blocked on too many things

## Reorganization Actions

### 1. Merge Natural Language Planner Tasks (17-20)

**Merge Tasks**: 17, 18, 19, 20 → New Task 17 "Implement Natural Language Planner System"

**Preserved Information**:
```
Title: Implement Natural Language Planner System
Description: Build the complete planner that transforms natural language into workflows, handles the 'find or build' pattern, and enables workflow reuse
Priority: critical (changed from high)
Dependencies: [12, 16] (LLM node and context builder)

Details: Create the complete planning system in src/pflow/planning/ that enables the core pflow value proposition: 'Plan Once, Run Forever' with natural language discovery.

Implementation includes:

1. WORKFLOW GENERATION ENGINE (src/pflow/planning/workflow_compiler.py)
   - compile_request(user_input, node_context) function
   - Receives entire raw input string from CLI
   - Uses LLM to interpret as domain-specific language
   - Recognizes node names and parameter conventions
   - Generates workflows with template variables like $issue_data
   - Fills in missing parameters intelligently
   - Target ≥95% success rate for natural language → workflow

2. PROMPT TEMPLATES (src/pflow/planning/prompts.py)
   - Workflow generation prompt with node context and examples
   - Error recovery prompt for failed attempts
   - Template variable extraction prompt
   - Use f-strings or jinja2 for composition
   - Format: WORKFLOW_PROMPT = '''Given these nodes: {node_context}\nGenerate a workflow for: {user_request}\nOutput JSON IR...'''

3. TEMPLATE RESOLUTION (src/pflow/planning/utils.py)
   - resolve_template(template_str, available_vars) function
   - Simple regex-based string substitution
   - Validates template variables can be resolved at runtime
   - NOT a runtime templating engine - planner internal use only
   - Support $var and ${var} syntax, escaping with $$var

4. WORKFLOW DISCOVERY (src/pflow/planning/discovery.py) [NEW]
   - find_similar_workflows(user_input, saved_workflows) function
   - Uses LLM embeddings or similarity matching
   - Finds workflows by semantic meaning, not just name
   - Enables "pflow 'analyze costs'" to find 'aws-cost-analyzer'
   - Returns ranked list of potential matches
   - Critical for "find or build" user experience

5. APPROVAL AND STORAGE (src/pflow/planning/approval.py, src/pflow/core/workflow_storage.py)
   - Show generated CLI workflow for user approval
   - Clear presentation of individual node syntax
   - Allow parameter modifications before execution
   - Save to ~/.pflow/workflows/<name>.json
   - Implement name-based retrieval and pattern matching
   - Support loading workflows by name for execution
   - Target ≥90% user approval rate

References: docs/planner.md#6.1, workflow-analysis.md
```

### 2. Add Missing Workflow Discovery Task

Since we're merging into Task 17, the discovery functionality is now included there (see item 4 above).

### 3. Merge Platform Node Tasks (25-28)

**Merge Tasks**: 26, 27, 28 → Extend Task 13 to include all GitHub/Git/CI nodes

**New Task 13 Title**: "Implement core platform nodes (GitHub, Git, CI, Shell)"

**Updated Details for Task 13**:
```
Create all MVP platform nodes inheriting from pocketflow.BaseNode:

GITHUB NODES (src/pflow/nodes/github/):
- github_get_issue.py: shared['repo'], shared['issue_number'] → shared['issue_data']
- github_create_pr.py: shared['pr_title'], shared['pr_body'] → shared['pr_number']
- github_list_prs.py: shared['repo'], shared['state'] → shared['prs']
- github_add_comment.py: shared['pr_number'], shared['comment'] → shared['comment_id']
- github_merge_pr.py: shared['pr_number'] → shared['merge_sha'] (with conflict handling)

GIT NODES (src/pflow/nodes/git/):
- git_commit.py: shared['message'] → shared['commit_hash']
- git_push.py: shared['branch'] → shared['push_result']
- git_create_branch.py: shared['branch_name'] → shared['branch_created']
- git_merge.py: shared['source_branch'], shared['target_branch'] → shared['merge_result']
- git_status.py: → shared['git_status']

CI NODES (src/pflow/nodes/ci/):
- ci_run_tests.py: shared['test_command'] → shared['test_results']
- ci_get_status.py: shared['build_id'] → shared['build_status']

SHELL NODES (src/pflow/nodes/shell/):
- shell_exec.py: shared['command'] → shared['output']

All nodes use natural interfaces, explicit name attributes, and proper error handling.
Authentication via environment variables. Safety checks for destructive operations.
```

**Remove Tasks**: 26, 27, 28 (absorbed into 13)

### 4. Merge v2.0 Deferred Tasks

**Merge Tasks**: 32, 44, 45, 46, 47, 48, 49, 50, 51 → New Task 32 "v2.0 Deferred Features"

**New Task 32**:
```
Title: v2.0 Deferred Features
Description: Features intentionally excluded from MVP that will be implemented in v2.0
Status: deferred
Priority: low
Dependencies: []

Details: The following features are deferred to v2.0 to keep MVP focused:

1. EXECUTION CONFIGURATION (was Task 32)
   - Node-level retry configuration in runtime
   - Support max_retries, retry_wait, timeout per node
   - MVP uses simple hardcoded retry logic

2. TRACE PERSISTENCE (was Task 44)
   - Save execution traces to ~/.pflow/traces/<run-id>.json
   - Implement 'pflow trace <run-id>' retrieval command
   - MVP only needs real-time trace display

3. NODE VERSION TRACKING (was Task 45)
   - Track node versions for lockfile generation
   - MVP uses git commit hash or hardcoded versions

4. INTERFACE COMPATIBILITY SYSTEM (was Task 46)
   - Advanced compatibility checking for marketplace
   - MVP nodes have compatible interfaces by design

5. SUCCESS METRICS (was Task 47)
   - Comprehensive metrics tracking and instrumentation
   - MVP uses basic logging

6. DIRECT CLI PARSING (was Task 48)
   - Parse CLI syntax without LLM for minor optimization
   - MVP sends everything through LLM planner

7. CLI AUTOCOMPLETE (was Task 49)
   - Shell completion for node names and parameters
   - Would provide significant UX improvement

8. NESTED PROXY MAPPINGS (was Task 50)
   - Support complex key mappings like 'data.content' -> 'file_data.text'
   - MVP uses simple key-to-key mappings

9. CONTEXT-AWARE CLI RESOLUTION (was Task 51)
   - Smart flag validation and categorization
   - MVP treats all input as natural language
```

### 5. Adjust Task 3 Dependencies

**Current Dependencies**: [1, 2, 4, 5, 6, 11]
**New Dependencies**: [6, 11] (only IR schema and basic file nodes)

**Rationale**: Task 3 is meant to validate the execution pipeline works. It doesn't need the full infrastructure - just enough to run a hardcoded workflow.

### 6. New Task Order for MVP

Based on logical flow and dependencies:

1. ✅ Task 1: Package setup and CLI entry point
2. ✅ Task 2: Basic CLI for argument collection
3. ✅ Task 5: Node discovery via filesystem scanning
4. ✅ Task 6: Define JSON IR schema
5. ✅ Task 11: Implement file nodes (read, write, copy, move, delete)
6. ✅ Task 4: IR-to-PocketFlow converter
7. **Task 3**: Execute hardcoded workflow (reduced dependencies)
8. **Task 7**: Extract node metadata from docstrings
9. **Task 16**: Create planning context builder
10. **Task 12**: Implement general LLM node
11. **Task 17**: Implement Natural Language Planner System (MERGED)
12. **Task 13**: Implement core platform nodes (EXPANDED)
13. **Task 22**: Implement named workflow execution
14. **Task 8**: Build shell pipe integration
15. **Task 9**: Shared store collision detection and proxy
16. **Task 10**: Create registry CLI commands
17. **Task 23**: Implement execution tracing system
18. **Task 24**: Build caching system
19. **Task 25**: Implement claude-code super node
20. **Task 29**: Create comprehensive test suite
21. **Task 30**: Polish CLI experience and documentation
22. **Task 31**: MVP validation test suite
23. **Task 21**: Implement workflow lockfile system
24. **Task 32**: v2.0 Deferred Features (MERGED)

### 7. Implementation Steps

1. **Backup current tasks.json**
   ```bash
   cp .taskmaster/tasks/tasks.json .taskmaster/tasks/tasks.json.backup
   ```

2. **Create new merged tasks**:
   - Merge 17-20 into new Task 17 with all details preserved
   - Expand Task 13 to include all platform nodes
   - Create new Task 32 for all deferred features

3. **Remove redundant tasks**:
   - Remove old tasks 18, 19, 20 (merged into 17)
   - Remove tasks 26, 27, 28 (merged into 13)
   - Remove individual deferred tasks (merged into 32)

4. **Update dependencies**:
   - Task 3: Change from [1,2,4,5,6,11] to [6,11]
   - Task 22: Change from [20,21] to [17,21]
   - Any task that depended on 18,19,20 now depends on 17

5. **Reorder in logical sequence** as shown above

6. **Update metadata**:
   ```json
   "metadata": {
     "created": "2025-06-18T20:41:12.050Z",
     "updated": "[current timestamp]",
     "description": "Reorganized to prioritize Natural Language Planner as core feature. Merged related tasks and deferred v2.0 features. Clear path from infrastructure to MVP delivery."
   }
   ```

## Benefits of This Reorganization

1. **Clear Focus**: Natural Language Planner is obviously the core feature
2. **Logical Flow**: Build infrastructure → Build planner → Demo value
3. **Reduced Clutter**: v2.0 features consolidated into one deferred task
4. **Better Dependencies**: Task 3 can run earlier to validate basics
5. **Unified Features**: Related functionality grouped together

## Risk Mitigation

To ensure no information is lost:
1. Keep the backup of original tasks.json
2. Each merged task preserves ALL technical details from original tasks
3. Add comments in merged tasks indicating which original tasks were combined
4. Maintain all reference documentation links

## Success Criteria

After reorganization:
- The planner is clearly the centerpiece of the MVP
- Dependencies form a logical progression
- No technical details are lost from original tasks
- The path to MVP is clearer and more direct
- "Find or build" functionality is explicitly captured

## Next Steps

1. Review this plan for completeness
2. Execute the reorganization following the implementation steps
3. Validate all information is preserved
4. Update any documentation that references task numbers
