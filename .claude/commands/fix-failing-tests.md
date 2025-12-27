---
description: Fix failing pytest tests with root cause analysis
argument-hint: [--use-parallel-subagents]
---

There are currently make test errors that need to be fixed.

You have been assigned to fix them.

Input:
--use-parallel-subagents=$ARGUMENTS (default: false)

if --use-parallel-subagents=true, you must use subagents to fix the tests.
if --use-parallel-subagents=false, you must not use subagents to fix the tests.
if --use-parallel-subagents is empty, you should not use subagents to fix the tests.

Requirements:
- You must always fix the root cause of the error, not just make the test pass.


Should you use subagents to fix the errors?

If yes, please carefully consider and followthe following requirements:

Requirements if using subagents:
- Always use the @write-tests-fixer subagent to fix issues in tests
- Only assign one subagent per file (never use the same subagent for errors in multiple files)
- Define a termination criteria for each subagent
- Provide a comprehensive context and instructions to each subagent
- Be clear about the scope of the subagent's work when writing the instructions to the subagent
- Make sure to point out that they should follow the general requirements from above (no cheating, make the best fix, etc.)
- Always deploy the subagents in PARALLEL if there are errors in multiple files (this means using ONE function call block to deploy all subagents)
- Use as many subagents as there are failing files (parallelize them, never use sequential function calls to deploy subagents)

Guidelines for fixing tests (if you are not using subagents):

**Your tests are not for humans to read once and forget. They are active guardians that protect AI agents from breaking the codebase.**

When tests fail, you must:
1. Find and fix the ROOT CAUSE, not just make tests 
2. You must think hard before attempting each error and make sure you understand the root cause of the error and the BEST way to fix it.
3. If there are multiple ways to fix the error, you must reason through the pros and cons of each and choose the best option.
4. You must never "cheat" by making the easy fix. You must always make the best fix.
5. Learn from failures to write better tests
6. Document what was discovered
7. Never take shortcuts or "cheat" to pass tests

## When Tests Fail:

**The most critical moment in testing is when a test fails. This is where you prove your integrity.**

### Root Cause Analysis is MANDATORY

When any test fails, you MUST follow this process:

```
Test Failed
├─ 0. Understand the requirements
│  ├─ Make sure you understand what the correct behavior is
│  └─ Verify ALL your assumptions
│
├─ 1. Understand the failure
│  ├─ What was the test trying to verify?
│  ├─ What was the expected behavior?
│  └─ What actually happened?
│
├─ 2. DIAGNOSE the root cause
│  ├─ Is the implementation wrong?
│  ├─ Is the test wrong?
│  ├─ Is the test assumption invalid?
│  └─ Is there a race condition or flaky behavior?
│
├─ 3. CHOOSE the right fix
│  ├─ Fix the bug in the implementation
│  ├─ Fix the test if it had wrong expectations
│  ├─ Make the test more robust (not weaker!)
│  └─ Document why the fix was needed
│
└─ 4. LEARN and document
   ├─ Add a comment explaining what was discovered
   ├─ Consider if similar tests have the same issue
   └─ Update test patterns if needed
```

### Making the Test vs Code Decision: Think, Don't Guess

**CRITICAL**: Never jump to conclusions. Always investigate BOTH the test and the code thoroughly before deciding what to fix. The hard but most important part of fixing a test is to understand the root cause of the failure.

#### The Investigation Mindset

When a test fails, resist the urge to immediately "fix" it. Instead, become a detective:

```python
# Your thought process should be:
"""
1. What is this test trying to verify? (Read test name, docstring, assertions)
2. What behavior does the code actually implement? (Read the implementation)
3. What should the correct behavior be? (Check requirements, ask if unclear)
4. Why is there a mismatch? (This is where the real thinking happens)
"""
```

### Systematic Debugging Protocol

When a test fails, follow this concrete debugging approach:

