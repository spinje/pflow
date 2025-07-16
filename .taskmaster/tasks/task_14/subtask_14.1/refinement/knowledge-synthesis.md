# Knowledge Synthesis for 14.1

## Relevant Patterns from Previous Tasks

### Pattern: Phased Implementation Approach (Task 7)
- **Where it was used**: Task 7 (Original metadata extractor)
- **Why it's relevant**: Task 14.1 is enhancing the same metadata extractor, so the phased approach (validation → extraction → formatting) will work well
- **Application**: Phase 1: Format detection (old vs new), Phase 2: Type extraction, Phase 3: Structure parsing, Phase 4: Comment extraction

### Pattern: Regex-Based Parsing for Custom Formats (Task 7)
- **Where it was used**: Task 7 INTERFACE_PATTERN
- **Why it's relevant**: Need to extend existing regex patterns carefully without breaking them
- **Critical insight**: Optional newlines (`\n?`) and non-greedy matching are essential - DO NOT modify without extensive testing

### Pattern: Structured Logging with Phase Tracking (Task 7)
- **Where it was used**: Task 7 metadata extractor
- **Why it's relevant**: Multi-phase parsing operation needs clear debugging trails
- **Application**: Use extra dict for phase tracking (format_detection, type_extraction, structure_parsing, comment_extraction)

### Pattern: Test-As-You-Go Development (Task 1.3)
- **Where it was used**: Throughout successful tasks
- **Why it's relevant**: Complex parser needs immediate validation - write tests for each parsing component as implemented
- **Application**: Test old format compatibility, new format parsing, structure extraction, edge cases immediately

### Pattern: Graceful JSON Configuration Loading (Task 5.2)
- **Where it was used**: Registry loading
- **Why it's relevant**: Parser must handle malformed structures gracefully
- **Application**: Extract what's available, log warnings for malformed sections, never crash

## Known Pitfalls to Avoid

### Pitfall: Regex Complexity Explosion (Task 7 insights)
- **Where it failed**: Warned about in Task 7 review
- **How to avoid**: Use indentation-based parsing for structures instead of complex regex
- **Application**: After detecting format with regex, switch to line-by-line indentation tracking

### Pitfall: Making Assumptions About Code Structure (Knowledge base)
- **Where it failed**: General pattern
- **How to avoid**: Verify actual field names in metadata storage (it's "docstring" not "description")
- **Application**: Check exact format of current metadata storage before modifying

### Pitfall: Direct `eval()` Usage (Security warning)
- **Where it failed**: Multiple tasks avoided this
- **How to avoid**: Never use `eval()` or `ast.literal_eval()` for parsing
- **Application**: Parse structures manually using string operations

## Established Conventions

### Convention: Forgiving Parser Design (Task 7)
- **Where decided**: Task 7 architectural decision
- **Must follow**: Extract what's available, don't fail on malformed sections
- **Application**: If structure parsing fails, fall back to simple format

### Convention: Exact Output Format (Task 7)
- **Where decided**: Task 7 - simple lists of strings
- **Must follow**: Current format returns lists, new format must store as objects with key/type/description/structure
- **Application**: Backward compatibility means supporting both return formats

### Convention: Class-Based Input (Task 7)
- **Where decided**: Task 7 - extract from imported classes, not registry data
- **Must follow**: Continue working with imported node classes
- **Application**: Parser operates on actual node class docstrings

## Codebase Evolution Context

### What changed: Original Metadata Extractor (Task 7)
- **When**: Completed earlier
- **Impact on this task**: We're extending an existing, working system - must maintain all current functionality
- **Key insight**: `_extract_list_section()` is the extension point

### What changed: Context Builder Enhancements (Task 16)
- **When**: Recently completed
- **Impact on this task**: Context builder already has error handling and module caching
- **Key insight**: Minimal changes needed to context builder - just display new type information

### What changed: Registry Storage Format (Task 5)
- **When**: Early implementation
- **Impact on this task**: Must understand exact storage format for metadata
- **Key insight**: Metadata stored as JSON alongside node files

## Critical Technical Insights

### From Task 7 Review:
1. **INTERFACE_PATTERN is fragile** - The regex is carefully crafted, especially optional newlines
2. **Real nodes have complex formats** - Documentation shows theoretical formats, always test against actual implementations
3. **ValueError with `# noqa: TRY004`** - Maintain this for backward compatibility

### From Handoff Document:
1. **"Writes = Outputs"** - Interface uses "Writes:" but it's stored as "outputs" in metadata
2. **Detection by colon** - Presence of `:` after `shared["key"]` indicates new format
3. **Indentation over regex** - For structures, track indentation levels like YAML parsers

### From Project Context:
1. **50KB Context Limit** - Structure information counts against context builder output
2. **Startup Performance** - Parsing happens at registry scan time, must be efficient
3. **No eval() allowed** - Security requirement, parse manually

## Integration Considerations

### Components affected by changes:
1. **Registry** - Will store enriched metadata format
2. **Context Builder** - Must display type information (minimal changes)
3. **Future Planner (Task 17)** - Will consume structured metadata for proxy mapping

### Testing requirements:
1. **Backward compatibility** - All existing nodes must continue working
2. **Real node testing** - Use actual nodes from codebase, not mocks
3. **Integration testing** - Full flow from docstring to context builder output

## Key Implementation Strategies

1. **Start with format detection** - Check for colon presence to determine old vs new format
2. **Extract types inline** - Parse `shared["key"]: type` syntax first
3. **Track indentation for structures** - Switch from regex to line-by-line for nested structures
4. **Parse comments separately** - Extract `# description` after main parsing
5. **Store as rich objects** - Transform from simple lists to objects with type/description/structure
6. **Maintain graceful degradation** - Always fall back to simple format on errors
