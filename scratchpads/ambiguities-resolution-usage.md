# How to Use the Ambiguities Resolution Prompts

## For Task Operators

When assigning an ambiguity resolution task to an AI agent:

1. **Ensure the agent has context about the task**:
   ```
   Here is Task [ID]: [provide full task details]
   Related context: [any additional information]
   ```

2. **Provide the comprehensive prompt**:
   ```
   Please follow the instructions in this prompt to create an ambiguities
   resolution document for Task [ID]: [paste ambiguities-resolution-prompt.md]
   ```

3. **Set clear expectations**:
   - This is a thinking/analysis task, not coding
   - The output enables others to implement without guesswork
   - Thoroughness is more important than speed

## For AI Agents

When you receive an ambiguity resolution task:

1. **Start with prerequisites** - Ensure you understand the task fully
2. **Use the comprehensive prompt** - Follow it step by step
3. **Reference the quick guide** - Keep key points in mind
4. **ULTRATHINK liberally** - Deep analysis prevents shallow ambiguities
5. **Verify everything** - Don't assume, check the codebase
6. **Create a self-contained document** - Reader shouldn't need external context

## Expected Outcomes

A good ambiguities document:
- Identifies 3-10 meaningful decision points
- Provides clear context for each
- Offers genuine alternatives with trade-offs
- Makes specific recommendations with reasoning
- Includes concrete examples
- Guides implementation without constraining it

## Example Usage

```
AI Agent, please analyze Task 17 (Implement Natural Language Planner System)
and create an ambiguities resolution document following the comprehensive
prompt provided. The task description is: [full description].

Focus especially on:
- How template variables should work
- Integration with the context builder
- Error handling strategies
- Performance boundaries

Use the prompt in ambiguities-resolution-prompt.md and create your output
at .taskmaster/tasks/task_17/task-17-ambiguities.md
```

## Quality Indicators

High-quality ambiguity resolution:
- Each decision would lead to different code if changed
- Context explains domain-specific knowledge
- Options represent fundamentally different approaches
- Recommendations consider the full system
- Examples clarify complex concepts
- Document helps months later when context is forgotten