```python
# STEP 1: Isolate the failure
def debug_failing_test():
    """Run ONLY the failing test to ensure it's not environmental"""
    # pytest path/to/test.py::test_specific_function -v

    # NEVER run 'make test' when debugging a specific test!
    # Other failures will distract you from your current task

# STEP 2: Add strategic debug output
def test_workflow_with_debug():
    print(f"Initial state: {shared}")  # See input
    result = workflow.run(shared)
    print(f"Result: {result}")  # See output
    print(f"Final state: {shared}")  # See mutations
    # Compare actual vs expected

# STEP 3: Simplify to minimal reproduction
def test_minimal_failure():
    # Remove everything except what's needed to reproduce
    # This often reveals the real issue

# STEP 4: Check assumptions
def test_verify_assumptions():
    # Is the test data valid?
    assert Path(test_file).exists(), "Assumption: file exists"
    # Are external dependencies available?
    assert service.is_connected(), "Assumption: service running"

# STEP 5: Binary search the problem
def test_bisect_issue():
    # Comment out half the test
    # Does it still fail? The issue is in remaining half
    # Repeat until you find the exact line
```

### Signs You're Cheating (NEVER DO THESE)

```python
# ❌ CHEATING: Mocking to avoid the failure
def test_file_operations():
    # Original test failed because file wasn't created
    # DON'T DO THIS:
    with patch('os.path.exists', return_value=True):
        result = create_file("test.txt")
        assert result.success  # This proves nothing!

# ❌ CHEATING: Weakening assertions
def test_error_message():
    # Original assertion: assert error == "File not found: test.txt"
    # Test failed, so you changed it to:
    assert "not found" in error.lower()  # Too weak!

# ❌ CHEATING: Skipping the hard parts
@pytest.mark.skip("Flaky on CI")  # Translation: "I gave up"
def test_concurrent_operations():
    pass

# ❌ CHEATING: Making tests that can't fail
def test_workflow():
    try:
        run_workflow()
        assert True  # What does this even test?
    except:
        assert True  # Really?
```

### Mocking Guidelines When Fixing Tests

When a test fails and you're tempted to add mocks:

```
Should I mock this to fix the test?
│
├─ Did the test find a REAL bug?
│  ├─ Yes → Fix the bug, not the test!
│  └─ No → Continue ↓
│
├─ Is the test flaky due to external factors?
│  ├─ Yes → Mock ONLY the external factor
│  └─ No → Continue ↓
│
├─ Is the test too slow?
│  ├─ Yes → Optimize the test, don't mock
│  └─ No → Continue ↓
│
└─ Is the test impossible without mocks?
   ├─ Yes → Document WHY and mock minimally
   └─ No → Don't mock!
```

## Test Smells: Early Warning System

Recognize these warning signs BEFORE your test becomes an anti-pattern:

### 🚩 **The Test is Getting Too Long**
```python
# SMELL: Test > 30 lines suggests too much setup or multiple concerns
def test_complex_workflow():  # 75 lines!
    # 40 lines of setup...
    # 20 lines of execution...
    # 15 lines of assertions...

# FIX: Extract helpers or split into focused tests
def test_workflow_initialization():
    workflow = create_test_workflow()  # Extracted helper
    assert workflow.is_valid()

def test_workflow_execution():
    workflow = create_test_workflow()
    result = workflow.run()
    assert result.success
```

### 🚩 **Too Many Mocks**
```python
# SMELL: More than 2-3 mocks indicates design issues
@patch('module.func1')
@patch('module.func2')
@patch('module.func3')
@patch('module.func4')  # Red flag!
def test_something(m1, m2, m3, m4):
    pass

# FIX: The code under test has too many dependencies
# Consider refactoring the code, not adding more mocks
```

### 🚩 **Changing Assertions to Make Tests Pass**
```python
# SMELL: Progressively weakening assertions
# Version 1: assert result == {"status": "ok", "count": 5}
# Version 2: assert result["status"] == "ok"  # Removed count
# Version 3: assert "ok" in str(result)  # Even weaker!

# FIX: Understand WHY the assertion changed
# Fix the root cause, don't weaken the test
```

