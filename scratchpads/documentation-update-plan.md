# Documentation Update Plan for Template-Driven Workflow Architecture

## 🎯 What We're Doing

Updating documentation to reflect the **template-driven workflow architecture** with:
- $ variable substitution (`$code_report`, `$commit_message`, etc.)
- Context-aware parameter resolution (data flags → shared store, behavior flags → node.set_params())
- Claude Code super node with instruction-based interface
- Sophisticated planner that generates prompts and parameter values
- Shared store inspection capabilities

## 📋 Documentation Update Checklist

### 🔥 MAJOR UPDATES REQUIRED

#### ✅ User Specified Files:

- [ ] **docs/core-node-packages/claude-nodes.md** - MAJOR REWRITE
  - **Issue**: Describes individual nodes (claude-analyze, claude-implement, claude-review, etc.)
  - **Change**: Replace with single `claude-code` super node with instruction-based interface
  - **Impact**: Complete rewrite of node specifications and examples

- [ ] **docs/workflow-analysis.md** - MINOR UPDATES
  - **Issue**: Examples show older workflow patterns
  - **Change**: Update target workflow to match new template-driven approach
  - **Impact**: Update examples to show realistic end-to-end workflow with $ variables (use the one the user provided in the prompt)

- [ ] **docs/architecture.md** - MODERATE UPDATES
  - **Issue**: CLI resolution algorithm doesn't mention context-aware routing
  - **Change**: Add template resolution system and context-aware parameter routing
  - **Impact**: Update CLI resolution section and data flow examples

- [ ] **docs/components.md** - MODERATE UPDATES
  - **Issue**: Component inventory doesn't include template system components
  - **Change**: Add template resolution, shared store inspection, enhanced planner
  - **Impact**: Update MVP component list with new architectural components

- [ ] **docs/planner.md** - MODERATE UPDATES
  - **Issue**: Describes planner as node selector, not prompt/parameter generator
  - **Change**: Update to sophisticated planner that generates contextual prompts and values
  - **Impact**: Update planner responsibilities and workflow generation sections

#### 🔧 Additional Files That Need Updates:

- [ ] **docs/shared-store.md** - MODERATE UPDATES
  - **Issue**: Doesn't describe context-aware parameter resolution
  - **Change**: Update CLI parameter guidelines and template variable handling
  - **Impact**: Add section on data vs behavior parameter classification

- [ ] **docs/cli-runtime.md** - MODERATE UPDATES
  - **Issue**: Doesn't describe template resolution or context-aware routing
  - **Change**: Add template resolution system and parameter classification
  - **Impact**: Update CLI flag handling and parameter resolution sections

- [ ] **docs/schemas.md** - MINOR UPDATES
  - **Issue**: JSON IR schema doesn't include template variables
  - **Change**: Add template variable definitions and parameter classification
  - **Impact**: Enhance IR schema with template metadata

- [ ] **docs/registry.md** - MINOR UPDATES
  - **Issue**: Metadata extraction doesn't distinguish data vs behavior parameters
  - **Change**: Add parameter classification in metadata extraction
  - **Impact**: Update metadata schema and extraction process

### 🟡 MINOR UPDATES REQUIRED

- [ ] **docs/runtime.md** - MINOR UPDATES
  - **Issue**: Execution engine doesn't mention template resolution
  - **Change**: Add template variable substitution in execution pipeline
  - **Impact**: Update execution flow with template resolution step

- [ ] **docs/simple-nodes.md** - MINOR UPDATES
  - **Issue**: Node design principles don't mention template awareness
  - **Change**: Add template variable support to node design
  - **Impact**: Update node interface patterns for template variables

- [ ] **docs/shell-pipes.md** - MINIMAL UPDATES
  - **Issue**: Might need stdin handling updates for template system
  - **Change**: Ensure stdin integration works with template variables
  - **Impact**: Verify stdin → template variable flow

### 🟢 NO UPDATES NEEDED

- [ ] **docs/mvp-scope.md** - NO CHANGES
  - **Reason**: Core MVP scope unchanged, just implementation details enhanced

- [ ] **docs/prd.md** - NO CHANGES
  - **Reason**: Product requirements unchanged, implementation approach evolved

- [ ] **docs/mcp-integration.md** - NO CHANGES
  - **Reason**: v2.0 feature, not affected by template system

