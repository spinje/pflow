# Shared Store Pattern Analysis Across pflow Documentation

## 1. Where the Shared Store Pattern is Formally Defined vs Casually Mentioned

### Canonical Definition Location
- **Primary Source**: `docs/shared-store.md` (575 lines)
  - Most comprehensive and authoritative definition
  - Contains complete architectural rationale, examples, and implementation details
  - Covers all aspects: concept, proxy pattern, params vs shared store guidelines, educational philosophy

### Significant Secondary Explanations
1. **docs/prd.md** (lines 146-228, 2079-2105)
   - Section 3.2 "Shared Store Pattern" provides good overview
   - Section 3.2.1 includes visual diagram
   - Glossary definitions at end
   - References shared-store.md appropriately

2. **docs/architecture.md** (lines 99-156, 461-509)
   - Section 3.2 "The Shared Store Pattern" - brief overview
   - Section 3.3 "Node Autonomy Principle"
   - Section 6 "Data Flow & State Management" with examples
   - No direct reference to shared-store.md

3. **docs/cli-runtime.md** (entire document)
   - Title references shared store explicitly
   - Focuses on CLI runtime implementation details
   - References shared-store.md at top (line 9)
   - Good cross-reference practice

### Casual Mentions Without Proper Context
1. **docs/simple-nodes.md**
   - Multiple mentions in context of node interfaces
   - No reference to canonical definition
   - Assumes reader already understands pattern

2. **docs/planner.md**
   - Mentions throughout in context of flow planning
   - Line 15 mentions "integrates seamlessly with shared store pattern"
   - No reference to canonical definition

3. **docs/pflow-pocketflow-integration-guide.md**
   - Lines 69-93 explain "Shared Store is Just a Dict"
   - Practical implementation advice
   - No reference to canonical definition

## 2. Redundant Explanations That Could Be Consolidated

### Shared Store vs Params Guidelines
**Redundant locations**:
- shared-store.md lines 11-33 (canonical)
- cli-runtime.md lines 209-217 (partial)
- architecture.md lines 511-516 (brief)

**Recommendation**: Keep canonical in shared-store.md, replace others with:
```markdown
> For complete shared store vs params guidelines, see [Shared Store Pattern](./shared-store.md#use-shared-store-vs-params-guidelines)
```

### Node Autonomy/"Dumb Pipes" Principle
**Redundant locations**:
- shared-store.md lines 89-134 (comprehensive)
- architecture.md lines 115-121 (brief)
- prd.md mentions but doesn't explain fully

**Recommendation**: Keep in shared-store.md, add cross-references in others.

### Proxy Pattern Explanation
**Redundant locations**:
- shared-store.md lines 162-221 (canonical with examples)
- cli-runtime.md lines 31-39 (brief)
- architecture.md lines 145-156 (brief)
- prd.md lines 229-260 (overview)

**Recommendation**: Keep detailed explanation in shared-store.md, use brief mentions with cross-references elsewhere.

### Template Variable Resolution
**Redundant locations**:
- shared-store.md lines 37-86 (comprehensive)
- architecture.md lines 226-258 (significant overlap)
- prd.md doesn't cover this well

**Recommendation**: Consolidate in shared-store.md with architecture.md providing implementation-specific details.

## 3. Missing Cross-References to the Canonical Definition

### Files that should reference shared-store.md but don't:
1. **architecture.md** - Explains shared store pattern without linking to canonical doc
2. **simple-nodes.md** - Uses shared store extensively without reference
3. **planner.md** - Discusses integration without linking
4. **pflow-pocketflow-integration-guide.md** - Practical advice without canonical reference

### Recommended cross-reference additions:

**For architecture.md** (after line 103):
```markdown
> For complete architectural rationale and detailed examples, see [Shared Store + Proxy Design Pattern](./shared-store.md)
```

**For simple-nodes.md** (after first mention):
```markdown
> Nodes communicate through the shared store pattern. See [Shared Store Pattern](./shared-store.md) for complete details.
```

**For planner.md** (line 15):
```markdown
The planner integrates seamlessly with the **[shared store pattern](./shared-store.md)**, generating flows...
```

**For pflow-pocketflow-integration-guide.md** (line 31):
```markdown
> For architectural understanding of the shared store pattern, see [Shared Store + Proxy Design Pattern](./shared-store.md)
```

## 4. Which Document Should Be the Single Source of Truth

### Recommendation: `shared-store.md` as Canonical Source

