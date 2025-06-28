# LLM Patterns Analysis for pflow

This document analyzes Simon Willison's LLM codebase to extract specific patterns that pflow could adapt beyond just LLM integration.

## 1. Plugin System Architecture

### Plugin Discovery and Loading

LLM uses `pluggy` for plugin management with a clean separation of concerns:

```python
# plugins.py
import pluggy
from . import hookspecs

pm = pluggy.PluginManager("llm")
pm.add_hookspecs(hookspecs)

def load_plugins():
    global _loaded
    if _loaded:
        return
    _loaded = True

    # Load from setuptools entry points
    if not hasattr(sys, "_called_from_test"):
        pm.load_setuptools_entrypoints("llm")

    # Load from environment variable
    if LLM_LOAD_PLUGINS:
        for package_name in LLM_LOAD_PLUGINS.split(","):
            distribution = metadata.distribution(package_name)
            # ...register plugin
```

### Hook Specification Pattern

Hooks are defined declaratively using decorators:

```python
# hookspecs.py
from pluggy import HookspecMarker

hookspec = HookspecMarker("llm")

@hookspec
def register_models(register):
    "Register additional model instances"

@hookspec
def register_commands(cli):
    """Register additional CLI commands"""

@hookspec
def register_tools(register):
    "Register functions that can be used as tools"
```

### Pattern for pflow

pflow could adapt this for node discovery:

```python
# pflow/hookspecs.py
@hookspec
def register_nodes(register):
    """Register additional node types"""

@hookspec
def register_node_packages(register):
    """Register node packages with metadata"""

# Usage in plugins
@hookimpl
def register_nodes(register):
    register(FileReadNode, name="read_file")
    register(LLMNode, name="llm")
```

## 2. CLI Command Structure

### Click with DefaultGroup

LLM uses `click-default-group` for intuitive CLI:

```python
from click_default_group import DefaultGroup

@click.group(
    cls=DefaultGroup,
    default="prompt",
    default_if_no_args=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.version_option()
def cli():
    """Access Large Language Models from the command-line"""
```

### Parameter Types and Validation

Custom parameter types for complex inputs:

```python
class AttachmentType(click.ParamType):
    name = "attachment"

    def convert(self, value, param, ctx):
        try:
            return resolve_attachment(value)
        except AttachmentError as e:
            self.fail(str(e), param, ctx)

# JSON validator factory
def json_validator(object_name):
    def validator(ctx, param, value):
        if value is None:
            return value
        try:
            obj = json.loads(value)
            if not isinstance(obj, dict):
                raise click.BadParameter(f"{object_name} must be a JSON object")
            return obj
        except json.JSONDecodeError:
            raise click.BadParameter(f"{object_name} must be valid JSON")
    return validator
```

### Fragment Resolution Pattern

Flexible input handling supporting multiple sources:

```python
def resolve_fragments(db, fragments, allow_attachments=False):
    """Resolve fragments from URLs, files, stdin, or plugin prefixes"""
    resolved = []
    for fragment in fragments:
        if fragment.startswith("http://") or fragment.startswith("https://"):
            # Fetch from URL
            response = httpx.get(fragment)
            resolved.append(Fragment(response.text, fragment))
        elif fragment == "-":
            # Read from stdin
            resolved.append(Fragment(sys.stdin.read(), "-"))
        elif has_plugin_prefix(fragment):
            # Load from plugin
            prefix, rest = fragment.split(":", 1)
            loader = loaders[prefix]
            result = loader(rest)
            resolved.extend(result)
        else:
            # Try database, then file
            content = _load_from_db(fragment)
            if content:
                resolved.append(Fragment(content, source))
            elif pathlib.Path(fragment).exists():
                resolved.append(Fragment(path.read_text(), str(path)))
```

### Pattern for pflow

pflow could use similar patterns for flow definitions:

