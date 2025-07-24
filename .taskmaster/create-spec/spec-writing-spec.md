# Feature: write\_executable\_specification

## Objective

Define a deterministic, self-validating spec format for executable implementation.

## Requirements

* **Reflexivity:** This document is both the rulebook and a compliant instance of it. Every revision MUST pass its own Test Criteria; if not, the spec is invalid.
* Must output a single Markdown document.
* Must include **all sections in the exact order specified below** (optional sections use `- None` if not relevant).
* Every rule must be atomic and testable.
* **Test Criteria must cover every Rule and every Edge Case.**
* Ambiguity, contradictions, or missing critical information must be STOP conditions or explicitly listed in the **Epistemic Appendix → Assumptions & Unknowns**.
* Must include an **Epistemic Appendix**.

## Scope

* Does not allow narrative prose inside operational sections.
* Does not allow vague, qualitative language (e.g., “gracefully”, “appropriate”, “optimal”).
* Does not merge multiple behaviors into a single rule.
* Does not omit compliance mapping, version history, or epistemic audit.

## Inputs

* `feature_request`: str — natural-language description of the feature
* `codebase_context`: dict

  * `relevant_files`: list\[str]
  * `existing_patterns`: list\[str]
  * `constraints`: list\[str]

## Outputs

Returns: A single Markdown specification document containing **exactly** these sections, **in this order**:

1. `# Feature: <feature_name>`
2. `## Objective`
3. `## Requirements`
4. `## Scope`
5. `## Inputs`
6. `## Outputs`
7. `## Structured Formats` *(optional)*
8. `## State/Flow Changes` *(optional)*
9. `## Constraints` *(optional)*
10. `## Rules`
11. `## Edge Cases`
12. `## Error Handling` *(optional)*
13. `## Non-Functional Criteria` *(optional)*
14. `## Examples` *(optional)*
15. `## Test Criteria`
16. `## Notes (Why)`
17. `## Compliance Matrix`
18. `## Versioning & Evolution`
19. `## Epistemic Appendix`

    * Assumptions & Unknowns
    * Conflicts & Resolutions
    * Decision Log / Tradeoffs
    * Ripple Effects / Impact Map
    * Residual Risks & Confidence
    * Epistemic Audit (Checklist Answers)

All optional sections must still be present; if not relevant, write `- None`.

## Structured Formats

A machine-readable shape of the target spec, enabling automatic validation:

```json
{
  "sections_order": [
    "Feature",
    "Objective",
    "Requirements",
    "Scope",
    "Inputs",
    "Outputs",
    "Structured Formats",
    "State/Flow Changes",
    "Constraints",
    "Rules",
    "Edge Cases",
    "Error Handling",
    "Non-Functional Criteria",
    "Examples",
    "Test Criteria",
    "Notes (Why)",
    "Compliance Matrix",
    "Versioning & Evolution",
    "Epistemic Appendix"
  ],
  "constraints": {
    "feature_name": { "case": "snake_case", "max_length": 30 },
    "objective": { "max_words": 15, "no_conjunctions": true },
    "rules": { "atomic": true, "no_conjunctions": true },
    "tests": { "min_per_rule": 1, "min_per_edge_case": 1 }
  },
  "epistemic_appendix": {
    "required": true,
    "subsections": [
      "Assumptions & Unknowns",
      "Conflicts & Resolutions",
      "Decision Log / Tradeoffs",
      "Ripple Effects / Impact Map",
      "Residual Risks & Confidence",
      "Epistemic Audit (Checklist Answers)"
    ]
  }
}
```

## State/Flow Changes

* `draft` → `validated` when all **Test Criteria** pass
* `validated` → `accepted` when human reviewer approves
* `accepted` → `deprecated` when superseded by a newer version
* `deprecated` → `superseded` when explicitly replaced and archived

## Constraints

* Feature name: snake\_case, ≤ 30 characters.
* Objective: ≤ 15 words, imperative form, no conjunctions.
* Every Rule is atomic; no “and/or”.
* Every Rule and Edge Case must be covered by at least one Test.
* Optional sections must exist and use `- None` if not relevant.
* No vague terms across all operational sections.
* Exact section order is mandatory.

## Rules

