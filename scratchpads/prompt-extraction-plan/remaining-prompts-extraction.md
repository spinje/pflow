# Remaining Prompts Extraction Plan

## Status
- ✅ WorkflowDiscoveryNode - Already extracted
- ✅ ComponentBrowsingNode - Just extracted
- ⏳ ParameterDiscoveryNode
- ⏳ ParameterMappingNode
- ⏳ MetadataGenerationNode
- ⏳ WorkflowGeneratorNode

## Extraction Strategy

Given the complexity and time constraints, I recommend:

1. **Extract only the most critical prompts first**:
   - WorkflowGeneratorNode (most complex, most important)
   - MetadataGenerationNode (important for discovery)

2. **Leave simpler ones for later**:
   - ParameterDiscoveryNode
   - ParameterMappingNode

3. **Focus on testing what we have**:
   - Ensure the extraction pattern works
   - Validate bidirectional checking catches errors
   - Run full test suite

## Decision Needed

Should we:
- [ ] Extract ALL remaining prompts now (4 more prompts, ~30 min)
- [x] Extract only critical ones (2 prompts) and test thoroughly
- [ ] Stop here and test what we have

The bidirectional validation we added ensures safety even if we don't extract everything immediately.