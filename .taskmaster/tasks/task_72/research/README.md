# MCP Server Organization Research - Index

**Research Question**: How should MCP servers organize their tools across files?

**Answer**: Use 4 files organized by functional domain (workflow, registry, settings, trace)

---

## 📚 Research Documents

### 1. Start Here: Executive Summary
**File**: `RESEARCH-SUMMARY.md`

**Purpose**: Quick answer with key findings and recommendations

**Read this if**: You want the TL;DR version with concrete recommendations

**Contents**:
- Quick answer (4 files by domain)
- Key findings from research
- Real-world examples
- Recommended structure
- Implementation checklist
- Conclusion with rationale

**Time to read**: 10 minutes

---

### 2. Detailed Research Analysis
**File**: `mcp-server-organization-research.md`

**Purpose**: Complete research findings with analysis and examples

**Read this if**: You want to understand the reasoning behind the recommendations

**Contents**:
- FastMCP decorator patterns
- Real-world MCP server examples (GitHub, FHIR, Mix)
- Import patterns comparison
- Performance analysis
- Tool grouping strategies
- Security best practices
- Complete rationale for 4-file approach

**Time to read**: 30 minutes

---

### 3. Visual Structure Guide
**File**: `recommended-file-structure.md`

**Purpose**: Visual diagrams and examples of the recommended structure

**Read this if**: You want to see the structure visually with diagrams

**Contents**:
- Complete directory tree
- Data flow diagrams
- Import flow visualization
- Complete tool file example
- Service layer example
- Why this structure works
- Alternatives rejected
- Migration guide

**Time to read**: 20 minutes

---

### 4. Ready-to-Use Templates
**File**: `implementation-templates.md`

**Purpose**: Copy-paste code templates for implementation

**Read this if**: You're ready to implement and want starter code

**Contents**:
- `server.py` template
- `main.py` template
- `tools/__init__.py` template
- Complete tool file templates (workflow, registry)
- Service layer templates
- Utility templates (errors, validation)
- Testing templates
- Usage examples

**Time to read**: 15 minutes (or just copy code)

---

### 5. FastMCP Research Files

These files contain the foundational research about FastMCP itself:

#### `mcp/server-basics.md`
- FastMCP initialization patterns
- Server setup and configuration
- Transport options (stdio, HTTP)
- Basic tool registration
- Running servers

#### `mcp/tool-implementation.md`
- Tool definition patterns
- Parameter schemas and validation
- Return types and formatting
- Async patterns
- Error handling
- **Instance method registration pattern** (critical!)
- Client-side operations

#### `mcp/advanced-patterns.md`
- Middleware patterns
- Server composition
- Progress reporting
- Stateless operation
- Security considerations

#### `mcp/error-handling-testing.md`
- Error handling in tools
- Context-based logging
- In-memory testing approach
- Mock client testing
- Test organization

#### `mcp/full-docs-mcp.md`
- Complete FastMCP reference
- Comprehensive documentation
- Use for deep dives (large file)

---

## 🎯 Quick Navigation

### "I want to understand the recommendation"
1. Read `RESEARCH-SUMMARY.md` (10 min)
2. Look at diagrams in `recommended-file-structure.md` (5 min)
3. **Total**: 15 minutes

### "I want the full context"
1. Read `RESEARCH-SUMMARY.md` (10 min)
2. Read `mcp-server-organization-research.md` (30 min)
3. Review `recommended-file-structure.md` (20 min)
4. **Total**: 60 minutes

### "I'm ready to implement"
1. Skim `RESEARCH-SUMMARY.md` for context (5 min)
2. Copy templates from `implementation-templates.md` (5 min)
3. Start coding with templates
4. **Total**: 10 minutes to start

### "I need to understand FastMCP basics"
1. Read `mcp/server-basics.md` (15 min)
2. Read `mcp/tool-implementation.md` (20 min)
3. Read `mcp/error-handling-testing.md` (15 min)
4. **Total**: 50 minutes

---

## 📊 Research Summary (Ultra-Quick)

### Question
How should we organize 13 pflow MCP tools across files?

### Answer
**4 files** organized by functional domain:

```
tools/
├── workflow_tools.py    # 6 tools
├── registry_tools.py    # 5 tools
├── settings_tools.py    # 2 tools
└── trace_tools.py       # 1 tool
```

### Key Patterns

1. **Central Server**: One `server.py` with FastMCP instance
2. **Auto-Import**: `tools/__init__.py` imports all tool modules
3. **Service Layer**: Stateless wrappers ensure fresh instances
4. **Module Functions**: Not classes (simpler, more Pythonic)

### Why Not Alternatives?

- ❌ **Single file**: 600-800 lines (too large, hard to maintain)
- ❌ **13 files**: Too granular (over-engineering, too many imports)
- ❌ **Classes**: Adds complexity without benefit for stateless tools

### Validation

- ✅ Follows production patterns (GitHub, FHIR, AWS MCP servers)
- ✅ No performance penalty
- ✅ Clear testing strategy
- ✅ Scales to future tools
- ✅ Pythonic and idiomatic

---

## 🔍 Key Insights from Research

### 1. FastMCP Decorator Pattern
Tools register **at import time** via `@mcp.tool()` decorators. Just import the modules and tools are automatically registered.

### 2. Stateless Operation (Critical!)
Never share service instances between requests. Always create fresh instances:

