# Critical Decisions for Task 35: Template Syntax Migration

## 1. Saved Workflows Migration - Importance: 4/5

There are 8 existing workflows saved in `~/.pflow/workflows/` that use the current `$variable` syntax. Since the CLAUDE.md states "we are building MVP with NO USERS", these appear to be development/test workflows.

### Context:
- Files like `jokes-for-you.json`, `story-time.json` contain `$topic`, `$model` variables
- No migration mechanism currently exists
- WorkflowManager loads files without version checking

### Options:

- [x] **Option A: Clean break - Document that saved workflows need regeneration**
  - Simple, aligns with "no users" MVP status
  - Developers can easily regenerate their test workflows
  - No migration code complexity

- [ ] **Option B: Write a migration script**
  - Preserves existing workflows
  - Adds complexity for potentially just test data
  - Creates precedent for future migrations

**Recommendation**: Option A - Since we have no users and these are development workflows, a clean break is simpler.

## 2. Escaped Template Syntax - Importance: 3/5

Currently `$$variable` outputs literal `$$variable` (escaped). With new syntax, how should escaping work?

### Context:
- Current: `$$var` → `$$var` (no processing)
- Tests verify this behavior exists
- Used when users want literal `$` in output

### Options:

- [x] **Option A: Use `$${variable}` → `${variable}` (literal output)**
  - Consistent with current escape pattern
  - Intuitive - double `$` means escape
  - Simple to implement

- [ ] **Option B: Use backslash `\${variable}` → `${variable}`**
  - More Unix-like
  - But conflicts with JSON string escaping
  - More complex in practice

**Recommendation**: Option A - Maintains consistency with current escape pattern.

## 3. Variable Name Characters - Importance: 2/5

The proposed regex allows hyphens in variable names: `${user-id}`. Should we add this capability?

### Context:
- Current: Only allows `[a-zA-Z_]\w*` (letters, numbers, underscore)
- Proposed: Could allow `[\w.-]*` (adds hyphen and dot)
- Would be a new feature, not just syntax change

### Options:

- [ ] **Option A: Keep current restrictions (letters, numbers, underscore only)**
  - No new complexity
  - Maintains compatibility with Python variable naming
  - Predictable behavior

- [x] **Option B: Allow hyphens in variable names**
  - More flexible for users
  - Common in other template systems
  - Regex already needs updating anyway

**Recommendation**: Option B - While migrating syntax, adding hyphen support is a small enhancement that improves usability.

## 4. Implementation Strategy - Importance: 3/5

How should we approach the migration implementation?

### Context:
- ~50 source files contain template patterns
- 230+ occurrences in documentation
- Extensive test coverage needs updating

### Options:

- [x] **Option A: Atomic migration - Update everything in one pass**
  - Clean, no temporary dual-syntax code
  - All tests remain consistent
  - Single PR/commit for entire change

- [ ] **Option B: Gradual migration with temporary dual support**
  - More complex regex to support both syntaxes
  - Allows incremental testing
  - Eventually requires cleanup pass

**Recommendation**: Option A - Since we have no users, an atomic migration is cleaner and avoids temporary complexity.

## 5. Prompt Template System - Importance: 1/5

`loader.py` uses `{{variable}}` syntax for prompt templates (different from workflow templates). Should this be touched?

### Context:
- Completely separate template system
- Used for LLM prompt generation, not workflows
- Uses double braces `{{variable}}` not dollar signs

### Options:

- [x] **Option A: Leave prompt templates unchanged**
  - They're a different system
  - No confusion since syntax is already different
  - Avoids scope creep

- [ ] **Option B: Align all template systems**
  - More consistency across codebase
  - But significant additional work
  - Not related to the `$variable` problem

**Recommendation**: Option A - Keep scope focused on workflow templates only.