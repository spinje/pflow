**---- SPEC-WRITING-SPEC (Write\_Executable\_Specification) ----**

# Feature: write\_executable\_specification

## Objective

Create deterministic specification documents for implementation.

## Requirements

* The output must be a single Markdown file.
* All sections must appear **in order**, even if optional (use `- None`).
* All rules must be atomic and testable.
* Test Criteria must map to every Rule and Edge Case.
* Ambiguity, contradictions, or missing critical information must be surfaced (STOP or recorded in Epistemic Appendix if proceeding with assumptions).

## Scope

* Does not allow narrative explanations in operational sections.
* Does not allow vague, qualitative language.
* Does not merge multiple behaviors into a single rule.
* Does not omit the Epistemic Appendix.

## Inputs

* `feature_request`: str — natural-language description of the feature
* `codebase_context`: dict

  * `relevant_files`: list\[str]
  * `existing_patterns`: list\[str]
  * `constraints`: list\[str]

## Outputs

* Returns: A Markdown document with **exactly** these sections, in this order:

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
17. `## Epistemic Appendix`

    * **Assumptions & Unknowns**
    * **Conflicts & Resolutions**
    * **Decision Log / Tradeoffs**
    * **Ripple Effects / Impact Map**
    * **Residual Risks & Confidence**
    * **Epistemic Audit (Checklist Answers)**

All optional sections must still be present; if not relevant, write `- None`.

## Rules

### 1. Feature

* Format: `# Feature: <snake_case>`
* Derived from `feature_request`, ≤ 30 characters.

### 2. Objective

* One sentence, ≤ 15 words.
* Format: “Verb noun that achieves outcome”.
* No conjunctions (“and”, “or”, “but”).

### 3. Requirements

* Preconditions (dependencies, permissions, data sources).
* One per line, `- Must have <thing>`.
* No conditionals (“if X then Y”).

### 4. Scope

* Explicitly lists what the feature **does not** do.
* One exclusion per line, `- Does not <verb> <noun>`.

### 5. Inputs

* Each: `name: type - description`
* Python type hints syntax.
* Required first, optional last.
* No prose between items.

### 6. Outputs

* Start with `Returns:` or `Side effects:`.
* Specify exact types/structures.
* Include all possible output states.

### 7. Structured Formats (optional)

Use when structured data forms are involved (e.g., payloads, schemas, configs).

* Must be in machine-readable blocks (JSON, YAML, tables).
* One structure per entity.

### 8. State/Flow Changes (optional)

Use when lifecycle/process transitions exist.

* Format: `Current → New when <trigger>`.
* One transition per line.

### 9. Constraints (optional)

Use for validation, limits, permissions, resource caps.

* Each line: `- Constraint: <deterministic statement>`.

### 10. Rules

* Numbered list.
* Each is a **single** testable assertion.
* Format: `If X then Y` **or** `Do Z`.
* No `and/or` inside a rule.
* Ordered by execution sequence.

### 11. Edge Cases

* One per line, `Condition → expected behavior`.
* Cover empty inputs, None/nulls, boundary values, type mismatches.

### 12. Error Handling (optional)

* Map condition → response/action.
* Deterministic mappings only.

### 13. Non-Functional Criteria (optional)

* Performance, security, compliance, availability, etc.
* Each line: `- Metric: deterministic target`.

### 14. Examples (optional)

* Concrete valid/invalid cases.
* Structured (JSON, tables).
* Clearly label valid vs invalid.

### 15. Test Criteria

* Numbered tests.
* **Minimum**: 1 per Rule, 1 per Edge Case.
* Each test includes:

  * Setup conditions
  * Expected output (deterministic)
* Use concrete values, not variables.

### 16. Notes (Why)

* Rationale for decisions.
* No implementation hints.
* One per line, starting with `-`.

### 17. Epistemic Appendix

Mandatory. Contains:

**Assumptions & Unknowns**

* All assumptions taken due to missing clarity.
* All unresolved unknowns.

**Conflicts & Resolutions**

* Each conflict: source A vs source B → resolution + rationale.

**Decision Log / Tradeoffs**

* Alternatives considered, chosen option, and why.

**Ripple Effects / Impact Map**

* Dependencies touched, invariants affected, external systems impacted.

**Residual Risks & Confidence**

* Remaining risks, failure modes not mitigated, and a confidence rating (High/Medium/Low) with justification.

**Epistemic Audit (Checklist Answers)**

1. Unstated assumptions made
2. What breaks if wrong
3. Elegance vs robustness choice
4. Rule⇄Test mapping completeness
5. Ripple effects noted
6. Remaining uncertainty + confidence score

## Edge Cases (for this meta-spec)

* `feature_request` < 5 words → reject and request more detail.
* `feature_request` > 200 words → extract core feature.
* Missing `Inputs` section → invalid spec.
* Present optional section written in prose only → invalid (must be structured per rules).
* Rules containing conjunctions (`and`, `or`) → invalid (must be atomic).
* Test Criteria missing coverage for any Rule or Edge Case → invalid.

## Test Criteria (for this meta-spec)

1. **Structure order validation**
   Input: Any valid spec.
   Output: All 17 sections present in the exact order.

2. **Rule atomicity**
   Input: Spec with “Do X and Y” in a rule.
   Output: Validation fails.

3. **Input completeness**
   Input: Spec missing parameter types.
   Output: Validation fails.

4. **Edge case format**
   Input: Edge case containing explanation text.
   Output: Validation fails.

5. **Objective brevity**
   Input: Objective with > 15 words.
   Output: Validation fails.

6. **Requirements conditional**
   Input: Requirement containing “if X then Y”.
   Output: Validation fails.

7. **Scope negativity**
   Input: Scope item that states positive behavior.
   Output: Validation fails.

8. **Optional section misuse**
   Input: Structured Formats present but written in prose.
   Output: Validation fails.

9. **Test coverage completeness**
   Input: Spec where at least one Rule or Edge Case has no corresponding test.
   Output: Validation fails.

10. **Epistemic Appendix presence**
    Input: Spec lacking Epistemic Appendix.
    Output: Validation fails.

11. **Conflict protocol applied**
    Input: Provided contradictory sources (code vs docs) without Conflicts & Resolutions.
    Output: Validation fails.

12. **Self-reflection answered**
    Input: Missing Epistemic Audit answers.
    Output: Validation fails.
