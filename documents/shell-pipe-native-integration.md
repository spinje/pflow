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
2. Place the piped content into the shared store under the reserved key `shared["stdin"]`. The `summarize-text` node (or the first node in the flow) is then expected to utilize this `shared["stdin"]` content for its primary text input.
3. Execute the flow as if the content had been provided explicitly.

### Advanced NL-based Usage

Natural language planner seamlessly supports piped input:

```bash
kubectl logs my-pod | pflow "extract errors and summarize"
```

Here, the NL planner identifies appropriate nodes, mapping piped `stdin` into the workflow automatically.

### Explicit Usage (for Ambiguous Cases)

For nodes with multiple string inputs or ambiguity:

```bash
git diff | pflow summarize-diff --diff -
```

The `-` explicitly indicates the node should consume piped input.

### Internal Implementation

* **Detection:** pflow detects if `stdin` is not a TTY and has content.
* **Mapping Logic:** Piped content is placed into `shared["stdin"]`. Nodes are generally designed to utilize `shared["stdin"]` for their primary textual input if no other specific input source is provided for that primary parameter. If a node has multiple string inputs or if the intended use of `shared["stdin"]` is ambiguous, explicit flags (e.g., using `-` as a value like `pflow my-node --target-input -`) are used to direct the `stdin` content appropriately.
* **Trace & Cache:** Input is hashed, saved under `stdin.<hash>.txt`, and the hash is included in the trace and lockfile to ensure caching and reproducibility.

## Importance and Benefits to Users

* **Reduced Cognitive Load:** Users intuitively use pflow in shell workflows without additional mental overhead.
* **Enhanced Composability:** Encourages integration of AI-driven tasks into existing workflows, enhancing user productivity and toolchain efficiency.
* **Smooth Adoption Path:** Eases transition for users familiar with Unix-style CLIs and tools like `llm`, accelerating adoption and increasing satisfaction.

## Summary

Native integration with Unix shell pipes positions pflow as a highly intuitive, frictionless, and powerful automation tool, reinforcing its role in modern AI-enabled workflows. By providing familiar, robust, and explicit support for shell piping, pflow ensures both user convenience and workflow reproducibility, clearly differentiating itself from simpler AI CLIs while embracing the Unix philosophy of composability and simplicity.
