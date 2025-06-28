# Feature Specification: CLI Autocomplete for `pflow`

> **MVP Status**: ✅ Core Feature (Basic autocomplete)
> **v2.0 Status**: Advanced type-aware suggestions

## 1. Overview & Importance

Command-Line Interface (CLI) Autocomplete is a critical usability feature designed to enhance the `pflow` user experience by providing real-time suggestions for commands, node names, flags (parameters and shared store keys), and their potential values. This functionality aims to transform `pflow` from a purely syntax-driven tool into a more interactive composition environment, enabling users to build correct, modular flows more efficiently and with fewer errors.

**Importance:**

* **Enhanced Usability:** Simplifies the process of writing `pflow` commands, especially for complex flows or users new to the system.
* **Error Prevention:** Reduces typos and the use of incorrect or non-existent node names, flags, or values.
* **Discoverability:** Allows users to easily discover available nodes within the registry, their parameters, expected shared store keys, and possible actions without constantly referring to documentation.
* **Learning Aid:** Reinforces `pflow`'s syntax and the "natural interface" patterns by making them visible during composition, supporting the educational design philosophy and progressive learning goals.
* **Productivity Boost:** Speeds up the process of authoring and iterating on flows.
* **Reinforces Core Design:** Makes the distinctions and interactions between the shared store and node parameters more tangible and understandable during flow construction.

## 1.1 MVP vs v2.0 Feature Scope

### MVP Features (Basic Autocomplete)
The MVP implementation focuses on immediate user value with simple completions:

* **Node name completion**: Complete available node names from registry
  - `pflow read-f[TAB]` → `read-file`
  - `pflow github-g[TAB]` → `github-get-issue`
* **Basic parameter completion**: Suggest common flags from node metadata
  - `pflow read-file --[TAB]` → `--path, --encoding`
  - `pflow llm --[TAB]` → `--prompt, --model, --temperature`
* **Pipe operator support**: Recognize `>>` and suggest available nodes
  - `pflow read-file --path=data.txt >> [TAB]` → list all nodes
* **Simple shell integration**: Basic completion scripts for bash/zsh
* **Works with LLM backend**: Unquoted CLI syntax enables autocomplete even though commands are processed by LLM planner

### v2.0 Enhancements (Type-Aware Autocomplete)
Future enhancements will add intelligent, context-aware suggestions:

* **Type-aware node filtering**: Only suggest compatible nodes based on outputs
  - After `github-get-issue >>`, prioritize nodes that consume issue data
* **Dynamic value completion**: Suggest actual values from context
  - `--issue=[TAB]` could list recent issue numbers
  - `--model=[TAB]` shows available LLM models
* **Shadow store integration**: Real-time compatibility validation
* **Advanced parameter hints**: Show types, descriptions, and defaults
* **Direct CLI parsing benefit**: More accurate completions with direct parsing

## 1.2 CLI Autocomplete Integration (MVP Feature)

**Shell autocomplete for CLI syntax is a high-value feature** that enhances user experience even while CLI syntax is processed through the LLM:

**Benefits**:
- **Node Discovery**: Users can tab-complete node names (`read-file`, `llm`, `github-get-issue`)
- **Parameter Hints**: Discover available flags (`--path`, `--prompt`, `--issue`)
- **Professional Feel**: Makes pflow feel like a polished CLI tool
- **Learning Aid**: Helps users understand available nodes and parameters

**Implementation**:
```bash
# User types and uses TAB for suggestions:
pflow [TAB]                    # → read-file, llm, write-file, etc. (recently used nodes)
pflow read-f[TAB]              # → read-file
pflow read-file --[TAB]         # → --path, --encoding
pflow read-file --path=data.txt >> [TAB]  # → llm, write-file, etc.
```

**Why it works with LLM backend**:
- Shell sees unquoted CLI syntax and can parse it
- Autocomplete reads from node registry
- LLM still handles intelligent connection and parameter filling
- Progressive enhancement path to direct parsing in v2.0

## 2. How it Works: Direct CLI Integration

CLI Autocomplete for `pflow` will be implemented through direct integration with the user's existing shell environment (e.g., Bash, Zsh, Fish, PowerShell), rather than requiring `pflow` to run as a separate REPL.

### 2.1 Completion Script Generation & Sourcing

* `pflow` will provide a command, such as `pflow completion <shell_name>`, which generates a shell-specific completion script.
* Users will need to source this script in their shell's configuration file (e.g., `.bashrc`, `.zshrc`, `config.fish`) to enable the autocomplete functionality.

### 2.2 Shell Invocation on TAB Press

* When the user types a `pflow` command and presses the `TAB` key, the active shell will execute the relevant part of the sourced completion script.

### 2.3 Dynamic Suggestion Generation by `pflow`

* The completion script is designed to call the `pflow` executable itself. This call includes special arguments or environment variables that signal a completion request, along with the entire content of the command line typed so far by the user.
* Upon receiving a completion request, `pflow` will:
    1. Parse the current command-line input to understand the context (e.g., is the cursor after `pflow`, after a node name, after a flag, after a transition operator like `>>` or `-`?).
    2. Query the **Unified Registry** for available node names, including namespaces and versions.
    3. Access **Node Metadata** (extracted from docstrings or MCP manifests) to find relevant inputs (shared store keys), outputs, parameters, default values, types, and actions for the current node or context.
    4. Potentially leverage logic from the **Type Shadow Store Prevalidation** concept to offer contextually intelligent suggestions, such as valid next nodes in a pipe or compatible shared store keys based on the output of a preceding node.
    5. Generate a list of possible completions based on this context.
    6. Print these suggestions to standard output, typically one suggestion per line.

