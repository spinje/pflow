# Knowledge Synthesis for Subtask 7.1

## Relevant Patterns from Previous Tasks

- **Dynamic Import Pattern**: Task 5 established context manager pattern for safe imports - Essential for metadata extraction since we'll be introspecting imported classes
- **Two-Tier Naming Pattern**: Task 5's approach of checking explicit attributes first, then falling back - Could apply to extracting description (docstring first line vs class name)
- **Phased Error Handling**: Task 4's approach with distinct error contexts - Apply phases: node validation, docstring extraction, parsing, field extraction
- **Traditional Function Approach**: Task 4 used functions not PocketFlow nodes - Metadata extractor should be a utility class/function, not a node
- **Direct Testing Pattern**: Task 3's approach of bypassing CLI for internal testing - Test the extractor directly with real node classes

## Known Pitfalls to Avoid

- **Over-engineering**: Task 5 showed simple solutions often better - Don't create complex parsing machinery for simple bullet lists
- **Mocking Limitations**: Task 5 proved real imports catch more issues - Test with actual node imports, not mocked classes
- **Empty String Handling**: Task 11 warned about truthiness issues - When extracting fields, check existence not truthiness
- **Reserved Field Names**: Task 4 logging issue with "module" - Use clear field names in output dictionary

## Established Conventions

- **Error Namespace**: "metadata_extractor:" prefix for all errors - Following Task 2's convention
- **Structured Docstring Format**: Task 11 established the Interface pattern - Must parse this exact format, not theoretical variations
- **Registry Separation**: Task 4 - registry provides metadata only - Extractor works on classes, not registry data
- **Consistent Error Returns**: Task 11's pattern - Clear ValueError for non-nodes, graceful handling for missing data

## Codebase Evolution Context

- **Task 5 Foundation**: Scanner already extracts raw docstrings - We parse what Task 5 discovered, don't duplicate discovery
- **Task 6 Validation**: Established layered validation approach - Apply to metadata extraction: parse → validate → transform
- **Task 11 Nodes**: Created real nodes with proper docstrings - Use these as test cases and format reference
- **Interface Pattern**: All nodes use single-line bullet format - Not YAML, not structured format, just simple bullets

## Testing Strategy from Previous Tasks

- **Progressive Enhancement**: Start with basic functionality, add edge cases
- **Real Import Testing**: Use actual nodes from /src/pflow/nodes/file/
- **Invalid Case Documentation**: Test and document what happens with malformed input
- **Direct Component Testing**: Test extractor in isolation before integration

## Architecture Insights

- **Utility Pattern**: Like the compiler, this is a transformation utility
- **No Wrapper Classes**: Direct use of types and dictionaries
- **Clear Separation**: Extractor doesn't know about registry or runtime
- **Forgiving Parser**: Extract what's available, don't fail on partial data