```python
# pflow CLI pattern
@click.group(cls=DefaultGroup, default="run", default_if_no_args=True)
def pflow():
    """Workflow compiler and executor"""

# Flexible input resolution
def resolve_flow_definition(definition):
    if definition == "-":
        return sys.stdin.read()
    elif definition.startswith("http"):
        return fetch_from_url(definition)
    elif Path(definition).exists():
        return Path(definition).read_text()
    else:
        # Try as inline definition
        return definition
```

## 3. Testing Patterns

### CLI Testing with CliRunner

```python
from click.testing import CliRunner

def test_model_options_list_and_show(user_path):
    (user_path / "model_options.json").write_text(
        json.dumps({"gpt-4o-mini": {"temperature": 0.5}}),
        "utf-8",
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["models", "options", "list"])
    assert result.exit_code == 0
    assert "temperature: 0.5" in result.output
```

### VCR Pattern for API Testing

Using cassettes to record/replay API interactions:

```python
@pytest.mark.vcr
def test_tool_use_basic(vcr):
    model = llm.get_model("gpt-4o-mini")

    def multiply(a: int, b: int) -> int:
        """Multiply two numbers."""
        return a * b

    chain_response = model.chain("What is 1231 * 2331?", tools=[multiply])
    output = "".join(chain_response)
    assert output == "The result is 2,869,461."
```

### Pattern for pflow

```python
# Test flow execution
def test_flow_execution(tmp_path):
    flow_def = """
    read_file("input.txt") >> llm("summarize") >> write_file("output.txt")
    """
    runner = CliRunner()
    result = runner.invoke(pflow, ["run", "-"], input=flow_def)
    assert result.exit_code == 0

# Test with cassettes for external APIs
@pytest.mark.vcr
def test_llm_node_execution():
    node = LLMNode(model="gpt-4o-mini")
    shared = {"prompt": "Hello"}
    node.exec(shared)
    assert "response" in shared
```

## 4. Configuration Management

### User Directory Pattern

```python
def user_dir():
    llm_user_path = os.environ.get("LLM_USER_PATH")
    if llm_user_path:
        path = pathlib.Path(llm_user_path)
    else:
        path = pathlib.Path(click.get_app_dir("io.datasette.llm"))
    path.mkdir(exist_ok=True, parents=True)
    return path
```

### Key/Configuration Storage

```python
def load_keys():
    path = user_dir() / "keys.json"
    if path.exists():
        return json.loads(path.read_text())
    return {}

def get_key(explicit_key=None, key_alias=None, env_var=None):
    """Hierarchical key resolution"""
    stored_keys = load_keys()

    # Check explicit key
    if explicit_key in stored_keys:
        return stored_keys[explicit_key]
    if explicit_key:
        return explicit_key

    # Check alias
    if key_alias in stored_keys:
        return stored_keys[key_alias]

    # Check environment
    if env_var and os.environ.get(env_var):
        return os.environ[env_var]
```

### Alias System

```python
def set_alias(alias, model_id_or_alias):
    """Set an alias to point to a model"""
    path = user_dir() / "aliases.json"
    current = json.loads(path.read_text()) if path.exists() else {}

    # Resolve to actual model ID
    try:
        model = get_model(model_id_or_alias)
        model_id = model.model_id
    except UnknownModelError:
        model_id = model_id_or_alias

    current[alias] = model_id
    path.write_text(json.dumps(current, indent=4) + "\n")
```

### Pattern for pflow

```python
# pflow configuration
def pflow_dir():
    path = os.environ.get("PFLOW_HOME")
    if path:
        return Path(path)
    return Path(click.get_app_dir("io.pflow"))

# Node aliases
def set_node_alias(alias, node_id):
    aliases = load_aliases()
    aliases[alias] = resolve_node_id(node_id)
    save_aliases(aliases)
```

## 5. Model Abstraction

### Base Class Hierarchy

