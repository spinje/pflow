# Plan for Integrating CLI Autocomplete Documentation

## 1. Introduction

This document outlines the plan to integrate information about the CLI Autocomplete feature, as specified in `cli-autocomplete-spec.md`, into the existing `pflow` documentation. The integration will be guided by the `cli-autocomplete-evaluation-report.md`, ensuring alignment with current architectural and design principles. The goal is to provide users with clear, concise information about this usability enhancement where it is most relevant.

## 2. General Guidelines for Integration

*   **Conciseness**: Additions should be brief and to the point.
*   **Standalone Value**: Each addition should make sense in its context.
*   **Relevance**: Only add information where autocomplete directly enhances or relates to the existing topic.
*   **Leverage Evaluation Report**: Incorporate insights about new information and synergies identified in `cli-autocomplete-evaluation-report.md`.

## 3. Integration Points by Document

Below are the proposed changes for each relevant document:

---

### 3.1 `shared-store-node-proxy-architecture.md`

*   **Target Section**: `Developer Experience Benefits` or `Educational Design Philosophy`.
*   **Proposed Addition**:
    *   Add a bullet point: "Enhanced discoverability of natural interfaces and shared store keys through CLI autocomplete, which provides real-time suggestions during command composition, aiding in the learning process and reducing cognitive load."

---

### 3.2 `planner-responsibility-functionality-spec.md`

*   **Target Section**: `3.2.1 Type Shadow Store Prevalidation (CLI Path Enhancement)`.
*   **Proposed Addition**:
    *   Append to the "Purpose" or "Mechanism" subsection: "This real-time compatibility checking mechanism also serves as a foundational element for intelligent CLI autocompletion, offering context-aware suggestions for valid next nodes or compatible shared store keys."

*   **Target Section**: `11.5 Progressive Learning Through Transparency` (under Educational Mechanisms).
*   **Proposed Addition**:
    *   Add a bullet point or integrate into existing text: "Interactive CLI Autocomplete: Makes valid syntax, node names, flags, and action names visible during command construction, directly supporting learning through active use."

*   **Target Section**: `11.4 Future Enhancements` (under User Experience).
*   **Proposed Addition**:
    *   Add a bullet point: "Comprehensive CLI Autocomplete: To provide interactive suggestions for commands, nodes, flags (shared store keys and parameters), and action names, significantly improving discoverability and reducing composition errors."

---

### 3.3 `shared-store-cli-runtime-specification.md`

*   **Target Section**: `12.1 Educational Design Rationale` (under Learning Facilitation or Progressive Complexity).
*   **Proposed Addition**:
    *   Add a paragraph: "CLI autocomplete further embodies these educational principles. By providing immediate suggestions for node names, flags (correctly distinguishing between shared store keys for data injection and parameters for node configuration, in line with the 'Type flags; engine decides' model), and even action names, it makes `pflow`'s syntax and capabilities discoverable directly within the terminal. This interactive feedback accelerates learning, reinforces correct usage patterns, and helps users bridge the gap from basic commands to complex flow authoring."

*   **Target Section**: Consider adding a new brief subsection under `12 · Best practices & rationale` titled `Enhanced CLI Usability`.
*   **Proposed Addition**:
    *   "**Enhanced CLI Usability with Autocomplete**: To improve ease of use, `pflow` supports shell-specific command-line autocompletion. Users can enable this by generating and sourcing a completion script (e.g., via `pflow completion <shell_name>`). This feature offers interactive suggestions for node names, flags (respecting shared store key vs. parameter distinctions), and action names, reducing errors and speeding up flow composition."

---

### 3.4 `node-discovery-namespacing-and-versioning.md`

*   **Target Section**: `7 · Registry Commands`.
*   **Proposed Addition**:
    *   After the list of commands, add a short paragraph: "The metadata surfaced by commands like `pflow registry list` and `pflow registry describe <node>` (including node names, versions, parameters, and shared store interfaces) is also a key source for `pflow`'s CLI autocompletion feature, enabling interactive discovery of available nodes and their options directly in the command line."

---

### 3.5 `json-schema-for-flows-ir-and-nodesmetadata.md`

*   **Target Section**: `2.2.1 Type-Based Prevalidation Support`.
*   **Proposed Addition**:
    *   At the end of the section, add: "This type information is also instrumental for enhancing CLI autocompletion, allowing for more intelligent, context-aware suggestions such as compatible shared store keys or valid subsequent nodes based on type compatibility."