- [ ] **docs/autocomplete.md** - NO CHANGES
  - **Reason**: v2.0 feature, not affected by current changes

- [ ] **docs/implementation-details/metadata-extraction.md** - REVIEW NEEDED
  - **Reason**: May need updates for parameter classification

- [ ] **docs/future-version/** - NO CHANGES
  - **Reason**: Future features, not affected by current MVP changes

## 🎯 Update Strategy

### Phase 1: Core Architecture Updates (High Priority)
1. **docs/core-node-packages/claude-nodes.md** - Complete rewrite
2. **docs/architecture.md** - CLI resolution and template system
3. **docs/planner.md** - Sophisticated planner capabilities

### Phase 2: Supporting System Updates (Medium Priority)
4. **docs/components.md** - Add template system components
5. **docs/shared-store.md** - Context-aware parameter resolution
6. **docs/cli-runtime.md** - Template resolution system

### Phase 3: Schema and Registry Updates (Lower Priority)
7. **docs/schemas.md** - Template variable schema
8. **docs/registry.md** - Enhanced metadata extraction
9. **docs/runtime.md** - Template substitution in execution

### Phase 4: Examples and Polish (Lowest Priority)
10. **docs/workflow-analysis.md** - Updated workflow examples
11. **docs/simple-nodes.md** - Template-aware node patterns
12. **docs/shell-pipes.md** - Template integration verification

## 🔧 Specific Changes Per File

### docs/core-node-packages/claude-nodes.md
**MAJOR REWRITE** - Replace individual nodes with super node:
```bash
# OLD: Multiple individual nodes
claude-analyze >> claude-implement >> claude-review

# NEW: Single super node with instructions
claude-code --prompt="<comprehensive_instructions>"
```

### docs/architecture.md
**UPDATE CLI Resolution Algorithm:**
```bash
# Add context-aware routing
--issue=1234 → shared["issue_number"] (data)
--temperature=0.3 → node.set_params({"temperature": 0.3}) (behavior)
```

**ADD Template Resolution System:**
```bash
# Add $ variable substitution
$code_report → shared["code_report"]
$commit_message → shared["commit_message"]
```

### docs/planner.md
**UPDATE Planner Responsibilities:**
- From: "Node selection based on user intent"
- To: "Prompt generation, parameter value creation, template mapping"

### docs/components.md
**ADD New MVP Components:**
- Template resolution system
- Context-aware CLI parameter router
- Shared store inspection utilities
- Enhanced planner with prompt generation

## 🚨 Critical Consistency Points

### 1. Node Architecture Consistency
- **Everywhere**: Confirm individual nodes (github-get-issue) + super nodes (claude-code)
- **Never mention**: action-based nodes (replaced by individual nodes)

### 2. Parameter Resolution Consistency
- **Everywhere**: Data flags → shared store, behavior flags → node.set_params()
- **Never say**: "All CLI flags → node.set_params()" (outdated)

### 3. Workflow Examples Consistency
- **Update all examples** to show realistic end-to-end template-driven workflows
- **Include $ variables** in workflow examples
- **Show planner-generated prompts** rather than user-written prompts

### 4. Planner Capabilities Consistency
- **Everywhere**: Planner generates prompts, instructions, and parameter values
- **Never say**: "Planner just selects nodes" (outdated)

## 🔍 Review Process

For each file:
1. **Read current content** to understand existing descriptions
2. **Identify conflicts** with new template-driven architecture
3. **Make minimal changes** to resolve conflicts while preserving intent
4. **Update examples** to show new workflow patterns
5. **Verify consistency** with other updated documentation

## ⚠️ What NOT to Change

- **Core product vision** and value proposition
- **MVP timeline** and phase structure
- **PocketFlow integration** patterns
- **Individual node philosophy** for simple operations
- **JSON IR → compiled Python** execution approach
- **Two-tier AI approach** (Claude Code + LLM nodes)

## 🎯 Success Criteria

Documentation update is complete when:
- [ ] No contradictions between template-driven architecture and docs
- [ ] All workflow examples show realistic end-to-end patterns
- [ ] Claude Code super node properly documented
- [ ] Context-aware parameter resolution clearly explained
- [ ] Template resolution system documented
- [ ] Enhanced planner capabilities described
- [ ] Shared store inspection utilities documented

This plan ensures we update documentation comprehensively while changing as little as possible and maintaining architectural consistency.
