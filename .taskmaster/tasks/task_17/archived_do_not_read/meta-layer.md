> **Note**: PocketFlow serves a dual role in this project - see "The PocketFlow Meta Layer" section below for important architectural context.

### The PocketFlow Meta Layer

**Important Architectural Note**: pflow has a unique relationship with PocketFlow that operates on two distinct levels:

1. **User Level (The Product)**: pflow's purpose is to help users create and execute PocketFlow workflows. Users describe what they want in natural language or CLI syntax, and pflow compiles this into executable PocketFlow Flow objects. The end product is always a PocketFlow workflow.

2. **Implementation Level (The Tool)**: pflow itself uses PocketFlow internally for its own complex operations. Components like the workflow planner, IR compiler, and shell integration are implemented as PocketFlow flows.

This creates an intentional meta architecture: **we use PocketFlow to build a tool that helps users build PocketFlow workflows**. This is similar to how compilers are often written in their own language (bootstrapping).

**Benefits of this approach**:
- We validate PocketFlow's capabilities by using it ourselves (dogfooding)
- We ensure deep understanding of the framework we're exposing to users
- We get the same reliability benefits (retry logic, error handling) that we provide to users
- Complex orchestrations in pflow are as robust as the workflows it produces

**Clarity for implementers**: When you see PocketFlow used in pflow's codebase, it's our internal implementation choice. When users interact with pflow, they're creating their own PocketFlow workflows. These are separate but philosophically aligned uses of the same framework.
