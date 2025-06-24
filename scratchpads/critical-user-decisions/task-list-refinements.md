# Task List Refinements - Critical Decisions Needed

## 1. CLI Parameter Resolution (Task 4) Simplification

The current Task 4 describes complex flag categorization logic, but the architecture docs indicate ALL input goes through the LLM planner in MVP. This creates unnecessary complexity.

### Options:

- [ ] **Option A: Simplify to stdin detection only**
  - Remove flag categorization logic
  - Just detect stdin and pass all flags to planner
  - Let LLM handle all parameter resolution
  - Aligns with documented MVP approach

- [x] **Option B: Keep current approach**
  - Implement flag categorization as described
  - Might enable future optimizations
  - Adds complexity not clearly needed for MVP

User comment: This is a cli tool, so we need to be able to pass in flags and parameters to the tool even though you are right, natural language syntax is most important to validate in the mvp, we should keep things simple though, as much as we can.

**Recommendation**: Option A - The planner.md explicitly states both natural language AND CLI syntax go through LLM in MVP.

## 2. Shell Integration Timing (Task 30)

Shell pipe integration is currently in Phase 5 but seems fundamental to CLI operation.

### Options:

- [x] **Option A: Move to Phase 1 (after Task 1)**
  - Shell integration is core infrastructure
  - stdin detection needed early for shared["stdin"]
  - Enables testing with real Unix pipes early

- [ ] **Option B: Keep in Phase 5**
  - Focus on other infrastructure first
  - Add shell integration as enhancement

User comment: Great idea, I think we should do this. Also we should mention that we can look at the code for simon willison's llm package to see how he does it when we are ready to implement it. We also have the source code for Claude Code, but im not sure how usable that is since Claude Code is a REPL.

**Recommendation**: Option A - Shell pipes are fundamental to the CLI experience.

## 3. NodeAwareSharedStore Implementation (Task 3)

The proxy pattern needs careful implementation to work with pocketflow's execution model.

### Options:

- [ ] **Option A: Subclass dict with transparent mapping**
  ```python
  class NodeAwareSharedStore(dict):
      def __getitem__(self, key):
          mapped_key = self.input_mappings.get(key, key)
          return super().__getitem__(mapped_key)
  ```

- [ ] **Option B: Wrapper class that delegates**
  ```python
  class NodeAwareSharedStore:
      def __init__(self, shared, mappings):
          self._shared = shared
          # Implement full dict interface
  ```

User comment: We are not ready to make a decision on this yet, we need choose this as we plan to start implementing the code. Make a note of this in the task description so that we dont forget it. Every task implementation phase start with a big exploration of potential solutions and then we choose the best one and create a very detailed plan and break the task down to sub-tasks. The important thing here is that we are doing things in the most optimal order possible and that we are doing the right things, and not forgetting any important task inbetween.

**Recommendation**: Option A - Simpler and maintains dict interface naturally.

## 4. Missing Entry Point & Packaging

No task explicitly creates the CLI entry point and package structure.

### Options:

- [x] **Option A: Add new Task 0 for packaging setup**
  - Create setup.py/pyproject.toml entry points
  - Ensure 'pflow' command is available
  - Set up proper package structure

- [ ] **Option B: Include in Task 1**
  - Extend Task 1 to include packaging
  - Keeps task count the same

User comment: Great idea but we must make sure this seamlessly integrates into task 1 (task 2 after this new is created). Also we cannot create task 0, we need to start with task 1 but make sure this is the first one.

**Recommendation**: Option A - Packaging deserves its own task for clarity.

## 5. Deferred Task Status (Tasks 26-27)

Tasks 26-27 have conflicting deferral information.

### Options:

- [x] **Option A: Mark both as explicitly deferred**
  - Change status to "deferred"
  - Set priority to "low"
  - Update descriptions to clarify v2.0 scope

- [ ] **Option B: Include simplified versions in MVP**
  - Task 26: Basic compatibility checking only
  - Task 27: Simple timing logs only

**Recommendation**: Option A - Focus on MVP essentials per architecture docs.

## 6. LLM Package Integration

Docs mention using Simon Willison's 'llm' package but no task explicitly integrates it.

### Options:

- [x] **Option A: Update Task 17 to use 'llm' package**
  - Leverage existing, well-tested solution
  - Provides model flexibility out of the box
  - Aligns with documented approach

- [ ] **Option B: Build custom implementation**
  - More control but more work
  - Might duplicate existing functionality

  User comment: Great idea, we should mention this as a potential solution in the task description.

**Recommendation**: Option A - Use proven tools, focus on core value.

## 7. Test Integration Approach

Current Task 24 is a single comprehensive test task at the end.

### Options:

- [ ] **Option A: Keep single test task**
  - All tests written together
  - Ensures comprehensive coverage
  - Current approach

- [x] **Option B: Add testing to each task**
  - Each feature includes its tests
  - Better TDD approach
  - Tests evolve with code

  User comment: Perfect, but only include this if making test makes sense for the task. Also, it should problably be added to the testStrategy field.

**Recommendation**: Option B - Include "write tests" in each implementation task description.