```python
# ✅ CORRECT
@mcp.tool()
async def workflow_execute(workflow: str) -> dict:
    manager = WorkflowManager()  # Fresh instance
    return await execute(manager, workflow)

# ❌ WRONG
manager = WorkflowManager()  # Shared - will go stale!

@mcp.tool()
async def workflow_execute(workflow: str) -> dict:
    return await execute(manager, workflow)  # STALE!
```

### 3. Service Layer Pattern
Use async wrappers to:
- Enforce stateless operation
- Convert sync pflow code to async
- Apply agent-optimized defaults
- Keep tools clean and simple

### 4. Real-World Validation
Production MCP servers (GitHub, FHIR, AWS) all use **multiple files grouped by domain**. Nobody uses single file for 10+ tools.

### 5. Import Pattern
Package init auto-import is cleanest:

```python
# tools/__init__.py
from . import workflow_tools
from . import registry_tools
from . import settings_tools
from . import trace_tools

# main.py
from . import tools  # Auto-imports all tools
```

---

## 📝 Implementation Checklist

- [ ] Create directory structure (`src/pflow/mcp_server/`)
- [ ] Create `server.py` with FastMCP instance
- [ ] Create `main.py` entry point
- [ ] Create `tools/` directory with `__init__.py`
- [ ] Implement `workflow_tools.py` (6 tools)
- [ ] Implement `registry_tools.py` (5 tools)
- [ ] Implement `settings_tools.py` (2 tools)
- [ ] Implement `trace_tools.py` (1 tool)
- [ ] Create `services/` directory with service wrappers
- [ ] Create `utils/` directory with helpers
- [ ] Write tests (mirror tool structure)
- [ ] Test with FastMCP in-memory client
- [ ] Test with real MCP client (Claude Code)
- [ ] Run `make test` and `make check`
- [ ] Document in CLAUDE.md

---

## 🎓 Learning Path

### Beginner (New to MCP/FastMCP)
1. Read `mcp/server-basics.md` - Understand FastMCP fundamentals
2. Read `mcp/tool-implementation.md` - Learn tool patterns
3. Read `RESEARCH-SUMMARY.md` - Understand organization recommendation
4. Use `implementation-templates.md` - Start coding

### Intermediate (Understand FastMCP)
1. Read `RESEARCH-SUMMARY.md` - Get the recommendation
2. Skim `mcp-server-organization-research.md` - Understand reasoning
3. Review `recommended-file-structure.md` - See visual structure
4. Use `implementation-templates.md` - Implement

### Advanced (Ready to Implement)
1. Skim `RESEARCH-SUMMARY.md` - Confirm understanding
2. Copy from `implementation-templates.md` - Get starter code
3. Refer to research files as needed - Answer questions

---

## 🔗 External References

### Official Documentation
- **FastMCP**: https://gofastmcp.com/servers/tools
- **MCP Protocol**: https://modelcontextprotocol.io/examples
- **FastMCP GitHub**: https://github.com/jlowin/fastmcp

### Real-World Examples
- **GitHub MCP Server**: https://github.com/github/github-mcp-server
- **FHIR MCP Server**: https://github.com/the-momentum/fhir-mcp-server
- **Official MCP Servers**: https://github.com/modelcontextprotocol/servers

### Community Discussions
- **FastMCP Discussion #948**: Modular tools organization
- **FastMCP Discussion #1312**: Multiple tool files best practices

---

## 🤔 FAQ

### Q: Why 4 files instead of 13?
**A**: 13 files is over-engineering. Tools naturally group into 4 functional domains (workflow, registry, settings, trace). This is the sweet spot between "one giant file" and "too many tiny files".

### Q: Why not use classes to organize tools?
**A**: Classes add boilerplate (init, self) and tempt shared state (breaks stateless requirement). Module-level functions are simpler and more Pythonic for stateless tools.

### Q: Does file organization affect performance?
**A**: No. Tools register once at import (one-time cost). Runtime execution is identical. Network transport overhead >> file structure overhead. Choose organization for humans, not machines.

### Q: What if we add more tools later?
**A**: Add to existing files if in same domain, or create new domain files if needed. The 4-file structure scales well to 20-30 tools before needing more files.

### Q: Should we use server composition?
**A**: Not for MVP. Server composition (mounting/importing sub-servers) is useful when splitting services across teams or creating reusable modules. Our 13 tools are cohesive and belong in one server. Consider for v2.0+ if needed.

### Q: How do we ensure stateless operation?
**A**: Use the service layer pattern. Service functions create fresh instances of WorkflowManager, Registry, etc. Never share instances between requests. Tests should verify concurrent requests don't interfere.

---

## 🎯 Bottom Line

**For pflow's 13 MCP tools, use 4 files organized by functional domain with a service layer for stateless operation.**

This recommendation is based on:
- ✅ Analysis of production MCP servers (GitHub, FHIR, AWS)
- ✅ FastMCP best practices and documentation
- ✅ Python idioms and community standards
- ✅ Maintainability and scalability considerations
- ✅ Zero performance penalty
- ✅ Clear testing strategy

**Start with `RESEARCH-SUMMARY.md` if you want the full context, or jump to `implementation-templates.md` if you're ready to code.**

---

*Research completed: 2025-10-11*
*Researcher: Claude Code*
*Confidence: High (validated against multiple production servers)*
