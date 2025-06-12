# Plan for Integrating CLI Autocomplete Documentation

## 1. Introduction

This document outlines a **focused and minimal** plan to integrate information about the CLI Autocomplete feature into the existing `pflow` documentation. The goal is to add this usability enhancement only where it provides clear, standalone value without being verbose or redundant.

## 2. Revised Guidelines for Integration

*   **Essential Only**: Add information only where autocomplete is a core part of the topic being discussed
*   **No Schema Changes**: Avoid any modifications to JSON schemas or data structures
*   **Minimal Footprint**: Prefer fewer, more meaningful additions over broad coverage
*   **Standalone Value**: Each addition must enhance the existing content meaningfully
*   **Implementation Reality**: Acknowledge this as a progressive feature that leverages existing pflow strengths

## 3. Revised Integration Points (Essential Only)

After careful consideration, only **two documents** need updates:

---

### 3.1 `PRD-pflow.md` (Master Product Requirements Document)

**Rationale**: As the source of truth for product features, this is the essential place to document CLI autocomplete.

*   **Target Section**: `4 · CLI Surface & Parameter Resolution`
*   **Proposed Addition**: Add new subsection `4.9 CLI Autocompletion`
    ```markdown
    #### 4.9 CLI Autocompletion

    `pflow` provides interactive command-line autocompletion to improve usability and reduce composition errors.

    *   **Setup**: `pflow completion <shell_name>` generates shell-specific completion scripts
    *   **Scope**: Node names, flags, parameter values, action names, and flow operators
    *   **Architecture**: Leverages existing Node Registry and metadata for intelligent suggestions

    This feature makes `pflow` syntax discoverable directly in the terminal, supporting the progressive learning philosophy.
    ```

*   **Target Section**: `Appendix A: Glossary of Key Terms`
*   **Proposed Addition**:
    ```markdown
    *   **CLI Autocomplete**: Interactive command-line completion providing real-time suggestions for nodes, flags, and syntax. Enabled via `pflow completion <shell_name>`.
    ```

---

### 3.2 `shared-store-cli-runtime-specification.md`

**Rationale**: This document specifically covers CLI behavior and user experience, making autocomplete directly relevant.

*   **Target Section**: `12 · Best practices & rationale`
*   **Proposed Addition**: Add new brief subsection `12.2 CLI Usability Enhancement`
    ```markdown
    ### 12.2 CLI Usability Enhancement

    **Interactive Autocomplete**: Autocompletion correctly distinguishes between shared store keys (for data injection) and node parameters (for behavior configuration), reinforcing the "Type flags; engine decides" resolution model. This contextual awareness helps users learn the distinction while reducing CLI composition errors.
    ```

---

## 4. Documents NOT Being Updated

The following documents do **not** need autocomplete additions:

*   **`shared-store-node-proxy-architecture.md`**: Autocomplete is not core to the architectural pattern
*   **`planner-responsibility-functionality-spec.md`**: While Type Shadow Store could support autocomplete, it's not essential to document this connection
*   **`node-discovery-namespacing-and-versioning.md`**: The registry connection is implied and obvious
*   **`json-schema-for-flows-ir-and-nodesmetadata.md`**: No schema changes needed; autocomplete uses existing metadata
*   **`runtime-behavior-specification.md`**: Autocomplete is not a runtime behavior

## 5. Summary

This focused approach adds CLI autocomplete documentation only in the two most relevant places:
1. **PRD** - Where all product features should be documented
2. **CLI Runtime Spec** - Where CLI user experience enhancements belong

This maintains the principle of adding necessary information without over-documenting or creating redundancy across multiple files.
