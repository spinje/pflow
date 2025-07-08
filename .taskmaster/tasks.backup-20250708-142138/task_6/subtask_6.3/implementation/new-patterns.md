# Patterns Discovered

## Pattern: Documentation-Driven Examples
**Context**: When you need to create examples that teach users how to use a system
**Solution**: Create each example with a corresponding markdown file that explains:
- Purpose and use case
- Visual flow diagram (ASCII art)
- Node-by-node explanation
- How to validate/run
- Common variations

**Why it works**: Users learn better with context and explanation alongside code
**When to use**: Any time you're creating examples for learning purposes
**Example**: Each JSON example in examples/ has a .md file explaining it

## Pattern: Invalid Examples as Teaching Tools
**Context**: Users need to understand what errors look like and how to fix them
**Solution**: Create intentionally invalid examples with documentation showing:
- What's wrong
- Expected error message
- How to fix it
- Why it matters

**Why it works**: Learning from mistakes is powerful, and seeing errors in a safe context builds confidence
**When to use**: When creating validation systems or APIs with complex rules
**Example**: examples/invalid/ directory with various validation failures

## Pattern: Progressive Example Complexity
**Context**: Teaching a complex system to users with varying skill levels
**Solution**: Organize examples from minimal to advanced:
1. Absolute minimum viable example
2. Basic patterns everyone needs
3. Advanced real-world scenarios

**Why it works**: Users can start simple and progress at their own pace
**When to use**: Documentation for any system with a learning curve
**Example**: examples/core/ (simple) vs examples/advanced/ (complex)