```python
class _BaseModel(ABC):
    model_id: str
    attachment_types: Set[str] = set()
    supports_schema = False
    supports_tools = False

    class Options(BaseModel):
        pass

    def _validate_attachments(self, attachments):
        if attachments and not self.attachment_types:
            raise ValueError("This model does not support attachments")

class Model(_Model):
    @abstractmethod
    def execute(self, prompt, stream, response, conversation):
        pass

class KeyModel(_Model):
    @abstractmethod
    def execute(self, prompt, stream, response, conversation, key):
        pass
```

### Provider Registration Pattern

```python
class ModelWithAliases:
    def __init__(self, model, async_model, aliases):
        self.model = model
        self.async_model = async_model
        self.aliases = aliases

def get_models_with_aliases():
    model_aliases = []

    def register(model, async_model=None, aliases=None):
        alias_list = list(aliases or [])
        # Add user-configured aliases
        if model.model_id in extra_model_aliases:
            alias_list.extend(extra_model_aliases[model.model_id])
        model_aliases.append(ModelWithAliases(model, async_model, alias_list))

    load_plugins()
    pm.hook.register_models(register=register)
    return model_aliases
```

### Pattern for pflow

```python
# Base node abstraction
class BaseNode(ABC):
    node_id: str
    supports_streaming = False
    required_keys: Set[str] = set()

    class Config(BaseModel):
        pass

    @abstractmethod
    def exec(self, shared: Dict[str, Any]) -> None:
        pass

# Node registry with aliases
class NodeWithAliases:
    def __init__(self, node_class, aliases):
        self.node_class = node_class
        self.aliases = aliases

def get_nodes_with_aliases():
    nodes = []

    def register(node_class, aliases=None):
        nodes.append(NodeWithAliases(node_class, aliases or []))

    pm.hook.register_nodes(register=register)
    return nodes
```

## 6. Error Handling Patterns

### Custom Exceptions

```python
class NeedsKeyException(Exception):
    """Raised when a model needs an API key"""
    def __init__(self, model, key_name):
        self.model = model
        self.key_name = key_name

class UnknownModelError(KeyError):
    pass
```

### Graceful Degradation

```python
def get_model(name=None):
    aliases = get_model_aliases()
    name = name or get_default_model()
    try:
        return aliases[name]
    except KeyError:
        # Check if async version exists
        async_model = None
        try:
            async_model = get_async_model(name)
        except UnknownModelError:
            pass
        if async_model:
            raise UnknownModelError(f"Unknown model (async model exists): {name}")
        else:
            raise UnknownModelError(f"Unknown model: {name}")
```

## 7. Tool/Function Integration

### Tool Definition Pattern

```python
@dataclass
class Tool:
    name: str
    description: Optional[str] = None
    input_schema: Dict = field(default_factory=dict)
    implementation: Optional[Callable] = None
    plugin: Optional[str] = None

    @classmethod
    def function(cls, function, name=None):
        """Convert Python function to Tool"""
        return cls(
            name=name or function.__name__,
            description=function.__doc__ or None,
            input_schema=_get_arguments_input_schema(function, name),
            implementation=function,
        )
```

### Pattern for pflow

This pattern could be adapted for dynamic node creation from functions:

```python
# Convert function to node
@Node.function
def uppercase_node(text: str) -> str:
    """Convert text to uppercase"""
    return text.upper()

# Would create a node that:
# - Reads 'text' from shared store
# - Applies function
# - Stores result back
```

## Key Takeaways for pflow

1. **Plugin System**: Use pluggy for extensibility with clear hook specifications
2. **CLI Design**: DefaultGroup pattern for intuitive default commands
3. **Input Resolution**: Support multiple input sources (stdin, files, URLs, plugins)
4. **Configuration**: Hierarchical config with environment variables, user files, and aliases
5. **Testing**: CliRunner for CLI tests, VCR for external API testing
6. **Error Handling**: Custom exceptions with helpful context
7. **Type Safety**: Use Pydantic models for configuration and validation
8. **Registration Pattern**: Flexible registration with aliases and metadata
