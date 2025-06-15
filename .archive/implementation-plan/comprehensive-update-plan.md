# Comprehensive Documentation Update Plan: Template-Driven Architecture

## 🎯 What We Actually Understand Now

The planner does **template string composition with variable dependency management**:

1. **Analyzes node metadata** to understand what shared store inputs each node requires
2. **Generates template strings** that populate those inputs with static text + `$variable` references
3. **Tracks variable dependencies** (`$issue` → `shared["issue"]` from github-get-issue output)
4. **Validates dependency flow** ensures all `$variables` can be resolved through workflow execution

**Real Example:**
```bash
github-get-issue >> \
claude-code --prompt="<instructions>
                        1. Understand the problem described in the issue
                        2. Search the codebase for relevant files
                        3. Implement the necessary changes to fix the issue
                        4. Write and run tests to verify the fix
                        5. Return a report of what you have done as output
                      </instructions>
                      This is the issue: $issue" >> \
llm --prompt="Write a descriptive commit message for these changes: $code_report" >> \
git-commit --message="$commit_message"
```

## 📋 Files That Need Updates

### 🔴 CRITICAL ERRORS TO FIX

#### 1. **todo/implementation-roadmap.md** - MAJOR INCONSISTENCIES
**Issues:**
- Line 75: Still lists individual Claude nodes: `claude-analyze`, `claude-implement`, `claude-review`
- Lines 144-148: "Two-Tier AI Approach" section describes individual Claude nodes
- Lines 160-165: Shows old workflow with individual nodes
- Missing template string composition in planning phases
- No mention of variable dependency tracking

**Required Changes:**
- Replace individual Claude nodes with `claude-code` super node
- Update "Two-Tier AI Approach" to show super node + LLM node pattern
- Update example workflows to show template-driven approach
- Add template string composition to Phase 4 planning requirements

#### 2. **docs/components.md** - MISSING TEMPLATE SYSTEM COMPONENTS
**Issues:**
- Line 102: Still lists non-existent individual Claude nodes
- Missing template resolution system components
- Node metadata system doesn't mention template string composition
- No shared store input population components

**Required Changes:**
- Remove individual Claude nodes, add `claude-code` super node
- Add template resolution system components
- Add variable dependency tracking components
- Update node metadata system to include template composition

#### 3. **docs/shared-store.md** - MISSING TEMPLATE INTEGRATION
**Issues:**
- No mention of template variable resolution (`$variable` → `shared["key"]`)
- Missing context-aware parameter resolution details
- No explanation of how template strings populate shared store inputs

**Required Changes:**
- Add template variable resolution section
- Explain context-aware CLI resolution (data flags → shared store, behavior flags → params)
- Show how template strings with $variables work at runtime

### 🟡 FILES I ALREADY UPDATED - NEED VERIFICATION

#### 4. **docs/planner.md** - VERIFY ACCURACY
**What I changed:**
- Updated Section 6.4 to show template string composition response format
- Changed from "instruction generation" to template string composition
- Added JSON IR example with template strings and variable dependencies

**Need to verify:** Is the template string composition process I described accurate?

#### 5. **docs/architecture.md** - VERIFY TEMPLATE SYSTEM
**What I changed:**
- Added context-aware parameter resolution
- Added template resolution system section
- Updated CLI examples to show template variables

**Need to verify:** Is the template resolution process correct?

#### 6. **docs/core-node-packages/claude-nodes.md** - VERIFY SUPER NODE
**What I changed:**
- Complete rewrite from individual nodes to `claude-code` super node
- Added template-driven instruction examples
- Updated all workflow patterns

**Need to verify:** Does this accurately represent the super node approach?

#### 7. **docs/workflow-analysis.md** - VERIFY EXAMPLES
**What I changed:**
- Updated target workflow to show template-driven approach
- Changed debugging examples to show new execution flow
- Updated "Where Intelligence Is Applied" section

**Need to verify:** Are the template-driven workflow examples correct?

## 🔧 Specific Updates Needed

### todo/implementation-roadmap.md Updates

**Lines 75-81: Replace individual Claude nodes**
```diff
- **Claude Code CLI nodes**: `claude-analyze`, `claude-implement`, `claude-review` (project-aware AI agent with file access)
+ **Claude Code super node**: `claude-code` (comprehensive AI-assisted development with planner-generated instructions)
```

