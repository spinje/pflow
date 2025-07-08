# Plan to Merge implementation-roadmap.md and mvp-scope.md

## Analysis of Current Files

### Overlap Assessment

Both files serve related but slightly different purposes that have significant overlap:

**implementation-roadmap.md**:
- Strategic development roadmap with timeline
- Task-oriented (references tasks.json task numbers)
- 4 phases with specific task groupings
- Timeline estimates (weeks 1-9)
- Parallelization opportunities
- Launch readiness criteria

**mvp-scope.md**:
- Feature-oriented scope definition
- Value proposition and use cases
- What's in/out of MVP
- Success criteria and metrics
- Implementation phases (different from roadmap)
- Acceptance criteria

### Key Overlaps
1. **Implementation Phases** - Both have phases but with different details and organization
2. **Success Metrics** - Similar metrics presented differently
3. **Core Vision** - Both explain the "Plan Once, Run Forever" concept
4. **v2.0 Deferred Features** - Both list the same 8 deferred features
5. **Technical Validation** - Both describe testing and validation approaches
6. **Use Case Examples** - Both show the slash command transformation

### Conflicts/Inconsistencies
1. **Phase Structure**:
   - Roadmap: 4 phases (Foundation, Node Ecosystem, Natural Language, Persistence)
   - MVP Scope: 4 phases (Foundation, Natural Language, Developer Nodes, Workflow Management)
2. **Timeline**: Roadmap has weeks 1-9, MVP scope has weeks 1-8
3. **Task References**: Roadmap references task numbers, MVP scope doesn't

## Proposed Merged Structure

### New File: `docs/features/mvp-implementation-guide.md`

**Rationale**: Combine the strategic roadmap with the scope definition into a single comprehensive implementation guide.

### Proposed Outline

```markdown
# MVP Implementation Guide: From Vision to Reality

## 1. Executive Summary
- Core vision: "Plan Once, Run Forever"
- 40 MVP tasks across 4 phases
- 9-week timeline (with parallelization opportunities for 6-7 weeks)
- Value proposition and success metrics

## 2. Core Vision & Value Proposition
[From mvp-scope.md - the compelling use case examples and transformation story]

## 3. MVP Feature Scope
### What's Included (v0.1)
[From mvp-scope.md - detailed feature descriptions]

### What's Excluded
[Merged list of v2.0 and v3.0 deferred features]

## 4. Implementation Roadmap
### Overview
[From implementation-roadmap.md - the 4-phase structure with task counts]

### Phase 1: Foundation & Core Execution (Weeks 1-3)
[Merge both phase descriptions, keep task references]

### Phase 2: Node Ecosystem & CLI Polish (Weeks 4-5)
[Merge descriptions, include detailed node listings from mvp-scope.md]

### Phase 3: Natural Language Planning (Weeks 6-7)
[Merge descriptions, emphasize this is the core differentiator]

### Phase 4: Persistence, Usability & Optimization (Weeks 8-9)
[Merge descriptions, include acceptance criteria]

### Parallelization Opportunities
[From implementation-roadmap.md - the timeline optimization section]

## 5. Success Metrics & Acceptance Criteria
[Merge both sets of metrics into a comprehensive list]

## 6. Technical Implementation Details
### Development Principles
[From implementation-roadmap.md]

### Critical Dependencies
[From mvp-scope.md - the 8 components that must work together]

### Risk Mitigation
[From implementation-roadmap.md]

## 7. Validation Strategy
[Merge testing approaches from both files]

## 8. Launch Readiness
[Combine launch criteria and acceptance criteria]
```

## Implementation Steps

1. **Create the merged file** `mvp-implementation-guide.md`
2. **Update references** in other docs to point to the new file
3. **Archive or remove** the original two files
4. **Update CLAUDE.md** and index.md to reflect the change

## Benefits of Merging

1. **Single source of truth** for MVP implementation
2. **Eliminates redundancy** between the two files
3. **Clearer narrative** from vision to implementation
4. **Easier to maintain** - one file instead of two
5. **Better for onboarding** - everything in one place

## Potential Concerns

1. **File length** - The merged file will be quite long
   - Mitigation: Good section structure and navigation links
2. **Different audiences** - Some may want just scope, others just roadmap
   - Mitigation: Clear sections allow jumping to relevant parts
3. **Task references** - Not everyone has access to tasks.json
   - Mitigation: Include brief task descriptions inline

## Alternative Approach

If merging seems too aggressive, we could:
1. Keep mvp-scope.md focused on WHAT (features, scope)
2. Keep implementation-roadmap.md focused on HOW (tasks, timeline)
3. Remove overlapping sections and cross-reference heavily
4. Add a clear note at the top of each file explaining the relationship

## Recommendation

**Proceed with the merge**. The overlap is significant enough that maintaining two files creates confusion and maintenance burden. The merged file will be the comprehensive guide for implementing the MVP.

---

# Prompt for New AI Agent

## Context
You are tasked with merging two overlapping documentation files for the pflow project into a single, comprehensive implementation guide. The pflow project is an AI workflow compiler that transforms natural language and CLI pipe syntax into permanent, deterministic CLI commands.

## Your Task
Merge these two files:
1. `docs/features/implementation-roadmap.md` - A strategic development roadmap with timelines and task references
2. `docs/features/mvp-scope.md` - A feature-oriented scope definition with use cases and success criteria

Into a new file:
- `docs/features/mvp-implementation-guide.md`

## Key Requirements

1. **Preserve all unique information** from both files
2. **Eliminate redundancy** where the files overlap
3. **Maintain task number references** from implementation-roadmap.md (these reference tasks.json)
4. **Keep the compelling use case examples** from mvp-scope.md
5. **Create a logical flow** from vision → scope → implementation → validation
6. **Add navigation links** at the top for easy access to sections
7. **Ensure consistency** in phase descriptions and timelines

## Structure to Follow
Use the proposed outline in the merge plan above. The final document should be:
- Comprehensive but well-organized
- Easy to navigate with clear sections
- Suitable for both technical implementers and stakeholders
- Consistent in terminology and timeline references

## Note on components.md

The file `docs/architecture/components.md` was also mentioned but serves a different purpose:
- **Components.md**: Technical inventory of MVP vs v2.0 components with detailed specifications
- **Purpose**: Detailed technical reference for implementers
- **Recommendation**: Keep this separate as a technical reference document

The implementation guide should reference components.md for technical details but not merge with it, as it serves a complementary but distinct purpose.

## Additional Tasks
After creating the merged file:
1. Update `docs/CLAUDE.md` to reference the new file
2. Update `docs/index.md` to reflect the change
3. Add redirect notes in the original files pointing to the new location
4. Ensure all cross-references in other documentation are updated
5. Update components.md to reference the new implementation guide where appropriate

## Quality Checks
- Verify no information is lost from either original file
- Ensure phase descriptions are consistent
- Check that all task numbers still reference correctly
- Confirm timeline adds up (9 weeks total, 6-7 with parallelization)
- Make sure success metrics aren't duplicated

Please proceed with creating the merged documentation file.
