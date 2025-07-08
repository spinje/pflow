# Kickstart Prompt for Documentation Merge

## Your First Task

Please start by reading these two critical context documents:
1. `/Users/andfal/projects/pflow/scratchpads/pflow-knowledge-braindump.md` - Essential pflow context
2. `/Users/andfal/projects/pflow/scratchpads/merge-roadmap-mvp-scope-plan.md` - The merge plan

## Your Mission

Execute the documentation merge plan to combine:
- `docs/features/implementation-roadmap.md`
- `docs/features/mvp-scope.md`

Into a new unified document:
- `docs/features/mvp-implementation-guide.md`

## Step-by-Step Instructions

1. **Read the context documents** mentioned above to understand pflow and the merge plan

2. **Read the source files** to understand their content:
   - `docs/features/implementation-roadmap.md`
   - `docs/features/mvp-scope.md`

3. **Create the merged file** following the structure outlined in the merge plan:
   ```
   docs/features/mvp-implementation-guide.md
   ```

4. **Key requirements**:
   - Preserve ALL unique information from both files
   - Eliminate redundancy where they overlap
   - Keep task number references from roadmap (e.g., "Task 17")
   - Maintain the compelling use case examples
   - Ensure phases and timelines are consistent
   - Add navigation links at the top

5. **After creating the merged file**:
   - Update `docs/CLAUDE.md` to reference the new file instead of the old ones
   - Update `docs/index.md` to list the new file
   - Add deprecation notices to the original files:
     ```markdown
     > **Note**: This document has been merged into [MVP Implementation Guide](./mvp-implementation-guide.md)
     > Please refer to that document for the most up-to-date information.
     ```

6. **Quality checks**:
   - Verify no information was lost
   - Ensure the Natural Language Planner (Task 17) is prominently featured as THE core feature
   - Check that timeline still shows 9 weeks (6-7 with parallelization)
   - Confirm all success metrics are included

## Important Context

Remember from the braindump:
- The Natural Language Planner is THE core feature of pflow
- Task 17 (which merged tasks 17-20) is the heart of the system
- The "find or build" pattern is what makes pflow unique
- Don't lose any technical details in the merge

## Begin

Start by acknowledging you've read the context documents, then proceed with the merge. Ask questions if anything is unclear before proceeding.