1. Produce all sections in the exact prescribed order.
2. Use `snake_case` for the feature name, max 30 characters.
3. Keep the Objective to ≤ 15 words with no conjunctions.
4. Requirements must have no conditional phrasing.
5. Scope must list only explicitly excluded behavior.
6. Inputs must use `name: type - description` with Python type hints.
7. Outputs must start with `Returns:` or `Side effects:` and enumerate all result states.
8. Rules must be atomic, testable, and free of conjunctions.
9. Edge Cases must use `Condition → expected behavior`.
10. Test Criteria must include at least one test per Rule and Edge Case, with concrete values.
11. Optional sections must still be present; write `- None` when not relevant.
12. All ambiguities, assumptions, conflicts, and tradeoffs must be recorded in the Epistemic Appendix.
13. The Conflicts & Resolutions hierarchy is: code > verified tests > current spec > narrative docs.
14. Include a Compliance Matrix mapping each Rule to at least one Test Criteria case.
15. Include Versioning & Evolution with a version tag and change log.
16. No narrative leakage or rationale in operational sections (rationale only in Notes (Why) and Epistemic Appendix).
17. Perform self-validation; if any Test Criteria fail, rewrite before output.

## Edge Cases

* `feature_request` under 5 words → reject and request more detail.
* `feature_request` over 200 words → extract core feature only.
* Missing `Inputs` → invalid spec.
* Present but prose-only Structured Formats → invalid.
* Any Rule using “and/or” → invalid.
* Missing Epistemic Appendix → invalid.
* Test Criteria do not cover every Rule and Edge Case → invalid.
* Section order mismatch → invalid.

## Error Handling

* Missing section → Return spec with section present and `- None`, plus entry in **Conflicts & Resolutions**.
* Ambiguity detected → STOP and request clarification; if forced to continue, list assumptions in **Assumptions & Unknowns**.
* Conflict between doc/spec/code → Resolve per hierarchy and log in **Conflicts & Resolutions**.
* Rule not covered by tests → Fail validation; must add tests.
* Non-deterministic language detected → Fail validation; must rewrite.

## Non-Functional Criteria

* Fully machine-parseable structure.
* Deterministic, testable, and falsifiable statements.
* Stable section order for automated tooling.
* Minimal ambiguity budget (all residual ambiguity must be explicitly listed).

## Examples

### Minimal compliant (toy) example

```
# Feature: add_user_tag

## Objective
Add a tag to a user account deterministically.

## Requirements
- Must have user persistence layer
- Must have tag storage
- Must have authentication context

## Scope
- Does not remove existing tags
- Does not create new users
- Does not sync tags to external services

## Inputs
- user_id: str - Unique identifier of the user
- tag: str - Tag to add

## Outputs
Returns: bool - True on success, False on no-op

## Structured Formats
- None

## State/Flow Changes
Draft → Validated when tests pass
Validated → Accepted after review

## Constraints
- tag length ≤ 64
- user_id must exist

## Rules
1. If user_id does not exist then return False
2. If tag already present then return False
3. Do add tag to user
4. Do return True after successful insertion

## Edge Cases
user_id not found → return False
tag empty string → return False
tag length > 64 → return False

## Error Handling
user missing → return False
invalid tag → return False

## Non-Functional Criteria
- Operation completes ≤ 50ms P95
- Function is idempotent

## Examples
Valid:
{ "user_id": "u123", "tag": "pro" } → True
Invalid:
{ "user_id": "u999", "tag": "pro" } → False

## Test Criteria
1. Existing user, new tag → True
2. Existing user, duplicate tag → False
3. Missing user → False
4. Empty tag → False
5. Tag length 65 → False

## Notes (Why)
- Idempotency avoids duplicate tags
- Returning False on no-op simplifies client logic

## Compliance Matrix
Rule 1 → Tests 3
Rule 2 → Test 2
Rule 3 → Test 1
Rule 4 → Test 1

## Versioning & Evolution
- v1.0.0 — Initial example spec

## Epistemic Appendix
### Assumptions & Unknowns
- Assumes synchronous persistence layer
### Conflicts & Resolutions
- None observed
### Decision Log / Tradeoffs
- False on no-op chosen over exceptions for simplicity
### Ripple Effects / Impact Map
- Touches user repository only
### Residual Risks & Confidence
- Risk: silent failure on missing user; Confidence: High
### Epistemic Audit (Checklist Answers)
1. Assumed sync IO
2. Incorrect assumption → latency guarantees may fail
3. Prioritized robustness over elegance
4. All rules covered by tests
5. Minimal ripple effects
6. Remaining uncertainty: low; Confidence: High
```

