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

```bash
cat article.md | pflow summarize-text
```

This will:

1. Detect that input is piped via `stdin`.
2. Place the piped content into the shared store under the reserved key `shared["stdin"]`.
3. The `summarize-text` node (or the first node in the flow) then utilizes this `shared["stdin"]` content. This can happen in a few ways:
    *   The node itself is designed to check `shared["stdin"]` for input if its primary named input key (e.g., `shared["text"]`) is not populated.
    *   The planner (for NL-generated flows) or CLI processing logic (for direct CLI flows) generates an Intermediate Representation (IR) that includes an explicit mapping from the node's primary input key to `shared["stdin"]`.
4. Execute the flow as if the content had been provided through an explicitly named shared store key.

### Advanced NL-based Usage

Natural language planner seamlessly supports piped input:

```bash
kubectl logs my-pod | pflow "extract errors and summarize"
```

Here, the NL planner identifies appropriate nodes. It will generate a flow where `shared["stdin"]` is populated with the log data, and the first relevant node in the generated flow is configured (either by its design or via an IR mapping) to process the content from `shared["stdin"]`.


### Internal Implementation

* **Detection:** pflow detects if `stdin` is not a TTY and has content.
* **Mapping Logic:** Piped content is primarily placed into `shared["stdin"]`.
    *   **Planner-driven Mapping**: For NL-generated flows, the planner may create an explicit IR mapping from a node's input key (e.g., `text`) to `shared["stdin"]`.
    *   **Node Convention**: Nodes can be designed to check `shared["stdin"]` as a fallback if their primary named input key is not found in the shared store.
* **Trace & Cache:** Input from `shared["stdin"]` is hashed, its content may be saved (e.g., to a file like `stdin.<hash>.txt` for tracing purposes), and the hash is included in the trace and lockfile to ensure caching and reproducibility.

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

- [Shared Store](../core-concepts/shared-store.md) - Reserved `shared["stdin"]` key
- [CLI Reference](../reference/cli-reference.md) - CLI syntax and commands
- [Execution Reference](../reference/execution-reference.md) - Caching and execution