### 2.4 Types of Suggestions

Based on the context, `pflow` autocomplete will suggest:

* **Node Names:**
  * Available nodes from the registry, e.g., `core/yt-transcript`.
  * Could include version specification hints, e.g., `core/yt-transcript@1.0.0`.
* **Flags (Shared Store Keys & Parameters):**
  * Following the "Type flags; engine decides" rule.
  * Suggesting natural interface keys for shared store data injection, e.g., `--url`, `--text`.
  * Suggesting node-specific parameters, e.g., `--temperature`, `--max-tokens`.
  * Suggesting execution configuration flags, e.g., `--max-retries`, `--use-cache`.
* **Parameter Values:**
  * For parameters with a predefined set of choices (e.g., from an enum in metadata like `format: "json" | "markdown"`).
  * Boolean values (`true`/`false`).
  * Potentially file paths or directory names for relevant parameters.
* **Action Names:**
  * For action-based transitions, suggesting valid actions a node can return, e.g., after `validator - "`.
* **Flow Operators:**
  * Suggesting `>>` or `-` after a node name.

### 2.5 Shell Displays Suggestions

* The shell captures the list of suggestions printed by `pflow` and displays them to the user, allowing them to select one to complete their command.

## 3. Alignment with `pflow` System & Design Principles

This feature integrates seamlessly with and reinforces the existing `pflow` architecture and its core philosophies.

### 3.1 Leveraging Existing Architecture

* **Node Metadata as Data Source:** Autocomplete will heavily rely on the structured JSON Node Metadata, which describes node interfaces (inputs, outputs, shared keys), parameters, actions, and descriptions. This metadata is already crucial for the planner. The "Performance Architecture" for the registry, designed for fast metadata access by the planner, will also benefit autocomplete.
* **Unified Registry:** The central registry will serve as the source for discovering available nodes, including their namespaces and versions, for both manually written and MCP wrapper nodes.
* **"Type Flags; Engine Decides" Algorithm:** The autocomplete logic will be built to understand this core CLI resolution rule, providing appropriate suggestions for data injection keys (shared store) or parameter overrides based on the current command structure.
* **Type Shadow Store Prevalidation Concept:** The planner's concept of a "type shadow store" for real-time compatibility checking during CLI composition can be directly extended or utilized by the autocomplete feature to offer more intelligent suggestions, such as valid next nodes in a pipeline or compatible shared store keys based on the output types of preceding nodes.

### 3.2 Reinforcing Core Concepts & Design Philosophy

* **Explicit Over Magic & Transparency:** By presenting available options, autocomplete makes the system's capabilities and expected inputs explicit, aligning with the "Explicit Over Magic" principle.
* **Natural Interfaces & Shared Store Visibility:** Suggesting natural shared store keys (e.g., `shared["url"]`, `shared["text"]`) and parameters makes these core concepts more accessible and understandable at the point of CLI interaction.
* **Educational Design & Progressive Learning:** Autocomplete serves as an interactive learning tool. Users see valid syntax and options as they type, which helps them understand `pflow`'s CLI patterns and the structure of nodes and flows. This directly supports the "Educational Design Rationale," "Learning Scaffolding," and "Progressive Learning Through Transparency" goals.
* **Reduced Cognitive Load & Enhanced Developer Experience:** Minimizing the need to memorize node interfaces, parameter names, or shared key conventions makes `pflow` easier and faster to use, which is a key benefit of the Shared Store + Proxy pattern.
* **Metadata-Driven Operations:** The feature's reliance on node metadata for suggestions aligns with `pflow`'s broader strategy of using metadata for planning, validation, and other operations.

### 3.3 Supporting User Workflows

* **Exploration and Learning:** Autocomplete greatly aids the initial "Exploration" and "Learning" phases of the user journey by making it easier to discover nodes and try out different parameters.
* **Iteration and Refinement:** During the "Iteration" phase, autocomplete speeds up the process of tuning parameters and evolving flow definitions.

## 4. Benefits Summary

* **Increased Usability:** Makes `pflow` significantly easier to use, especially for new users or those working with many different nodes.
* **Reduced Errors:** Prevents common typographical errors and usage of incorrect flags or node names.
* **Enhanced Discoverability:** Allows users to explore `pflow`'s capabilities (nodes, parameters, shared keys, actions) interactively.
* **Improved Learning Curve:** Acts as an implicit guide, helping users learn the correct syntax and available options.
* **Boosted Productivity:** Enables faster authoring and modification of `pflow` command lines and flows.
* **Strengthened Adherence to Patterns:** Subtly guides users towards idiomatic `pflow` usage by suggesting standard natural interface keys and parameters.

This feature is a natural extension of `pflow`'s existing architecture and directly supports its goals of user-friendliness, explicitness, and learnability.

## 5. Implementation plan

A phased approach to implementation, starting with core suggestions (node names, flags) and progressively adding more sophisticated contextual awareness, would be a sensible way to manage complexity and deliver value incrementally. The performance of the suggestion-generation call will be paramount.

See [Cli Autocomplete Feature Implementation Details](../implementation-details/autocomplete-impl.md) for the implementation details.