## Test Criteria

1. **Section order** — All 19 sections appear in exact order.
2. **Atomic rules** — Any rule containing “and/or” fails validation.
3. **Objective brevity** — Objective > 15 words fails.
4. **Feature name constraints** — Not snake\_case or > 30 chars fails.
5. **Inputs typing** — Missing type hints fails.
6. **Outputs completeness** — Missing return/side-effect states fails.
7. **Optional sections presence** — Missing optional sections (without `- None`) fails.
8. **Structured Formats validity** — Present but prose-only fails.
9. **Rule coverage** — Any Rule without at least one test fails.
10. **Edge case coverage** — Any Edge Case without a test fails.
11. **Epistemic Appendix presence** — Missing appendix fails.
12. **Conflict protocol** — Conflicts not logged in **Conflicts & Resolutions** fails.
13. **Compliance Matrix** — Missing or incomplete mapping fails.
14. **Versioning & Evolution** — Missing version tag fails.
15. **Ambiguity handling** — Ambiguity not STOPped or logged as assumptions fails.
16. **Non-functional criteria** — Present but non-deterministic targets fail.
17. **Self-validation** — Any failed criterion without rewrite fails finalization.

## Notes (Why)

* Determinism enables mechanical translation to code.
* Atomic rules simplify validation and coverage tracing.
* The Epistemic Appendix isolates rationale and uncertainty without polluting operational clarity.
* Compliance Matrix guarantees bi-directional traceability between Rules and Tests.
* Versioning prevents silent drift in the governing standard.

## Compliance Matrix

| Rule # | Covered By Test Criteria # |
| ------ | -------------------------- |
| 1      | 1                          |
| 2      | 4                          |
| 3      | 3                          |
| 4      | 6                          |
| 5      | 7                          |
| 6      | 5                          |
| 7      | 6                          |
| 8      | 2, 9                       |
| 9      | 10                         |
| 10     | 9, 10                      |
| 11     | 7                          |
| 12     | 11, 12, 15                 |
| 13     | 12                         |
| 14     | 13                         |
| 15     | 14                         |
| 16     | 1, 3, 6, 7                 |
| 17     | 17                         |

## Versioning & Evolution

* **Version:** 2.0.0
* **Changelog:**

  * **2.0.0** — Added Structured Formats, State/Flow Changes, Constraints, Error Handling, Non-Functional Criteria, Examples, Compliance Matrix, Versioning & Evolution, and a mandatory Epistemic Appendix. Converted prior implicit constraints into explicit, testable conditions and added bi-directional Rule/Test traceability.
  * **1.x** — Earlier internal versions without self-compliance and epistemic auditing (deprecated).

## Epistemic Appendix

### Assumptions & Unknowns

* Assumes spec authors have (or can synthesize) enough determinism to avoid narrative leakage in operational sections.
* Assumes validating infrastructure can parse Markdown + machine-readable blocks reliably.

### Conflicts & Resolutions

* Prior versions allowed skipping optional sections. **Resolution:** Optional sections are now mandatory containers with `- None`.

### Decision Log / Tradeoffs

* Chose **mandatory Epistemic Appendix** over implicit behavior to ensure traceability of uncertainty and conflict resolution.
* Chose **fixed order for all sections** to simplify machine validation (at the cost of verbosity in simple specs).

### Ripple Effects / Impact Map

* Tooling (linters, generators, validators) must be updated to reflect the new sections and order.
* Any existing specs must be migrated or version-pinned.

### Residual Risks & Confidence

* Risk: Overhead for trivial features. Mitigation: allow `- None`.
* Risk: Over-constraining creativity in early exploration. Mitigation: STOP + clarify loop.
* Confidence: High.

### Epistemic Audit (Checklist Answers)

1. **Unstated assumptions:** Authors can conform to deterministic style; infra can parse structured blocks.
2. **Breakage if wrong:** Specs become unreadable for agents; validators fail; ambiguity re-enters pipeline.
3. **Elegance vs robustness:** Chose robustness (verbosity, explicitness) over elegance.
4. **Rule⇄Test mapping complete?** Yes (see Compliance Matrix).
5. **Ripple effects noted?** Yes (tooling, migration).
6. **Remaining uncertainty + confidence:** Minor on parsing stability. **Confidence: High**.
