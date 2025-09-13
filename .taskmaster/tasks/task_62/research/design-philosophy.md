# Design Philosophy: stdin and Unix Composability in pflow

## The Unix Philosophy Applied to pflow

### Core Tenets

1. **Do One Thing Well**: Each node should perform a single, well-defined operation
2. **Compose Through Pipes**: Workflows should compose like Unix pipelines
3. **Text is Universal**: Data flows as text (or structured data) between components
4. **Silence is Golden**: Only output what's necessary
5. **Expect Composability**: Tools should work together without special configuration

### How pflow Aligns

```bash
# Unix way
cat data.csv | grep "pattern" | wc -l

# pflow way (should be this natural)
cat data.csv | pflow "count lines matching pattern"
```

Both should "just work" without special configuration or flags.

## The Atomicity Principle

### What Makes a Node Atomic

**Atomic nodes:**
- Have a single responsibility
- Don't know about data sources
- Don't know about data destinations
- Process inputs to outputs
- Are predictable and testable

### Why Atomicity Matters

```python
# ❌ NON-ATOMIC: Node knows too much
class SmartReadNode:
    def exec(self):
        if self.file_path == "-":
            return self.stdin  # Knows about stdin
        elif self.file_path.startswith("http"):
            return fetch_url(self.file_path)  # Knows about HTTP
        else:
            return read_file(self.file_path)  # Knows about files

# ✅ ATOMIC: Node does one thing
class ReadFileNode:
    def exec(self):
        return read_file(self.file_path)  # Just reads files
```

### The Cost of Breaking Atomicity

When we tried to make read-file handle stdin:

1. **Increased Complexity**: Node needed to check multiple conditions
2. **Reduced Testability**: More code paths to test
3. **Coupling**: Node became coupled to shell conventions
4. **Inconsistency**: Other nodes wouldn't have the same capability
5. **Maintenance Burden**: Every file node would need updating

## Separation of Concerns

### The Layers of pflow

```
┌─────────────────────────────────┐
│         User Intent             │  "analyze the data"
└────────────┬────────────────────┘
             │
┌────────────▼────────────────────┐
│     Parameter Discovery         │  Maps stdin → inputs
└────────────┬────────────────────┘
             │
┌────────────▼────────────────────┐
│     Workflow Generation         │  Creates node graph
└────────────┬────────────────────┘
             │
┌────────────▼────────────────────┐
│    Template Resolution          │  ${stdin} → content
└────────────┬────────────────────┘
             │
┌────────────▼────────────────────┐
│      Node Execution             │  Process data (atomic)
└─────────────────────────────────┘
```

### Responsibilities by Layer

**Parameter Discovery**:
- Understand context (stdin available?)
- Map user intent to parameters
- Route data intelligently

**Workflow Generation**:
- Build node graph
- Connect data flows
- Apply templates

**Template Resolution**:
- Resolve variables
- Access shared store
- Provide data to nodes

**Node Execution**:
- Process inputs
- Generate outputs
- Stay atomic

## The Data-Source Agnostic Principle

### Workflows Shouldn't Care

A well-designed workflow works regardless of data source:

```json
{
  "nodes": [{
    "type": "analyze",
    "params": {
      "data": "${input_data}"
    }
  }]
}
```

This workflow doesn't care if `input_data` is:
- Content from stdin
- Content read from a file
- Response from an API
- Output from another node

### The Power of Abstraction

```bash
# All of these should work with the same workflow:

# From stdin
echo "data" | pflow my-workflow

# From file
pflow my-workflow input_data=file.txt

# From API (future)
pflow my-workflow input_data="https://api.example.com/data"

# From another workflow's output
pflow workflow1 | pflow my-workflow
```

## Design Decisions and Tradeoffs

### Decision: Parameter Discovery Intelligence

**Choice**: Make parameter discovery smart enough to route stdin

**Tradeoffs**:
- (+) Minimal code changes
- (+) Preserves atomicity
- (+) Natural user experience
- (-) Prompt complexity increases
- (-) Harder to debug when routing goes wrong

