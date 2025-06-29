# Task 6 Readiness Assessment: Define JSON IR Schema

## Overall Status: ✅ READY TO IMPLEMENT

### Dependency Check
- **Blockers**: None ✅
- **Task 5 (Node Discovery)**: Complete ✅ - Can reference nodes by type
- **Task 7 (Metadata Extraction)**: Not needed ❌ - IR only stores node references
- **Task 9 (Proxy/Mappings)**: Not needed ❌ - Just define mappings structure

### Integration Points Analysis

#### 1. With Task 3 (Hello World Workflow)
- Task 3 needs to create a `hello_workflow.json` file
- Our schema must support the minimal workflow structure
- **Risk**: None - we control both schema and example file

#### 2. With Task 4 (IR-to-PocketFlow Compiler)
- Compiler needs to parse and validate our IR format
- Must support dynamic imports using registry metadata
- **Risk**: Low - clear contract between schema and compiler

#### 3. With Task 5 (Registry)
- Nodes referenced by 'type' must exist in registry
- Registry uses name like 'read-file', 'github-get-issue'
- **Risk**: None - Task 5 complete, naming convention established

#### 4. With Future Planner (Task unknown)
- Planner will generate IR conforming to our schema
- May need template variable support later
- **Risk**: Low - can extend schema in future versions

### Schema Design Considerations

#### What's Crystal Clear:
1. **Nodes array**: Each node has id, type, params
2. **Edges array**: Each edge has from, to, optional action
3. **Mappings object**: Optional, for proxy pattern
4. **JSON Schema format**: Use standard JSON Schema, not Pydantic

#### What Needs Decisions:
1. **Versioning**: How much metadata in envelope?
2. **Start node**: Required or optional?
3. **Template variables**: Include now or defer?
4. **Validation**: Where does validation code live?

### File Structure Plan
```
src/pflow/core/
├── __init__.py
├── ir_schema.py      # Schema definitions and validation functions
└── schemas/          # Future: actual .json schema files
    └── flow-0.1.json
```

### Implementation Approach
1. Define schema as Python dict initially (easier testing)
2. Export to JSON file later if needed
3. Include validation function using jsonschema library
4. Write comprehensive tests with valid/invalid examples

### Risk Assessment
- **Technical Risk**: Very Low - Standard JSON Schema is well understood
- **Integration Risk**: Low - Clear interfaces with dependent tasks
- **Future Compatibility**: Low - Versioning allows evolution

### Pre-Implementation Checklist
- [x] All dependencies complete or not needed
- [x] Clear understanding of minimal requirements
- [x] Integration points identified
- [x] Design decisions documented
- [x] No conflicting requirements found

### Potential Issues Found
1. **None critical** - All issues have clear solutions
2. **Minor**: Need to decide on schema location (Python dict vs JSON file)
3. **Minor**: Need to add jsonschema to dependencies

### Time Estimate
- Core implementation: 2-3 hours
- Tests: 2-3 hours
- Documentation: 1 hour
- Total: ~6 hours

### Conclusion
Task 6 is ready for implementation with the decisions documented in task-6-ir-schema-decisions.md. The main work is defining the schema structure and creating validation functions. No blockers or unclear requirements remain.
