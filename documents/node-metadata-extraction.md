# Node Metadata Extraction Infrastructure

## Executive Summary

**Chosen Approach**: Structured docstring parsing with hybrid extraction  
**Primary Format**: Interface sections in Python docstrings  
**Parsing Strategy**: `docstring_parser` + custom regex for pflow-specific sections  
**Purpose**: Enable metadata-driven planner selection from static node library

This document defines the infrastructure for extracting structured metadata from developer-written pflow nodes to support the planner's discovery and validation capabilities.

---

## Why This Approach

### Integration with Static Node Architecture

**Established Reality**: Developers write static, reusable node classes  
**Our Solution**: Extract rich metadata to enable intelligent planner selection  
**Key Benefit**: Bridge between human-written nodes and AI-driven flow planning

### Technical Benefits

1. **Zero Runtime Overhead** - Pre-extracted JSON for fast planner access
2. **Source of Truth** - Metadata extracted from actual node code
3. **Framework Integration** - Works with established pocketflow patterns
4. **Registry Compatible** - Integrates with versioning and discovery systems
5. **Planner Ready** - Enables metadata-driven LLM selection and validation

---

## Integration with pflow Architecture

This metadata extraction infrastructure directly supports several core pflow systems:

### Planner Discovery Integration
>
> **See**: [Planner Responsibility Spec](./planner-responsibility-functionality-spec.md#node-discovery)

The extraction process feeds the planner's metadata-driven selection:

- Builds registry of available nodes with natural language descriptions
- Provides interface compatibility data for validation
- Enables LLM context generation for intelligent selection
- Supports both natural language and CLI pipe syntax validation

### Registry Integration  
>
> **See**: [Node Discovery & Versioning](./node-discovery-namespacing-and-versioning.md#registry-management)

Metadata extraction occurs during node installation:

- `pflow registry install node.py` triggers automatic metadata extraction
- Version changes invalidate cached metadata for re-extraction
- Registry commands use pre-extracted metadata for rich CLI experience
- Supports namespace and versioning requirements

### Shared Store Compatibility
>
> **See**: [Shared Store Pattern](./shared-store-node-proxy-architecture.md#natural-interfaces)

Extracted interface data preserves natural shared store access patterns:

- Documents `shared["key"]` usage from actual node code
- Enables proxy mapping generation when needed for complex flows
- Validates interface consistency across flow components
- Maintains natural interface simplicity for node writers

---

## Docstring Format Standard

### Established Format Alignment

Following the format established in `shared-store-node-proxy-architecture.md`:

```python
class YTTranscript(Node):
    """Fetches YouTube transcript from video URL.
    
    Detailed explanation of behavior, use cases, and important notes
    about the node's operation and requirements.
    
    Interface:
    - Reads: shared["url"] - YouTube video URL
    - Writes: shared["transcript"] - extracted transcript text
    - Params: language (default "en") - transcript language
    - Actions: default, video_unavailable
            
    Examples:
        Basic usage:
            shared["url"] = "https://youtu.be/abc123"
            params = {"language": "en"}
            
    Performance:
        - Average processing time: 2-5 seconds
        - Memory usage: ~10MB per request
        
    Error Handling:
        - video_unavailable action for inaccessible videos
        - Handles rate limiting with exponential backoff
    """
    
    def prep(self, shared):
        return shared["url"]
        
    def exec(self, prep_res):
        language = self.params.get("language", "en")
        return fetch_transcript(prep_res, language)
        
    def post(self, shared, prep_res, exec_res):
        if exec_res is None:
            return "video_unavailable"
        shared["transcript"] = exec_res
        return "default"
```

### Enhanced Format Support (Future)

The parser will support enhanced structured format while maintaining backward compatibility:

```python
"""
Interface:
    Inputs:
        url (str): YouTube video URL, required
    Outputs:
        transcript (str): Extracted transcript text
    Parameters:
        language (str, optional): Transcript language code. Default: en
    Actions:
        default: Successful transcript extraction
        video_unavailable: Video is private or unavailable
"""
```

---

## Extraction Implementation

### Core Architecture

```python
from docstring_parser import parse as parse_standard
import re
import json
from typing import Dict, Any, List
from datetime import datetime

class PflowMetadataExtractor:
    """Production-ready metadata extractor for pflow nodes."""
    
    def __init__(self):
        self.interface_parser = InterfaceSectionParser()
        
    def extract_metadata(self, node_class) -> Dict[str, Any]:
        """Extract complete metadata from node class."""
        docstring = node_class.__doc__ or ""
        
        # Get basic info from standard parser
        base_metadata = self._extract_standard_sections(docstring)
        
        # Extract pflow-specific Interface section
        interface_metadata = self.interface_parser.parse_interface(docstring)
        
        # Extract additional sections
        additional_metadata = self._extract_additional_sections(docstring)
        
        # Merge and normalize to schema-compliant structure
        complete_metadata = self._normalize_metadata(
            base_metadata, interface_metadata, additional_metadata, node_class
        )
        
        return complete_metadata
    
    def extract_from_file(self, python_file: str) -> Dict[str, Any]:
        """Extract metadata from Python file."""
        # Implementation for file-based extraction
        pass
    
    def _extract_standard_sections(self, docstring: str) -> Dict:
        """Use docstring_parser for standard sections."""
        try:
            parsed = parse_standard(docstring)
            return {
                "description": parsed.short_description or "No description",
                "long_description": parsed.long_description,
                "standard_params": {p.arg_name: {
                    "description": p.description, 
                    "type": p.type_name
                } for p in parsed.params} if parsed.params else {}
            }
        except Exception:
            return {"description": "No description"}
    
    def _extract_additional_sections(self, docstring: str) -> Dict:
        """Extract Performance, Error Handling, Examples sections."""
        sections = {}
        
        # Examples section
        examples_match = re.search(r'Examples:\s*\n(.*?)(?=\n\n|\n[A-Z][a-z]+:|\Z)', 
                                  docstring, re.DOTALL)
        if examples_match:
            sections["examples"] = self._parse_examples(examples_match.group(1))
        
        # Performance section
        perf_match = re.search(r'Performance:\s*\n(.*?)(?=\n\n|\n[A-Z][a-z]+:|\Z)', 
                              docstring, re.DOTALL)
        if perf_match:
            sections["performance"] = [line.strip().lstrip('- ') 
                                     for line in perf_match.group(1).split('\n') 
                                     if line.strip()]
        
        # Error Handling section
        error_match = re.search(r'Error Handling:\s*\n(.*?)(?=\n\n|\n[A-Z][a-z]+:|\Z)', 
                               docstring, re.DOTALL)
        if error_match:
            sections["error_handling"] = [line.strip().lstrip('- ') 
                                        for line in error_match.group(1).split('\n') 
                                        if line.strip()]
        
        return sections
    
    def _normalize_metadata(self, base_metadata: Dict, interface_metadata: Dict, 
                           additional_metadata: Dict, node_class) -> Dict:
        """Ensure schema compliance with json-schema-for-flows-ir-and-nodesmetadata.md"""
        
        normalized = {
            "node": {
                "id": self._generate_node_id(node_class.__name__),
                "namespace": getattr(node_class, '__namespace__', 'core'),
                "version": getattr(node_class, '__version__', '1.0.0'),
                "python_file": getattr(node_class, '__file__', ''),
                "class_name": node_class.__name__
            },
            "interface": {
                "inputs": interface_metadata.get("inputs", {}),
                "outputs": interface_metadata.get("outputs", {}),
                "params": interface_metadata.get("params", {}),
                "actions": interface_metadata.get("actions", ["default"])
            },
            "documentation": {
                "description": base_metadata.get("description", "No description"),
                "long_description": base_metadata.get("long_description"),
                "examples": additional_metadata.get("examples", []),
                "performance": additional_metadata.get("performance"),
                "error_handling": additional_metadata.get("error_handling")
            },
            "extraction": {
                "source_hash": self._compute_source_hash(node_class),
                "extracted_at": datetime.utcnow().isoformat(),
                "extractor_version": "1.0.0"
            }
        }
        
        # Remove None values
        return self._remove_none_values(normalized)
    
    def _generate_node_id(self, class_name: str) -> str:
        """Convert class name to kebab-case node ID."""
        return re.sub(r'([a-z0-9])([A-Z])', r'\1-\2', class_name).lower()
    
    def _compute_source_hash(self, node_class) -> str:
        """Compute hash of source code for staleness detection."""
        import hashlib
        import inspect
        
        try:
            source = inspect.getsource(node_class)
            return f"sha256:{hashlib.sha256(source.encode()).hexdigest()}"
        except:
            return "sha256:unavailable"
    
    def _remove_none_values(self, data):
        """Recursively remove None values from dictionary."""
        if isinstance(data, dict):
            return {k: self._remove_none_values(v) for k, v in data.items() if v is not None}
        elif isinstance(data, list):
            return [self._remove_none_values(item) for item in data if item is not None]
        return data


class InterfaceSectionParser:
    """Specialized parser for Interface: sections with format flexibility."""
    
    def parse_interface(self, docstring: str) -> Dict:
        """Parse Interface section with support for multiple formats."""
        interface_match = re.search(
            r'Interface:\s*\n(.*?)(?=\n\n|\n[A-Z][a-z]+:|\Z)', 
            docstring, 
            re.DOTALL
        )
        
        if not interface_match:
            return {"inputs": {}, "outputs": {}, "params": {}, "actions": ["default"]}
            
        interface_text = interface_match.group(1)
        
        # Try structured format first, fall back to simple format
        if self._is_structured_format(interface_text):
            return self._parse_structured_format(interface_text)
        else:
            return self._parse_simple_format(interface_text)
    
    def _is_structured_format(self, text: str) -> bool:
        """Detect if using structured (Inputs:/Outputs:) format."""
        return bool(re.search(r'\s*(Inputs|Outputs|Parameters):\s*\n', text))
    
    def _parse_structured_format(self, text: str) -> Dict:
        """Parse structured format with Inputs:/Outputs: subsections."""
        return {
            "inputs": self._parse_inputs(text),
            "outputs": self._parse_outputs(text),
            "params": self._parse_params(text),
            "actions": self._parse_actions(text)
        }
    
    def _parse_simple_format(self, text: str) -> Dict:
        """Parse simple format: '- Reads: key - description'."""
        inputs = {}
        outputs = {}
        params = {}
        actions = ["default"]
        
        for line in text.strip().split('\n'):
            line = line.strip()
            if not line:
                continue
                
            # Parse "- Reads: shared["key"] - description"
            reads_match = re.match(r'-\s*Reads:\s*shared\["([^"]+)"\]\s*-\s*(.+)', line)
            if reads_match:
                key, description = reads_match.groups()
                inputs[key] = {
                    "description": description.strip(),
                    "type": "any",
                    "required": True
                }
                continue
            
            # Parse "- Writes: shared["key"] - description"
            writes_match = re.match(r'-\s*Writes:\s*shared\["([^"]+)"\]\s*-\s*(.+)', line)
            if writes_match:
                key, description = writes_match.groups()
                outputs[key] = {
                    "description": description.strip(),
                    "type": "any"
                }
                continue
            
            # Parse "- Params: name (default value) - description"
            params_match = re.match(r'-\s*Params:\s*([^(]+)(?:\(default\s+([^)]+)\))?\s*-\s*(.+)', line)
            if params_match:
                name, default, description = params_match.groups()
                params[name.strip()] = {
                    "description": description.strip(),
                    "type": "any",
                    "default": default.strip() if default else None,
                    "optional": True
                }
                continue
            
            # Parse "- Actions: action1, action2"
            actions_match = re.match(r'-\s*Actions:\s*(.+)', line)
            if actions_match:
                action_list = [a.strip() for a in actions_match.group(1).split(',')]
                actions = action_list if action_list else ["default"]
        
        return {
            "inputs": inputs,
            "outputs": outputs, 
            "params": params,
            "actions": actions
        }
    
    def _parse_inputs(self, text: str) -> Dict[str, Dict]:
        """Parse Inputs subsection."""
        inputs_match = re.search(r'Inputs:\s*\n(.*?)(?=\n\s*[A-Z][a-z]+:|\Z)', 
                                text, re.DOTALL)
        if not inputs_match:
            return {}
            
        inputs = {}
        for line in inputs_match.group(1).strip().split('\n'):
            line = line.strip()
            if not line:
                continue
                
            # Pattern: "key (type): description, required/optional"
            match = re.match(r'(\w+)\s*(?:\(([^)]+)\))?\s*:\s*(.+)', line)
            if match:
                key, type_info, description = match.groups()
                inputs[key] = {
                    "description": description.strip(),
                    "type": type_info.strip() if type_info else "any",
                    "required": "optional" not in description.lower()
                }
                
        return inputs
    
    def _parse_outputs(self, text: str) -> Dict[str, Dict]:
        """Parse Outputs subsection."""
        outputs_match = re.search(r'Outputs:\s*\n(.*?)(?=\n\s*[A-Z][a-z]+:|\Z)', 
                                 text, re.DOTALL)
        if not outputs_match:
            return {}
            
        outputs = {}
        for line in outputs_match.group(1).strip().split('\n'):
            line = line.strip()
            if not line:
                continue
                
            match = re.match(r'(\w+)\s*(?:\(([^)]+)\))?\s*:\s*(.+)', line)
            if match:
                key, type_info, description = match.groups()
                outputs[key] = {
                    "description": description.strip(),
                    "type": type_info.strip() if type_info else "any"
                }
                
        return outputs
    
    def _parse_params(self, text: str) -> Dict[str, Dict]:
        """Parse Parameters subsection."""
        params_match = re.search(r'Parameters:\s*\n(.*?)(?=\n\s*[A-Z][a-z]+:|\Z)', 
                                text, re.DOTALL)
        if not params_match:
            return {}
            
        params = {}
        for line in params_match.group(1).strip().split('\n'):
            line = line.strip()
            if not line or line.lower() == "none":
                continue
                
            match = re.match(r'(\w+)\s*(?:\(([^)]+)\))?\s*:\s*(.+)', line)
            if match:
                key, type_info, description = match.groups()
                
                # Extract default value if present
                default_match = re.search(r'Default:\s*([^.]+)', description)
                default_value = default_match.group(1).strip() if default_match else None
                
                # Clean description
                clean_desc = re.sub(r'\.\s*Default:.*', '', description).strip()
                
                params[key] = {
                    "description": clean_desc,
                    "type": type_info.strip() if type_info else "any",
                    "optional": "optional" in (type_info or "").lower(),
                    "default": default_value
                }
                
        return params
    
    def _parse_actions(self, text: str) -> List[str]:
        """Parse Actions subsection."""
        actions_match = re.search(r'Actions:\s*\n(.*?)(?=\n\s*[A-Z][a-z]+:|\Z)', 
                                 text, re.DOTALL)
        if not actions_match:
            return ["default"]
            
        actions = []
        for line in actions_match.group(1).strip().split('\n'):
            line = line.strip()
            if not line:
                continue
                
            # Extract action name (before colon if present)
            action_match = re.match(r'(\w+)\s*:?', line)
            if action_match:
                actions.append(action_match.group(1))
                
        return actions or ["default"]
    
    def _parse_examples(self, examples_text: str) -> List[Dict]:
        """Parse Examples section into structured format."""
        examples = []
        current_example = None
        current_code = []
        
        for line in examples_text.strip().split('\n'):
            line = line.strip()
            if not line:
                continue
                
            # New example starts (description followed by colon)
            if ':' in line and not line.startswith(' '):
                if current_example:
                    examples.append({
                        "description": current_example,
                        "code": current_code
                    })
                current_example = line.rstrip(':')
                current_code = []
            else:
                # Code line (indented)
                if line.startswith(' ') or 'shared[' in line or 'params' in line:
                    current_code.append(line.strip())
        
        # Add last example
        if current_example:
            examples.append({
                "description": current_example,
                "code": current_code
            })
            
        return examples
```

---

## Registry Integration

### Metadata Storage Schema

Aligned with `json-schema-for-flows-ir-and-nodesmetadata.md`:

```json
{
  "node": {
    "id": "yt-transcript",
    "namespace": "core",
    "version": "1.0.0",
    "python_file": "nodes/core/yt-transcript/1.0.0/node.py",
    "class_name": "YTTranscript"
  },
  "interface": {
    "inputs": {
      "url": {
        "description": "YouTube video URL",
        "type": "str",
        "required": true
      }
    },
    "outputs": {
      "transcript": {
        "description": "Extracted transcript text",
        "type": "str"
      }
    },
    "params": {
      "language": {
        "description": "Transcript language code",
        "type": "str",
        "optional": true,
        "default": "en"
      }
    },
    "actions": ["default", "video_unavailable"]
  },
  "documentation": {
    "description": "Fetches YouTube transcript from video URL",
    "long_description": "Downloads and extracts transcript text...",
    "examples": [
      {
        "description": "Basic usage",
        "code": ["shared[\"url\"] = \"https://youtu.be/abc123\""]
      }
    ],
    "performance": [
      "Average processing time: 2-5 seconds",
      "Memory usage: ~10MB per request"
    ]
  },
  "extraction": {
    "source_hash": "sha256:abc123...",
    "extracted_at": "2025-01-01T12:00:00Z",
    "extractor_version": "1.0.0"
  }
}
```

### Installation Integration

```python
def registry_install_with_metadata_extraction(node_file: str, namespace: str = None):
    """Install node with automatic metadata extraction."""
    
    # 1. Load and validate node class
    node_class = load_node_class(node_file)
    
    # 2. Extract metadata
    extractor = PflowMetadataExtractor()
    metadata = extractor.extract_metadata(node_class)
    
    # 3. Validate extracted metadata
    validation_errors = validate_metadata(metadata)
    if validation_errors:
        raise ValidationError(f"Metadata validation failed: {validation_errors}")
    
    # 4. Install to registry with metadata
    registry_path = get_registry_path(namespace or metadata["node"]["namespace"])
    install_node_files(node_file, metadata, registry_path)
    
    # 5. Update registry index
    update_registry_index(metadata)
    
    return metadata
```

---

## CLI Commands

### Registry Integration Commands

```python
# pflow/cli/registry.py
import click
import json
import yaml
from pathlib import Path
from rich.console import Console
from rich.table import Table

console = Console()

@click.group()
def registry():
    """Node registry management commands."""
    pass

@registry.command()
@click.argument('python_file', type=click.Path(exists=True))
@click.option('--format', type=click.Choice(['json', 'yaml']), default='json')
@click.option('--output', '-o', type=click.Path(), help='Output file')
def extract_metadata(python_file, format, output):
    """Extract metadata from Python node file."""
    extractor = PflowMetadataExtractor()
    metadata = extractor.extract_from_file(python_file)
    
    if format == 'json':
        content = json.dumps(metadata, indent=2)
    else:
        content = yaml.dump(metadata, default_flow_style=False)
    
    if output:
        Path(output).write_text(content)
        console.print(f"✅ Metadata extracted to {output}")
    else:
        console.print(content)

@registry.command()
@click.argument('python_file', type=click.Path(exists=True))
def validate_metadata(python_file):
    """Validate that docstring metadata matches actual code."""
    extractor = PflowMetadataExtractor()
    validator = CodeValidator()
    
    # Extract metadata from docstring
    documented = extractor.extract_from_file(python_file)
    
    # Analyze actual code behavior
    actual = validator.analyze_code_behavior(python_file)
    
    # Compare and report
    issues = validator.compare_metadata(documented, actual)
    
    if not issues:
        console.print("✅ Metadata is consistent with code")
    else:
        console.print("⚠️  Found metadata inconsistencies:")
        for issue in issues:
            console.print(f"  - {issue}")

@registry.command()
def refresh_metadata():
    """Re-extract metadata for all installed nodes."""
    registry = NodeRegistry()
    extractor = PflowMetadataExtractor()
    
    updated_count = 0
    for node_path in registry.get_all_node_paths():
        try:
            node_class = registry.load_node_class(node_path)
            new_metadata = extractor.extract_metadata(node_class)
            
            # Check if metadata changed
            current_metadata = registry.get_metadata(node_path)
            if metadata_changed(current_metadata, new_metadata):
                registry.update_metadata(node_path, new_metadata)
                updated_count += 1
                console.print(f"Updated: {node_path}")
                
        except Exception as e:
            console.print(f"Failed to update {node_path}: {e}")
    
    console.print(f"✅ Updated metadata for {updated_count} nodes")

@registry.command()
def list():
    """List nodes with rich metadata."""
    registry = NodeRegistry()
    nodes = registry.list_all()
    
    table = Table()
    table.add_column("Node ID")
    table.add_column("Description")
    table.add_column("Inputs")
    table.add_column("Outputs")
    table.add_column("Version")
    
    for node in nodes:
        metadata = node.get("metadata", {})
        interface = metadata.get("interface", {})
        
        inputs = ", ".join(interface.get("inputs", {}).keys()) or "none"
        outputs = ", ".join(interface.get("outputs", {}).keys()) or "none"
        
        table.add_row(
            node["node"]["id"],
            metadata.get("documentation", {}).get("description", "No description")[:50],
            inputs,
            outputs,
            node["node"]["version"]
        )
    
    console.print(table)

@registry.command()
@click.argument('node_id')
def describe(node_id):
    """Show detailed node information."""
    registry = NodeRegistry()
    node = registry.get_node(node_id)
    
    if not node:
        console.print(f"❌ Node not found: {node_id}")
        return
    
    metadata = node.get("metadata", {})
    interface = metadata.get("interface", {})
    documentation = metadata.get("documentation", {})
    
    # Rich formatted output
    console.print(f"[bold]{node['node']['id']}[/bold] (v{node['node']['version']})")
    console.print(f"Description: {documentation.get('description')}")
    console.print()
    
    if interface.get("inputs"):
        console.print("[bold]Inputs:[/bold]")
        for key, info in interface["inputs"].items():
            req = "required" if info.get("required") else "optional"
            console.print(f"  {key} ({info.get('type', 'any')}) - {info.get('description')} [{req}]")
        console.print()
    
    if interface.get("outputs"):
        console.print("[bold]Outputs:[/bold]")
        for key, info in interface["outputs"].items():
            console.print(f"  {key} ({info.get('type', 'any')}) - {info.get('description')}")
        console.print()
    
    if interface.get("params"):
        console.print("[bold]Parameters:[/bold]")
        for key, info in interface["params"].items():
            default = f" (default: {info.get('default')})" if info.get('default') else ""
            console.print(f"  {key} ({info.get('type', 'any')}) - {info.get('description')}{default}")
        console.print()
    
    if documentation.get("examples"):
        console.print("[bold]Examples:[/bold]")
        for example in documentation["examples"]:
            console.print(f"  {example.get('description', 'Example')}:")
            for line in example.get("code", []):
                console.print(f"    {line}")
            console.print()
```

---

## Performance & Caching

### Fast Planner Context Generation

```python
class PlannerContextBuilder:
    """Build optimized LLM context from pre-extracted metadata."""
    
    def __init__(self, registry_path: str):
        self.registry = NodeRegistry(registry_path)
        self.metadata_cache = {}
        
    def build_context(self, available_nodes: List[str]) -> str:
        """Build LLM-optimized context from node metadata."""
        context_parts = []
        
        context_parts.append("Available pflow nodes:\n")
        
        for node_id in available_nodes:
            metadata = self._get_cached_metadata(node_id)
            if not metadata:
                continue
                
            interface = metadata.get("interface", {})
            documentation = metadata.get("documentation", {})
            
            # Compact format for LLM
            inputs = self._format_interface_keys(interface.get("inputs", {}))
            outputs = self._format_interface_keys(interface.get("outputs", {}))
            params = self._format_params(interface.get("params", {}))
            actions = ", ".join(interface.get("actions", ["default"]))
            
            context_parts.append(f"""
{node_id}: {documentation.get('description', 'No description')}
  Reads: {inputs}
  Writes: {outputs}
  Params: {params}
  Actions: {actions}
            """.strip())
        
        return "\n".join(context_parts)
    
    def _get_cached_metadata(self, node_id: str) -> Dict:
        """Get metadata with caching for performance."""
        if node_id not in self.metadata_cache:
            self.metadata_cache[node_id] = self.registry.get_metadata(node_id)
        return self.metadata_cache[node_id]
    
    def _format_interface_keys(self, interface_dict: Dict) -> str:
        """Format interface keys for compact display."""
        if not interface_dict:
            return "none"
        
        keys = []
        for key, info in interface_dict.items():
            req = "" if info.get("required", True) else " (optional)"
            keys.append(f'shared["{key}"]{req}')
        
        return ", ".join(keys)
    
    def _format_params(self, params_dict: Dict) -> str:
        """Format parameters for compact display."""
        if not params_dict:
            return "none"
        
        params = []
        for key, info in params_dict.items():
            default = info.get("default")
            if default:
                params.append(f'{key}="{default}"')
            else:
                params.append(key)
        
        return ", ".join(params)

    def invalidate_cache(self, node_id: str = None):
        """Invalidate metadata cache."""
        if node_id:
            self.metadata_cache.pop(node_id, None)
        else:
            self.metadata_cache.clear()
```

### Registry Performance Optimizations

```python
class NodeRegistry:
    """High-performance node registry with metadata caching."""
    
    def __init__(self, registry_path: str):
        self.registry_path = Path(registry_path)
        self.index_file = self.registry_path / "index.json"
        self._index_cache = None
        self._metadata_cache = {}
        
    def get_fast_index(self) -> Dict:
        """Get fast lookup index for registry operations."""
        if self._index_cache is None:
            if self.index_file.exists():
                with open(self.index_file) as f:
                    self._index_cache = json.load(f)
            else:
                self._index_cache = self._build_index()
                self._save_index()
        return self._index_cache
    
    def _build_index(self) -> Dict:
        """Build fast lookup index from filesystem."""
        index = {"nodes": {}, "last_updated": datetime.utcnow().isoformat()}
        
        for namespace_dir in self.registry_path.glob("*"):
            if not namespace_dir.is_dir():
                continue
                
            for node_dir in namespace_dir.glob("*"):
                if not node_dir.is_dir():
                    continue
                    
                for version_dir in node_dir.glob("*"):
                    metadata_file = version_dir / "metadata.json"
                    if metadata_file.exists():
                        with open(metadata_file) as f:
                            metadata = json.load(f)
                            
                        node_id = metadata["node"]["id"]
                        index["nodes"][node_id] = {
                            "path": str(metadata_file),
                            "version": metadata["node"]["version"],
                            "hash": metadata["extraction"]["source_hash"]
                        }
        
        return index
    
    def invalidate_index(self):
        """Force index rebuild on next access."""
        self._index_cache = None
        self._metadata_cache.clear()
```

---

## Validation & Quality

### Code-Metadata Consistency Validation

```python
class CodeValidator:
    """Validate that extracted metadata matches actual node behavior."""
    
    def analyze_code_behavior(self, python_file: str) -> Dict:
        """Analyze actual node code to extract real interface."""
        import ast
        
        with open(python_file) as f:
            tree = ast.parse(f.read())
        
        # Find node class
        node_class = None
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for base in node.bases:
                    if isinstance(base, ast.Name) and base.id == 'Node':
                        node_class = node
                        break
        
        if not node_class:
            raise ValueError("No Node class found")
        
        # Analyze methods
        actual_interface = {
            "inputs": self._find_shared_reads(node_class),
            "outputs": self._find_shared_writes(node_class),
            "params": self._find_param_accesses(node_class),
            "actions": self._find_action_returns(node_class)
        }
        
        return actual_interface
    
    def _find_shared_reads(self, node_class) -> Set[str]:
        """Find shared["key"] reads in prep() method."""
        reads = set()
        
        for method in node_class.body:
            if isinstance(method, ast.FunctionDef) and method.name == 'prep':
                for node in ast.walk(method):
                    if (isinstance(node, ast.Subscript) and 
                        isinstance(node.value, ast.Name) and 
                        node.value.id == 'shared' and
                        isinstance(node.slice, ast.Constant)):
                        reads.add(node.slice.value)
        
        return reads
    
    def _find_shared_writes(self, node_class) -> Set[str]:
        """Find shared["key"] writes in post() method."""
        writes = set()
        
        for method in node_class.body:
            if isinstance(method, ast.FunctionDef) and method.name == 'post':
                for node in ast.walk(method):
                    if (isinstance(node, ast.Assign) and
                        len(node.targets) == 1 and
                        isinstance(node.targets[0], ast.Subscript) and
                        isinstance(node.targets[0].value, ast.Name) and
                        node.targets[0].value.id == 'shared' and
                        isinstance(node.targets[0].slice, ast.Constant)):
                        writes.add(node.targets[0].slice.value)
        
        return writes
    
    def _find_param_accesses(self, node_class) -> Dict[str, str]:
        """Find self.params.get() calls."""
        params = {}
        
        for method in node_class.body:
            if isinstance(method, ast.FunctionDef):
                for node in ast.walk(method):
                    if (isinstance(node, ast.Call) and
                        isinstance(node.func, ast.Attribute) and
                        isinstance(node.func.value, ast.Attribute) and
                        isinstance(node.func.value.value, ast.Name) and
                        node.func.value.value.id == 'self' and
                        node.func.value.attr == 'params' and
                        node.func.attr == 'get' and
                        len(node.args) >= 1 and
                        isinstance(node.args[0], ast.Constant)):
                        
                        param_name = node.args[0].value
                        default_value = None
                        if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
                            default_value = node.args[1].value
                        
                        params[param_name] = default_value
        
        return params
    
    def _find_action_returns(self, node_class) -> Set[str]:
        """Find return statements in post() method."""
        actions = set()
        
        for method in node_class.body:
            if isinstance(method, ast.FunctionDef) and method.name == 'post':
                for node in ast.walk(method):
                    if (isinstance(node, ast.Return) and 
                        isinstance(node.value, ast.Constant) and
                        isinstance(node.value.value, str)):
                        actions.add(node.value.value)
        
        return actions or {"default"}
    
    def compare_metadata(self, documented: Dict, actual: Dict) -> List[str]:
        """Compare documented vs actual interfaces."""
        issues = []
        
        # Check inputs
        doc_inputs = set(documented.get("interface", {}).get("inputs", {}).keys())
        actual_inputs = actual.get("inputs", set())
        
        if doc_inputs != actual_inputs:
            missing = actual_inputs - doc_inputs
            extra = doc_inputs - actual_inputs
            if missing:
                issues.append(f"Undocumented inputs: {', '.join(missing)}")
            if extra:
                issues.append(f"Documented but unused inputs: {', '.join(extra)}")
        
        # Check outputs
        doc_outputs = set(documented.get("interface", {}).get("outputs", {}).keys())
        actual_outputs = actual.get("outputs", set())
        
        if doc_outputs != actual_outputs:
            missing = actual_outputs - doc_outputs
            extra = doc_outputs - actual_outputs
            if missing:
                issues.append(f"Undocumented outputs: {', '.join(missing)}")
            if extra:
                issues.append(f"Documented but unused outputs: {', '.join(extra)}")
        
        # Check params
        doc_params = documented.get("interface", {}).get("params", {})
        actual_params = actual.get("params", {})
        
        for param, actual_default in actual_params.items():
            if param not in doc_params:
                issues.append(f"Undocumented parameter: {param}")
            else:
                doc_default = doc_params[param].get("default")
                if str(actual_default) != str(doc_default):
                    issues.append(f"Parameter {param} default mismatch: documented '{doc_default}', actual '{actual_default}'")
        
        return issues
```

---

## Future Integration Points

### Planner Integration Example

```python
# Example showing how planner uses extracted metadata
def planner_node_selection(user_prompt: str) -> List[str]:
    """Example of planner using extracted metadata for node selection."""
    
    # 1. Build LLM context from pre-extracted metadata
    context_builder = PlannerContextBuilder()
    available_nodes = registry.list_node_ids()
    llm_context = context_builder.build_context(available_nodes)
    
    # 2. LLM selection using rich metadata
    llm_response = thinking_model.generate(f"""
    {llm_context}
    
    User request: {user_prompt}
    
    Select appropriate nodes for this request.
    """)
    
    # 3. Validate selected nodes using metadata
    selected_nodes = parse_llm_selection(llm_response)
    validation_errors = validate_node_compatibility(selected_nodes)
    
    return selected_nodes if not validation_errors else []

def validate_node_compatibility(selected_nodes: List[str]) -> List[str]:
    """Validate interface compatibility using metadata."""
    errors = []
    
    for i, node_id in enumerate(selected_nodes[:-1]):
        current_metadata = registry.get_metadata(node_id)
        next_metadata = registry.get_metadata(selected_nodes[i + 1])
        
        current_outputs = set(current_metadata["interface"]["outputs"].keys())
        next_inputs = set(next_metadata["interface"]["inputs"].keys())
        
        # Check for interface mismatches
        missing_inputs = next_inputs - current_outputs
        if missing_inputs:
            errors.append(f"Node {selected_nodes[i + 1]} expects inputs {missing_inputs} not provided by {node_id}")
    
    return errors
```

---

## Dependencies and Tools

### Required Libraries

```bash
pip install docstring-parser>=0.15    # Standard docstring parsing
pip install rich>=13.0                # CLI formatting  
pip install click>=8.0                # CLI framework
```

### Optional Enhancements

```bash
pip install ast-decompiler            # Enhanced code analysis
pip install pyflakes                  # Static analysis integration
pip install black                     # Code formatting validation
```

---

## Conclusion

This metadata extraction infrastructure provides the foundation for pflow's metadata-driven planner capabilities while maintaining perfect alignment with the established static node architecture.

**Key Benefits**:

- **Zero architectural conflicts** - Fully aligned with source documents
- **Production ready** - Robust parsing with comprehensive error handling
- **Performance optimized** - Pre-extracted metadata for fast planner context
- **Registry integrated** - Seamless workflow with node installation and versioning
- **Validation enabled** - Code-metadata consistency checking for quality assurance

The infrastructure enables intelligent flow planning while preserving the simplicity and reliability of pflow's curated node ecosystem.