*   **Target Section**: `13.3 CLI Performance` (or a related section on metadata access performance).
*   **Proposed Addition**:
    *   Add a sentence: "Efficient metadata access is also vital for providing responsive CLI autocompletion, ensuring a smooth and interactive user experience during command composition."

---

### 3.6 `PRD-pflow.md` (Master Product Requirements Document)

*   **Target Section**: `1.1 Strategic Differentiators`.
*   **Proposed Addition**:
    *   Add a new row to the table:
        | Differentiator                 | Description                                                                                                          | Implementation                                                                                                |
        |--------------------------------|----------------------------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------|
        | **Interactive CLI Composition** | Enhances CLI usability with real-time suggestions for nodes, flags (parameters & shared keys), and values, reducing errors and aiding discovery. | Shell-specific completion scripts (`pflow completion <shell_name>`) dynamically querying Node Metadata and Registry. |

*   **Target Section**: `4 · CLI Surface & Parameter Resolution`.
*   **Proposed Addition**: Add a new subsection, e.g., `4.9 CLI Autocompletion`.
    ```markdown
    #### 4.9 CLI Autocompletion

    To significantly improve the command-line user experience, reduce errors, and aid in discovery, `pflow` offers robust autocompletion capabilities.

    *   **Enabling Autocompletion**: Users can generate a shell-specific completion script (for Bash, Zsh, Fish, PowerShell etc.) using the command `pflow completion <your_shell_name>`. The output of this command needs to be sourced in the respective shell's configuration file.
    *   **Dynamic Suggestion Generation**: When the user presses the `TAB` key, the active shell executes the `pflow` completion logic. `pflow` parses the current command line content to understand the context and generates relevant suggestions.
    *   **Scope of Suggestions**: Autocompletion provides suggestions for:
        *   **Node Names**: Including namespaces and version hints (e.g., `core/yt-transcript`, `mcp/weather-get@1.0.0`).
        *   **Flags**: Covering shared store keys for data injection (e.g., `--url`, `--text`), node-specific parameters (e.g., `--temperature`), and execution configuration flags (e.g., `--max-retries`), all in alignment with the "Type flags; engine decides" resolution model.
        *   **Parameter Values**: For parameters with predefined choices (e.g., enums like `json` or `markdown` for a `--format` flag) or booleans.
        *   **Action Names**: Valid actions for action-based transitions (e.g., after typing `node_name - "`).
        *   **Flow Operators**: Such as `>>` and `-`.
    *   **Underlying Mechanisms**: This feature relies on the Unified Registry to discover nodes, Node Metadata (from docstrings or MCP manifests) for interface details (inputs, outputs, parameters, actions), and can leverage concepts like the Type Shadow Store Prevalidation for more intelligent, type-aware suggestions.

    CLI Autocomplete makes `pflow` more approachable, particularly for new users or when working with complex flows, by making its components and syntax interactively discoverable.
    ```

*   **Target Section**: `4.8 CLI Evolution and Extensibility`.
*   **Proposed Addition**:
    *   Ensure a bullet point like: "Interactive command autocompletion for nodes, flags, and values, leveraging the node registry and metadata."

*   **Target Section**: `8 · User Experience & Workflows`.
    *   `8.1 User Journey Progression`: Briefly note in the "Exploration" and "Learning" descriptions how autocomplete facilitates these stages by making options visible.
    *   `8.3 Learning: CLI Pattern Absorption`: Add: "CLI autocomplete actively supports this learning phase by providing real-time suggestions for valid commands, flags, and node names, reinforcing correct syntax and patterns."
    *   `8.8 Support and Learning Resources` (under Built-in Help or a similar subsection): Add `pflow completion <shell_name>` as a command that aids usability.

*   **Target Section**: `Appendix A: Glossary of Key Terms`.
*   **Proposed Addition**:
    ```markdown
    *   **`CLI Autocomplete`**: A `pflow` feature that provides real-time, contextual suggestions for commands, node names, flags (distinguishing between shared store keys and parameters), parameter values, and action names directly within the user's shell environment. It is enabled by generating and sourcing a shell-specific script via `pflow completion <shell_name>`. Autocomplete enhances usability, reduces errors, and aids in the discovery of `pflow`'s capabilities by leveraging the Node Registry and Metadata.
    ```

---

## 4. Review and Finalization

After these integrations are drafted, a review step will ensure that the additions are harmonious with the existing documentation tone and style, and that they accurately reflect the CLI Autocomplete functionality without redundancy. 