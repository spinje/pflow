# pflow Native Integration with Shell Pipes

## Overview

pflow introduces native integration with Unix shell pipes (`stdin`) to enhance its usability and flexibility for developers. This integration enables seamless interactions with shell workflows and familiar Unix-style command-line patterns, significantly reducing friction in common use cases.

## Why We're Adding Shell Pipe Support

Unix shell pipes are fundamental to efficient command-line workflows, widely adopted for their simplicity and composability. Supporting native piping aligns with pflow's core mission: providing frictionless, reproducible workflows directly from intuitive user interactions. By leveraging shell pipes, users can effortlessly bridge command-line tools and AI-driven workflows without intermediate steps or temporary files.

### Key Motivations:

* **Friction Reduction:** Minimizes unnecessary steps such as manually specifying input files or copying data.
* **Familiarity and Convenience:** Leverages existing user knowledge and muscle memory, familiar from tools like `grep`, `cat`, and Simon Willison's popular `llm` CLI.
* **Workflow Composability:** Makes it straightforward to chain pflow with traditional Unix utilities, enabling a richer ecosystem integration.

## How Shell Pipe Integration Fits into pflow

Shell pipe integration complements pflow's existing design philosophy, maintaining explicitness and reproducibility:

* **Preserves Core Guarantees:** Input from pipes is captured, hashed, and tracked in pflow's deterministic flow execution model, ensuring cacheability and reproducibility.
* **Minimal Complexity:** The integration logic is straightforward, ensuring reliability without introducing significant complexity.
* **Uniform Experience:** Pipe-based input is handled uniformly across pflow, ensuring consistent, predictable behavior.

## Similarity to Simon Willison's `llm`

Simon Willison's `llm` CLI popularized the seamless interaction of Unix pipelines with AI-driven commands, exemplified by simple syntax:

```bash
cat notes.txt | llm summarize
```

pflow's shell integration mirrors this intuitive behavior, ensuring familiarity for users transitioning from `llm` to pflow, but extends it with explicit reproducibility, structured caching, and workflow traceability.

## Detailed Functionality and Workflow

### Basic Usage

Workflows declare which input receives piped data using `"stdin": true`:

```json
{
  "inputs": {
    "data": {"type": "string", "required": true, "stdin": true}
  },
  "nodes": [...]
}
```

```bash
cat article.md | pflow summarize-text
```

This will:

1. Detect that input is piped via `stdin` (FIFO pipe detection).
2. Find the workflow input marked with `"stdin": true`.
3. Route the piped content to that input parameter.
4. Execute the workflow with the stdin content as the input value.

**Key behaviors:**
- CLI parameters override stdin: `echo "ignored" | pflow workflow.json data="used"`
- Only one input per workflow can have `stdin: true`
- Same workflow works via piping OR CLI arguments

### Workflow Chaining

With stdin routing, workflows can be chained like Unix tools:

```bash
# Pipeline composition
cat data.json | pflow -p transform.json | pflow analyze.json > report.md

# Mix with Unix tools
pflow -p fetch-prs.json | jq '.[] | select(.urgent)' | pflow notify.json
```

The `-p` flag outputs to stdout for pipeline composition.

### Internal Implementation

* **FIFO Detection:** `stdin_has_data()` uses `stat.S_ISFIFO()` to detect real shell pipes
  - Returns True only for FIFO pipes (real `|` pipes)
  - Returns False for char devices (Claude Code), sockets, StringIO
  - Prevents hanging in non-pipe environments

* **Routing Logic:** Stdin routes to workflow input with `"stdin": true`
  - `_find_stdin_input()` locates the target input
  - `_route_stdin_to_params()` injects stdin into execution params
  - Routing happens BEFORE input validation (so required inputs are satisfied)

* **CLI Override:** CLI parameters take precedence over piped stdin

* **Error Handling:** Clear error if stdin is piped but no `stdin: true` input exists

### Advanced Unix Integration

Beyond basic stdin detection, pflow provides full Unix citizenship:

#### 1. Streaming Support
Large files are processed in chunks without loading entirely into memory:
```bash
cat 1GB-log.txt | pflow analyze-errors  # Streams, doesn't load 1GB
```
This is critical for processing server logs, database dumps, or other large datasets.

#### 2. Exit Code Propagation
Proper exit codes enable shell scripting and automation:
```bash
pflow analyze || echo "Analysis failed"  # Exit 0 on success, non-zero on failure
pflow validate && pflow deploy           # Chain commands based on success
```

#### 3. Signal Handling
Graceful interruption support for long-running workflows:
```bash
# Ctrl+C during execution:
# - Cleanly stops current node
# - Saves partial progress to trace
# - Returns appropriate exit code
```

#### 4. stdout Output
Workflows can output to stdout for further processing:
```bash
pflow extract-errors | grep CRITICAL | wc -l
pflow summarize --format=json | jq '.summary'
```

This enables pflow to be a true citizen in Unix pipelines, composing naturally with grep, awk, jq, and other tools.

## Importance and Benefits to Users

* **Reduced Cognitive Load:** Users intuitively use pflow in shell workflows without additional mental overhead.
* **Enhanced Composability:** Encourages integration of AI-driven tasks into existing workflows, enhancing user productivity and toolchain efficiency.
* **Smooth Adoption Path:** Eases transition for users familiar with Unix-style CLIs and tools like `llm`, accelerating adoption and increasing satisfaction.

## Summary

Native integration with Unix shell pipes positions pflow as a highly intuitive, frictionless, and powerful automation tool, reinforcing its role in modern AI-enabled workflows. By providing familiar, robust, and explicit support for shell piping, pflow ensures both user convenience and workflow reproducibility, clearly differentiating itself from simpler AI CLIs while embracing the Unix philosophy of composability and simplicity.

## See Also

- [Shared Store](../core-concepts/shared-store.md) - Node communication patterns
- [Architecture](../architecture.md) - CLI interface overview
- [IR Schema](../reference/ir-schema.md) - Workflow input declarations including `stdin: true`