**Lines 144-154: Update Two-Tier AI Approach**
```diff
- **Claude Code CLI Nodes** (Development-Specific):
- - `claude-analyze`: Project-aware code/issue analysis with full context
- - `claude-implement`: Code generation with file system access and project understanding
- - `claude-review`: Code review with development tool integration
+ **Claude Code Super Node** (Development-Specific):
+ - `claude-code`: Comprehensive AI development with planner-generated instructions combining analysis, implementation, review, testing
```

**Lines 160-167: Update Primary Workflow**
```diff
- pflow github-get-issue --issue=1234 >>
-   claude-analyze --focus-areas=root-cause >>
-   claude-implement --language=python >>
-   ci-run-tests >>
-   github-create-pr
+ pflow github-get-issue --issue=1234 >> \
+   claude-code --prompt="$comprehensive_fix_instructions" >> \
+   llm --prompt="Write commit message for: $code_report" >> \
+   git-commit --message="$commit_message" >> \
+   github-create-pr --title="Fix: $issue_title" --body="$code_report"
```

### docs/components.md Updates

**Lines 96-102: Update Claude nodes**
```diff
- - **GitHub**: `github-get-issue`, `github-create-issue`, `github-list-prs`, `github-create-pr`, `github-get-files`, `github-merge-pr`
- - **Claude Code CLI**: `claude-analyze`, `claude-implement`, `claude-review`, `claude-explain`, `claude-refactor`
+ - **GitHub**: `github-get-issue`, `github-create-issue`, `github-list-prs`, `github-create-pr`, `github-get-files`, `github-merge-pr`
+ - **Claude Code Super Node**: `claude-code` (comprehensive development with planner-generated instructions)
```

**Add new template system components around line 140:**
```markdown
#### 4.4 Template Resolution System

- **Purpose**: Resolve $variable references to shared store values at runtime
- **Components**:
  - Template string parser for $variable detection
  - Variable dependency tracker
  - Runtime variable substitution engine
  - Template validation and error reporting
  - Integration with shared store for value resolution
```

### docs/shared-store.md Updates

**Add new section around line 35:**
```markdown
## Template Variable Resolution

Template variables (`$variable`) provide dynamic content substitution in node inputs:

### Template String Pattern
```bash
# Template string with $variable
--prompt="<instructions>...This is the issue: $issue"

# At runtime: $issue → shared["issue"] (from previous node output)
--prompt="<instructions>...This is the issue: Button component touch events not working"
```

### Context-Aware CLI Resolution
- **Data flags** (`--issue=1234`) → `shared["issue_number"] = "1234"`
- **Behavior flags** (`--temperature=0.3`) → `node.set_params({"temperature": 0.3})`
- **Template variables** (`$code_report`) → `shared["code_report"]` at runtime
```

## 🎯 Update Priorities

### Phase 1: Fix Critical Inconsistencies
1. **todo/implementation-roadmap.md** - Fix individual Claude nodes references
2. **docs/components.md** - Add template system components, fix Claude nodes

### Phase 2: Add Missing Template Details
3. **docs/shared-store.md** - Add template variable resolution section

### Phase 3: Verify Previous Updates
4. Review all files I already updated to ensure template string composition is accurately described

## ✅ Success Criteria

Documentation is consistent when:
- [ ] No references to individual Claude nodes (`claude-analyze`, `claude-implement`, etc.)
- [ ] All examples show `claude-code` super node with planner-generated instructions
- [ ] Template string composition process is clearly explained
- [ ] Variable dependency tracking (`$variable` → `shared["key"]`) is documented
- [ ] Context-aware parameter resolution is explained
- [ ] All workflow examples show realistic template-driven patterns

## 🚨 Key Questions to Validate

1. **Template String Composition**: Is my understanding of how the planner generates template strings like `"...This is the issue: $issue"` correct?

2. **Variable Resolution**: Is the runtime process of `$issue` → `shared["issue"]` accurate?

3. **Shared Store Input Population**: Does the planner really need to populate ALL node inputs, or just some?

4. **Super Node Instructions**: Are the comprehensive instructions I show for `claude-code` realistic?

This plan ensures all documentation accurately reflects the template-driven architecture with proper variable dependency management and super node design.
