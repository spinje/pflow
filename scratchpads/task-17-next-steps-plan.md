# Task 17 Integration - Next Steps Plan

## Immediate Next Steps

### 1. Understand Current State
**CRITICAL**: The task-17-context-and-implementation-details.md already contains extensive integrations from previous research files. You need to:
1. First read through the ENTIRE document to understand what's already there
2. Identify which patterns/sections came from previous integrations
3. Then check which research files haven't been processed yet

**Check research directory**:
```bash
ls -la /Users/andfal/projects/pflow/.taskmaster/tasks/task_17/research/
```

**Note**: Many files may have already been integrated.

### 2. Continue Research File Analysis
Process remaining research files ONE BY ONE

### 3. For Each File, Follow This Process

#### A. Critical Analysis
1. **Read with skepticism** - Files may contain outdated or incorrect information
2. **Check against source of truth** - `task-17-planner-ambiguities.md` or even better ask the user for clarification
3. **Identify key insights** that align with:
   - Meta-workflow architecture
   - Template variable system
   - LLM-based approach (no hardcoding)

#### B. Extract and Categorize
For each file, identify:
1. **Valid insights** to integrate
2. **Contradictions** with established architecture
3. **Anti-patterns** to document as "what not to do"
4. **Questions** that need clarification

#### C. Integration Approach
1. **Primary target**: Update `task-17-context-and-implementation-details.md`
2. **If fundamental ambiguity**: Update `task-17-planner-ambiguities.md`
3. **If new anti-pattern**: Add to anti-patterns section
4. **If implementation detail**: Add to relevant section

### 4. Key Areas Still Needing Clarity

Based on current understanding, focus on finding information about:

1. **Workflow Storage and Retrieval**
   - When/how are new workflows saved?
   - How does the discovery node search saved workflows?
   - Format of saved workflows with template variables

2. **Error Recovery Specifics**
   - How many retry attempts for each node?
   - What triggers fallback strategies?
   - How are errors communicated to users?

3. **Prompt Engineering Details**
   - Exact prompt structure for workflow generation
   - Examples included in prompts
   - How to guide LLM to generate complete variable_flow

4. **Integration Points**
   - How does planner receive input from CLI?
   - How does confirmation node interact with user?
   - How does execution node invoke workflows?

### 5. Document Structure to Maintain

Keep the following structure in `task-17-context-and-implementation-details.md`:
1. Critical Insight: Meta-Workflow Architecture (KEEP AT TOP)
2. Architectural Decision: PocketFlow for Planner
3. Directory Structure Decision
4. PocketFlow Execution Model
5. Advanced Implementation Patterns
6. Flow Design Patterns
7. Integration Points and Dependencies
8. Testing Patterns
9. Performance Considerations
10. Anti-Patterns to Avoid
11. Template-Driven Workflow Architecture
12. Risk Mitigation Strategies
13. Testing Workflow Generation
14. Semantic Discovery Approach
15. Success Metrics and Targets
16. Open Questions and Decisions Needed
17. Next Steps

### 6. Critical Concepts to Preserve

When analyzing new files, ensure these concepts remain clear:

1. **Meta-Workflow Nature**
   - Planner creates AND executes workflows
   - Parameter extraction → mapping → execution all in planner
   - MVP: Everything goes through planner

2. **Template Variables Sacred**
   - Never hardcode extracted values
   - Always generate with $variables
   - LLM provides complete variable_flow mappings

3. **No Inference or Guessing**
   - LLM generates everything explicitly
   - System only validates
   - No hardcoded patterns or fallbacks

4. **Semantic Discovery**
   - LLM-based matching, no embeddings
   - Context builder provides workflow descriptions
   - "Find or build" in same interface

### 7. Questions to Ask User

If you encounter genuine ambiguities:

1. **Workflow Saving**: Is workflow saving automatic after approval or does user choose?
2. **Discovery Ranking**: Should planner show multiple matches or pick best one?
3. **Parameter Defaults**: How are optional parameters handled?
4. **Execution Feedback**: How verbose should execution output be?

### 8. Final Integration Checklist

After processing all files:

1. [ ] All valid insights integrated
2. [ ] All contradictions documented
3. [ ] All anti-patterns listed
4. [ ] Meta-workflow concept remains clear
5. [ ] Template variable system properly explained
6. [ ] No hardcoded inference logic added
7. [ ] Success metrics included
8. [ ] Testing strategies documented
9. [ ] Implementation structure clear
10. [ ] Open questions updated

### 9. Warning Signs to Watch For

Be suspicious of research files that suggest:
- Hardcoded workflow patterns
- Variable inference logic
- Template fallback systems
- Direct CLI parsing (MVP uses LLM for everything)
- Embedding-based discovery
- Separate execution system

### 10. Remember the Core Truth

The planner is a PocketFlow meta-workflow that:
1. Finds or creates workflows (with templates)
2. Extracts and maps parameters
3. Executes with proper substitution

Everything else is implementation detail that must serve this core architecture.

## Final Note

The integration work is about distilling truth from research while maintaining the architectural integrity established in the ambiguities document. When in doubt, the ambiguities document is the source of truth, and the meta-workflow insight is the key to understanding everything.