**Alternative Rejected**: Node-level stdin handling
- (+) Explicit and obvious
- (-) Breaks atomicity
- (-) Requires widespread changes
- (-) Couples nodes to I/O methods

### Decision: Use Template Variables

**Choice**: Route stdin via `${stdin}` template variable

**Tradeoffs**:
- (+) Works with existing system
- (+) Declarative and clear
- (+) No new syntax needed
- (-) Requires understanding of template system
- (-) Not immediately obvious to new users

**Alternative Rejected**: Special stdin syntax
- (+) More explicit
- (-) New syntax to learn
- (-) Complicates template resolver

## The Principle of Least Surprise

### What Users Expect

Users coming from Unix expect:
```bash
# This should work
cat data | pflow "process"

# As should this
pflow "process" < data

# And this
pflow "process data.txt"
```

### Meeting Expectations

By routing stdin intelligently:
- Unix users feel at home
- Pipelines work naturally
- No special flags needed
- No manual stdin handling

## Composability Over Configuration

### The Wrong Way: Configuration

```yaml
# ❌ Requiring configuration
workflow:
  stdin_handling: true
  stdin_parameter: input_data
  stdin_type: text
```

### The Right Way: Intelligence

```python
# ✅ Smart defaults
if stdin_present and no_explicit_path:
    use_stdin()
```

### Why This Matters

- **Zero Configuration**: Works out of the box
- **Natural Behavior**: Does what users expect
- **Progressive Disclosure**: Complexity only when needed

## Future-Proofing the Design

### Extensibility Points

The current design allows future enhancements without breaking changes:

1. **Template Functions**: `${stdin|json}`, `${stdin|lines}`
2. **Multiple stdin Streams**: stdin, stderr routing
3. **Type Coercion**: Automatic format conversion
4. **Conditional Templates**: `${stdin ?? file:backup.txt}`

### What We're NOT Doing

**Not adding now (but could later):**
- Complex routing logic
- Type validation at parameter level
- Multi-source aggregation
- Stream processing

**Why not:**
- MVP focus
- Complexity without proven need
- Can add later if needed

## Philosophical Alignment

### pflow's Core Philosophy

> "Plan Once, Run Forever"

stdin routing supports this by:
- Making workflows reusable with different data sources
- Removing the need to modify workflows for I/O changes
- Enabling true workflow portability

### The Declarative Principle

Workflows remain declarative:
```json
{
  "params": {
    "input": "${data}"  // Don't care where data comes from
  }
}
```

Not imperative:
```python
if stdin:
    input = stdin
else:
    input = read_file(path)
```

## Lessons from the Journey

### Lesson 1: Start with Wrong Solutions

We first tried modifying nodes because it seemed "obvious". This wrong turn taught us:
- The value of atomicity
- The cost of coupling
- The importance of separation of concerns

### Lesson 2: The System Knows Best

The planner already had all the information needed:
- stdin availability
- User intent
- Workflow requirements

We just needed to connect the dots.

### Lesson 3: Simple Solutions Scale

Updating a prompt is simpler than:
- Modifying nodes
- Changing template resolution
- Adding new workflow syntax

And yet it solves the entire problem.

## The Cultural Impact

### For Users

stdin routing makes pflow:
- More Unix-friendly
- More intuitive
- More composable

### For Developers

The approach reinforces:
- Atomic node design
- Layer separation
- Intelligence at the right level

### For the Project

This solution demonstrates:
- Thoughtful design
- User-centric thinking
- Respect for established patterns

## Conclusion: The pflow Way

The "pflow way" for stdin handling is:

1. **Keep nodes atomic** - They process, not route
2. **Add intelligence at planning** - Where context exists
3. **Use existing mechanisms** - Template variables work
4. **Respect Unix conventions** - But don't be enslaved by them
5. **Optimize for users** - Make the common case simple

This approach embodies the best of Unix philosophy while leveraging pflow's unique strengths in natural language understanding and intelligent workflow generation.

The result: Workflows that "just work" whether data comes from files, stdin, or future sources we haven't imagined yet.