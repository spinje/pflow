# Critical Decisions for Task 6: JSON IR Schema Implementation

## 1. Schema Implementation Technology - Importance: 4/5

The task previously mentioned "Pydantic models or JSON Schema definitions" but we need to choose one approach.

### Analysis:
- The documentation (schemas.md) shows JSON IR with `"$schema": "https://pflow.dev/schemas/flow-0.1.json"`
- This strongly suggests standard JSON Schema format
- Pydantic would provide runtime validation but adds complexity
- JSON Schema is language-agnostic and follows the "standard" mentioned in task

### Options:

- [x] **Option A: Use standard JSON Schema (json-schema.org format)**
  - Pros: Language-agnostic, standard format, matches documentation examples
  - Cons: Less Pythonic, requires separate validation library
  - Implementation: Define schema as Python dict/JSON, use jsonschema library for validation

- [ ] **Option B: Use Pydantic models**
  - Pros: Pythonic, built-in validation, type hints
  - Cons: Not standard JSON Schema format, harder to share schema
  - Implementation: Define Pydantic BaseModel classes

**Recommendation**: Option A - The documentation clearly shows standard JSON Schema usage with `$schema` field.

---

## 2. Template Variable Support in MVP - Importance: 3/5

Planner.md section 10.1 mentions template variables with `$variable` placeholders, but task says "keep it simple".

### Analysis:
- The MVP examples show variables like `$issue`, `$code_report` in workflow strings
- Template resolution is part of the "Plan Once, Run Forever" philosophy
- But the task explicitly says "Don't overengineer - we can extend later"

### Options:

- [ ] **Option A: Include full template support in schema**
  - Add `input_templates`, `template_dependencies`, `variable_resolution` fields
  - Pros: Matches planner documentation
  - Cons: More complex for MVP

- [x] **Option B: Defer template support to planner/runtime**
  - Keep IR schema simple, let templates be plain strings in params
  - Pros: Simpler schema, follows "don't overengineer" directive
  - Cons: May need schema update later

**Recommendation**: Option B - Keep schema minimal. Templates can be stored as strings in params and resolved at runtime.

---

## 3. Minimal vs Full Schema Structure - Importance: 5/5

Task says "minimal IR structure" but schemas.md shows envelope with metadata, versioning, etc.

### Analysis:
- Task example: `{'nodes': [...], 'edges': [...], 'start_node': 'n1'}`
- Schemas.md shows: Full envelope with `$schema`, `ir_version`, `metadata`, etc.
- Need to balance "minimal" with "sufficient for MVP needs"

### Options:

- [ ] **Option A: Truly minimal (just nodes, edges, start_node)**
  - Pros: Matches task example exactly
  - Cons: No versioning, no validation hook

- [x] **Option B: Minimal with essential metadata**
  - Include: nodes, edges, start_node (optional), mappings (optional)
  - Add minimal envelope: schema version for future compatibility
  - Pros: Future-proof, allows validation
  - Cons: Slightly more than bare minimum

**Recommendation**: Option B - Include minimal versioning for future compatibility while keeping structure simple.

---

## 4. Node Reference Field Name - Importance: 2/5

Task example uses 'type' field, but schemas.md uses 'registry_id'.

### Options:

- [x] **Option A: Use 'type' as shown in task example**
  - Pros: Simpler, matches task description
  - Cons: Less explicit about registry lookup

- [ ] **Option B: Use 'registry_id' as in schemas.md**
  - Pros: More explicit about registry system
  - Cons: Doesn't match task example

**Recommendation**: Option A - Follow the task example with 'type' field for simplicity.

---

## 5. Start Node Specification - Importance: 3/5

Task mentions "start_node id" but pocketflow can infer start from first node.

### Options:

- [x] **Option A: Make start_node optional**
  - Default to first node in nodes array if not specified
  - Pros: More flexible, matches pocketflow behavior
  - Cons: Less explicit

- [ ] **Option B: Always require start_node**
  - Pros: Explicit, no ambiguity
  - Cons: Redundant for simple linear flows

**Recommendation**: Option A - Optional start_node with sensible default behavior.

---

## 6. Action-based Edges Support - Importance: 4/5

Task mentions edges with "action" field but also emphasizes simple flows.

### Options:

- [x] **Option A: Include optional action field**
  - Default to "default" action if not specified
  - Pros: Future-ready, matches task description
  - Cons: Adds complexity

- [ ] **Option B: Defer actions entirely**
  - Only support simple from->to edges
  - Pros: Simpler for MVP
  - Cons: May need schema change later

**Recommendation**: Option A - Include as optional field with default value. Doesn't add much complexity.
