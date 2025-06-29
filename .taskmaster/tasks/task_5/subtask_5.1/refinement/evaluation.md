# Evaluation for Subtask 5.1

## Ambiguities Found

### 1. Import Path Resolution - Severity: 4

**Description**: How should the scanner convert file paths to importable module names when pocketflow is not installed as a package?

**Why this matters**: Without proper import path resolution, importlib.import_module() will fail to find modules

**Options**:
- [x] **Option A**: Add both pflow root and pocketflow to sys.path temporarily during scanning
  - Pros: Simple, works with current structure, allows importing both pflow and pocketflow modules
  - Cons: Modifies global state temporarily
  - Similar to: Common pattern in Python test runners

- [ ] **Option B**: Calculate relative imports based on package structure
  - Pros: No sys.path modification
  - Cons: Complex path manipulation, fragile with package changes
  - Risk: Breaks if package structure changes

**Recommendation**: Option A because it's simpler and more robust for the MVP

### 2. Test Node Structure - Severity: 2

**Description**: Should the test node inherit from BaseNode or Node?

**Why this matters**: Sets precedent for future node implementations

**Options**:
- [ ] **Option A**: Inherit from BaseNode (the fundamental class)
  - Pros: Tests the core requirement, simpler
  - Cons: Doesn't test Node detection
  - Similar to: Minimal examples in cookbook

- [x] **Option B**: Create two test nodes - one BaseNode, one Node
  - Pros: Tests both inheritance patterns, better coverage
  - Cons: Slightly more work
  - Risk: None significant

**Recommendation**: Option B for comprehensive testing

### 3. Error Handling Strategy - Severity: 3

**Description**: How should the scanner handle import errors for individual files?

**Why this matters**: Some Python files may have syntax errors or missing dependencies

**Options**:
- [x] **Option A**: Log errors and continue scanning, return partial results
  - Pros: Robust, doesn't fail entire scan for one bad file
  - Cons: May miss nodes in problematic files
  - Similar to: Task 2's error handling philosophy

- [ ] **Option B**: Fail fast on first error
  - Pros: Clear failure indication
  - Cons: One bad file breaks everything
  - Risk: Poor user experience

**Recommendation**: Option A for graceful degradation

## Conflicts with Existing Code/Decisions

### 1. Directory Creation Responsibility

- **Current state**: No src/pflow/nodes/ directory exists
- **Task assumes**: Directory already exists for scanning
- **Resolution needed**: Create directory as part of this subtask

## Implementation Approaches Considered

### Approach 1: AST-based parsing (from initial subtask description)
- Description: Use ast module to parse Python files without importing
- Pros: No code execution, safer
- Cons: Complex inheritance detection, can't get runtime metadata
- Decision: **Rejected** - Updated specification explicitly requires importlib

### Approach 2: Direct importlib approach (from refined specification)
- Description: Use importlib.import_module() to load modules dynamically
- Pros: Simple, gets actual runtime information
- Cons: Executes module code (security concern for future)
- Decision: **Selected** - Matches updated requirements, acceptable for MVP with trusted code

### Approach 3: Hybrid cookbook pattern adaptation
- Description: Create scanner similar to pocketflow's flow execution pattern
- Pros: Consistent with framework patterns
- Cons: Over-engineered for simple scanning task
- Decision: **Rejected** - Keep scanner simple and focused

## Key Technical Decisions

### Module Organization
- Scanner location: `src/pflow/registry/scanner.py` (not planning/)
- Function name: `scan_for_nodes()` (not scan_directory)
- Create `__init__.py` files for proper package structure

### Metadata Extraction Scope
- Extract only 5 basic fields for this subtask:
  1. module (full import path)
  2. class_name
  3. name (from attribute or kebab-case)
  4. docstring (raw, no parsing)
  5. file_path
- No Interface parsing - that's Task 7's responsibility

### Testing Strategy
- Create both real test nodes and use mocks for edge cases
- Test inheritance detection (BaseNode vs Node vs neither)
- Test name extraction (explicit attribute vs kebab-case conversion)
- Mock importlib for error simulation
- Use pathlib for cross-platform file handling

### Security Documentation
- Add clear comment about importlib executing code
- Note this is acceptable for MVP (trusted package nodes only)
- Document future considerations for user nodes

## Success Validation Criteria

- [ ] Scanner finds all Python files in target directory
- [ ] Correctly identifies BaseNode subclasses (not Node)
- [ ] Extracts all 5 required metadata fields
- [ ] Handles files with import errors gracefully
- [ ] Proper security warning in code
- [ ] Test nodes created and discovered
- [ ] Comprehensive test coverage
