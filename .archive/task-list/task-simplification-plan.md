# Task Simplification Plan

## Key Principles
1. Remove words like "system", "engine", "framework", "abstraction", "enhanced", "sophisticated"
2. Focus on concrete implementation steps
3. Reference specific documentation sections
4. Keep MVP scope in mind
5. Use direct pocketflow features where possible

## Major Changes Needed

### Task 1: Split into smaller tasks
Current: One large task doing CLI setup, package structure, commands, etc.
New approach:
- Task 1a: Basic CLI setup with click
- Task 1b: Command routing and help system
- Task 1c: Inspect and trace commands (lower priority)

### Task 4: Simplify scope
Remove "JSON IR → compiled Python code execution pipeline" - that belongs in task 21

### Task 5: Rename and simplify
From: "Implement template resolution system"
To: "Create template variable substitution"
Just simple string replacement, not a complex "system"

### Task 7: Reduce scope
From: "Design complete JSON IR system"
To: "Define JSON IR schema for MVP"
Focus on what's needed now, not "complete"

### Task 17: Remove abstraction
From: "Create LLM client abstraction"
To: "Implement LLM API client"
Just API calls, not an abstraction layer

### Task 18: Simplify language
From: "Build sophisticated planning context"
To: "Create planning context builder"

### Task 19: Remove "engine"
From: "Implement workflow generation engine"
To: "Implement natural language to CLI compiler"

### Task 22: Merge with task 2
Validation is already covered in task 2 - this creates confusion

### Task 26: Defer to post-MVP
Interface compatibility might not be needed for initial version

### Task 27: Defer to post-MVP
Metrics instrumentation is premature optimization

### Task 28: Simplify
From: "Create prompt engineering system"
To: "Create prompt templates for planning"