**Reasons**:
1. **Most Comprehensive**: 575 lines covering all aspects
2. **Well-Structured**: Clear sections from overview to implementation
3. **Educational Focus**: Includes learning philosophy and progression
4. **Complete Examples**: Shows simple to complex scenarios
5. **Already Referenced**: cli-runtime.md already treats it as canonical

### Secondary Documents Should Focus On:

**prd.md**:
- High-level strategic overview
- How shared store fits into product vision
- Keep brief explanation with cross-reference

**architecture.md**:
- Implementation architecture specifics
- How shared store integrates with other components
- Data flow examples specific to CLI
- Cross-reference for pattern details

**cli-runtime.md**:
- Runtime implementation details
- CLI flag resolution specifics
- Already has good cross-reference

**planner.md**:
- How planner generates flows using the pattern
- Template variable resolution in planning context
- Add cross-reference

**simple-nodes.md**:
- Practical node implementation examples
- How nodes use natural interfaces
- Add cross-reference

**pflow-pocketflow-integration-guide.md**:
- Practical implementation tips
- Common misconceptions
- Add cross-reference

## 5. Unique Perspectives That Should Be Preserved

### From prd.md:
- Strategic positioning in vision statement
- Competitive differentiation aspects
- Business value proposition

### From architecture.md:
- Specific CLI integration details
- Template resolution system implementation
- Shell pipe integration (`shared["stdin"]`)
- Clear implementation phases and roadmap context

### From cli-runtime.md:
- Detailed parameter resolution algorithm
- CLI flag categorization logic
- Complete execution pipeline examples
- Validation rules table

### From planner.md:
- Template string composition details
- Variable dependency tracking
- How planner generates appropriate shared store schemas

### From simple-nodes.md:
- Real-world business scenario examples
- How general LLM node uses shared store
- Practical interface patterns

### From pflow-pocketflow-integration-guide.md:
- Critical insight that shared store is "just a dict"
- Common implementation traps to avoid
- Practical validation approach

## 6. Redundant Content That Could Be Replaced with Links

### Replace in architecture.md:
Lines 99-156 (shared store pattern basics) with:
```markdown
### 3.2 The Shared Store Pattern

The shared store is pflow's primary innovation for inter-node communication.

> For complete pattern definition, examples, and architectural rationale, see [Shared Store + Proxy Design Pattern](./shared-store.md)

In the context of the CLI architecture, the shared store:
- Receives data from CLI flags and shell pipes
- Flows through the execution pipeline
- Supports template variable resolution
[Keep implementation-specific details...]
```

### Replace in prd.md:
Keep strategic overview but add after line 168:
```markdown
> For complete technical details and implementation patterns, see [Shared Store + Proxy Design Pattern](./shared-store.md)
```

### Consolidate proxy pattern mentions:
Keep detailed explanation only in shared-store.md, replace others with brief mention and link.

## 7. Recommendations for Documentation Improvement

### 1. Add Navigation Helper
Create a brief "Key Concepts" section in README or main docs:
```markdown
## Key Architectural Patterns
- **[Shared Store Pattern](./docs/shared-store.md)** - Core communication mechanism
- **[Simple Nodes](./docs/simple-nodes.md)** - Node design philosophy
- **[Planning System](./docs/planner.md)** - Flow generation approach
```

### 2. Standardize Cross-Reference Format
Use consistent format:
```markdown
> **See also**: [Shared Store Pattern](./shared-store.md#specific-section)
```

### 3. Add "Prerequisites" Section
In documents that assume shared store knowledge:
```markdown
## Prerequisites
This document assumes familiarity with:
- [Shared Store Pattern](./shared-store.md)
- [pocketflow Framework](../pocketflow/__init__.py)
```

### 4. Create Concept Dependency Graph
```
shared-store.md (foundation)
    ├── architecture.md (applies pattern)
    ├── cli-runtime.md (implements pattern)
    ├── simple-nodes.md (uses pattern)
    ├── planner.md (generates for pattern)
    └── pflow-pocketflow-integration-guide.md (practical tips)
```

### 5. Update Each Document's Purpose Statement
Make it clear what each document covers:
- **shared-store.md**: "Canonical definition of the shared store pattern"
- **architecture.md**: "How pflow implements the shared store pattern"
- **cli-runtime.md**: "Runtime implementation of shared store with CLI"
- etc.

## Conclusion

The shared store pattern is well-documented but scattered across multiple files with significant redundancy. Making `shared-store.md` the clear canonical source and adding proper cross-references would greatly improve documentation clarity and maintainability. Each document should focus on its unique perspective while referring to the canonical definition for foundational concepts.
