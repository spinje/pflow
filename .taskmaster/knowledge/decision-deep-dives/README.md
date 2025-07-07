# Decision Deep Dives

This directory contains comprehensive analyses for complex architectural decisions that require extensive documentation beyond what fits comfortably in `decisions.md`.

## Purpose

While `decisions.md` provides concise decision records following the ADR (Architecture Decision Record) format, some decisions involve:
- Complex technical investigations
- Multiple failed approaches
- Extensive code examples
- Detailed root cause analysis
- Step-by-step debugging processes

These deep dives preserve the full context and learning process for future reference.

## Structure

Each subdirectory represents one decision deep dive:
```
decision-deep-dives/
├── README.md (this file)
├── pocketflow-parameter-handling/
│   ├── README.md (main analysis)
│   ├── investigation-process.md
│   └── code-examples.md
└── [future-decision-name]/
    ├── README.md
    └── supporting-docs.md
```

## When to Create a Deep Dive

Create a deep dive when:
- The investigation process itself provides valuable learning
- Multiple solutions were prototyped before finding the right one
- The decision involves subtle technical details that future developers need to understand
- The "why" behind the decision requires extensive explanation
- Code examples are needed to illustrate the problem and solution

## Relationship to decisions.md

- `decisions.md` contains the official decision record with standardized format
- Each decision in `decisions.md` can optionally reference a deep dive
- Deep dives are linked from decisions.md with: "See detailed analysis in `decision-deep-dives/[name]/`"

## Current Deep Dives

### pocketflow-parameter-handling
**Decision**: Modify PocketFlow Instead of Using Wrapper for Parameter Handling
**Date**: 2025-01-07
**Summary**: Investigation into why PocketFlow overwrites node parameters and how to resolve the conflict with pflow's parameter model.

Key findings:
- PocketFlow's parameter overwriting is intentional for BatchFlow support
- pflow uses parameters differently (static config vs dynamic runtime values)
- Temporary modification chosen over wrapper pattern for MVP simplicity