### 🚩 **Test Only Passes in Specific Order**
```python
# SMELL: Test depends on state from previous tests
def test_1_create_user():
    global user_id
    user_id = create_user()

def test_2_update_user():
    update_user(user_id)  # Depends on test_1!

# FIX: Each test must be independent
def test_update_user():
    user_id = create_user()  # Own setup
    update_user(user_id)
```

### 🚩 **Hard to Understand What's Being Tested**
```python
# SMELL: Need to read implementation to understand test
def test_process():
    obj = Thing()
    obj.x = 5
    obj.y = 10
    obj._internal = []  # What is this?
    result = obj.process()
    assert result  # What does this mean?

# FIX: Clear test intent
def test_calculator_adds_two_numbers():
    calculator = Calculator()
    result = calculator.add(5, 10)
    assert result == 15
```

## Mocking Decision Tree

```
Should I mock this?
│
├─ Is it an external system boundary?
│  ├─ Yes → Mock it (filesystem, network, database, time)
│  └─ No → Continue ↓
│
├─ Is it expensive/slow/non-deterministic?
│  ├─ Yes → Mock it (AI models, random generation)
│  └─ No → Continue ↓
│
├─ Is it a third-party library?
│  ├─ Yes → Consider mocking (but prefer real if possible)
│  └─ No → Continue ↓
│
└─ Is it your own code?
   └─ No, don't mock it! → Use real implementation
```

## Quality Checklist

Before submitting any test, ask yourself:

- [ ] Can I understand what this test verifies from its name alone?
- [ ] Will this test fail if the behavior changes?
- [ ] Will this test survive if I refactor the implementation?
- [ ] Am I testing what users/other code will observe?
- [ ] Is this test independent of other tests?
- [ ] Does this test run in under 100ms (unit) or 1s (integration)?
- [ ] Are my assertions specific to the behavior, not the implementation?
- [ ] Have I avoided mocking my own code?

**Final step**: Run `make check` to ensure all linting, type checking, and formatting passes for your test changes.

When fixing a failing test:

- [ ] Did I find the ROOT CAUSE of the failure?
- [ ] Am I fixing the bug, not weakening the test?
- [ ] Have I documented what I learned from this failure?
- [ ] Is the test now testing real behavior, not mocked behavior?
- [ ] Will this test catch the same bug if it happens again?
- [ ] Did I check if other tests have the same issue?

### Emergency Checklist

When a test is failing and you don't know why:

1. **Is it testing behavior or implementation?**
2. **Would this test break if I renamed a variable?**
3. **Can I understand what broke from the error message?**
4. **Is the test dependent on other tests?**
5. **Am I mocking something I shouldn't?**

If you answer "yes" to #2 or #4, or "no" to #1 or #3, the test needs fixing.

If any answer is "No", revise the test.

## Final Reminders

1. **Your tests are code too** - Keep them clean, simple, and maintainable
2. **Delete bad tests** - A bad test is worse than no test
3. **Test the contract, not the implementation** - What matters is what the code promises to do
4. **When in doubt, use real components** - Mocking is the exception, not the rule
5. **NEVER CHEAT** - A passing test that hides bugs is worse than a failing test
6. **Shallow tests** - Shallow tests hide real bugs
7. **Document your fixes** - Future agents need to know what bugs were found and fixed

Remember: You're not writing tests to achieve coverage metrics or to see green checkmarks. You're writing tests to make AI-driven development safer and more efficient. Every test should earn its place by catching real bugs and enabling confident changes.

**The Ultimate Test Quality Metric**: If your test passes but the feature is broken, your test has failed its purpose. Real behavior > Green tests.

When you encounter a failing test, that's not a problem to hide - it's an opportunity to prevent a bug from reaching production. Embrace test failures, learn from them, and make the codebase stronger.
