"""Tests for the markdown workflow parser.

Test categories from implementation plan Phase 1.2:
1. Complete workflow parsing
2. Section handling
3. Entity parsing
4. YAML param parsing
5. Code block parsing
6. Param routing
7. Edge generation
8. Frontmatter
9. Prose joining
10. Validation errors
11. Non-dict YAML items
12. ast.parse() Python validation
13. yaml.safe_load() YAML config validation
14. IR equivalence
15. Edge cases
"""

import textwrap

import pytest

from pflow.core.markdown_parser import (
    MarkdownParseError,
    _coerce_yaml_scalar,
    _find_colon_offending_line,
    parse_markdown,
)
from tests.shared.markdown_utils import ir_to_markdown

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _md(text: str) -> str:
    """Dedent and strip a markdown string for readability."""
    return textwrap.dedent(text).strip() + "\n"


MINIMAL_WORKFLOW = _md("""\
    # Test

    A test workflow.

    ## Steps

    ### hello

    Says hello.

    - type: shell

    ```shell command
    echo hello
    ```
""")


# ===========================================================================
# 1. Complete workflow parsing
# ===========================================================================


class TestCompleteWorkflowParsing:
    """Full end-to-end parsing of a realistic workflow."""

    def test_complete_workflow_with_inputs_steps_outputs(self) -> None:
        content = _md("""\
            # Webpage Fetcher

            Fetches a webpage and saves it.

            ## Inputs

            ### target_url

            The URL to fetch.

            - type: string
            - required: true

            ### output_file

            Output file path.

            - type: string
            - default: "auto"

            ## Steps

            ### fetch

            Fetch the page via HTTP.

            - type: http
            - url: https://example.com/${target_url}

            ### save

            Save the fetched content to disk.

            - type: write-file
            - file_path: ${output_file}
            - content: ${fetch.response}

            ## Outputs

            ### file_path

            Path to the saved file.

            - source: ${output_file}
        """)
        result = parse_markdown(content)
        ir = result.ir

        assert result.title == "Webpage Fetcher"
        assert result.description == "Fetches a webpage and saves it."

        # Inputs
        assert "target_url" in ir["inputs"]
        assert ir["inputs"]["target_url"]["type"] == "string"
        assert ir["inputs"]["target_url"]["required"] is True
        assert ir["inputs"]["output_file"]["default"] == "auto"

        # Nodes
        assert len(ir["nodes"]) == 2
        assert ir["nodes"][0]["id"] == "fetch"
        assert ir["nodes"][0]["type"] == "http"
        assert ir["nodes"][0]["params"]["url"] == "https://example.com/${target_url}"
        assert ir["nodes"][1]["id"] == "save"
        assert ir["nodes"][1]["type"] == "write-file"

        # Edges from document order
        assert ir["edges"] == [{"from": "fetch", "to": "save"}]

        # Outputs
        assert ir["outputs"]["file_path"]["source"] == "${output_file}"

    def test_workflow_with_batch_and_prompt(self) -> None:
        content = _md("""\
            # Analyzer

            Analyzes items.

            ## Steps

            ### analyze

            Analyze each item with an LLM.

            - type: llm
            - model: gpt-4
            - images: ${item}

            ```yaml batch
            items: ${source.stdout}
            parallel: true
            max_concurrent: 40
            error_handling: continue
            ```

            ````markdown prompt
            Extract the information.

            * Diagram: mermaid code
            * Chart: data values

            ```python
            print("example")
            ```
            ````
        """)
        result = parse_markdown(content)
        node = result.ir["nodes"][0]

        assert node["type"] == "llm"
        assert node["params"]["model"] == "gpt-4"
        assert node["params"]["images"] == "${item}"
        assert node["batch"]["items"] == "${source.stdout}"
        assert node["batch"]["parallel"] is True
        assert node["batch"]["max_concurrent"] == 40
        assert "Extract the information." in node["params"]["prompt"]
        assert "```python" in node["params"]["prompt"]


# ===========================================================================
# 2. Section handling
# ===========================================================================


class TestSectionHandling:
    def test_case_insensitive_sections(self) -> None:
        content = _md("""\
            # Test

            A test.

            ## inputs

            ### url

            The URL.

            - type: string

            ## STEPS

            ### fetch

            Fetches data.

            - type: http

            ## Outputs

            ### result

            The result.

            - source: ${fetch.response}
        """)
        result = parse_markdown(content)
        assert "url" in result.ir["inputs"]
        assert len(result.ir["nodes"]) == 1
        assert "result" in result.ir["outputs"]

    def test_optional_inputs_and_outputs(self) -> None:
        result = parse_markdown(MINIMAL_WORKFLOW)
        ir = result.ir
        assert "inputs" not in ir or ir.get("inputs") == {}
        assert "outputs" not in ir or ir.get("outputs") == {}

    def test_unknown_sections_ignored(self) -> None:
        content = _md("""\
            # Test

            A test.

            ## Notes

            Some documentation notes here.

            ## Steps

            ### hello

            Says hello.

            - type: shell

            ```shell command
            echo hello
            ```

            ## Design Decisions

            We chose X because Y.
        """)
        result = parse_markdown(content)
        assert len(result.ir["nodes"]) == 1

    def test_near_miss_section_warning(self) -> None:
        content = _md("""\
            # Test

            A test.

            ## Input

            ### url

            The URL.

            - type: string

            ## Steps

            ### hello

            Says hello.

            - type: shell

            ```shell command
            echo hello
            ```
        """)
        result = parse_markdown(content)
        warnings = result.warnings
        assert any("Input" in w.message and "Inputs" in w.message for w in warnings)

    def test_missing_steps_section_error(self) -> None:
        content = _md("""\
            # Test

            A test.

            ## Inputs

            ### url

            The URL.

            - type: string
        """)
        with pytest.raises(MarkdownParseError, match="Missing '## Steps' section"):
            parse_markdown(content)


# ===========================================================================
# 3. Entity parsing
# ===========================================================================


class TestEntityParsing:
    def test_entity_id_from_heading(self) -> None:
        result = parse_markdown(MINIMAL_WORKFLOW)
        assert result.ir["nodes"][0]["id"] == "hello"

    def test_entity_id_with_hyphens_and_underscores(self) -> None:
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### my-node_v2

            Does something.

            - type: shell

            ```shell command
            echo test
            ```
        """)
        result = parse_markdown(content)
        assert result.ir["nodes"][0]["id"] == "my-node_v2"

    def test_invalid_entity_id_uppercase(self) -> None:
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### MyNode

            Does something.

            - type: shell
        """)
        with pytest.raises(MarkdownParseError, match="Invalid entity ID 'MyNode'"):
            parse_markdown(content)

    def test_invalid_entity_id_starts_with_number(self) -> None:
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### 1st-node

            Does something.

            - type: shell
        """)
        with pytest.raises(MarkdownParseError, match="Invalid entity ID"):
            parse_markdown(content)

    def test_invalid_entity_id_with_spaces(self) -> None:
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### my node

            Does something.

            - type: shell
        """)
        with pytest.raises(MarkdownParseError, match="Invalid entity ID"):
            parse_markdown(content)

    def test_duplicate_entity_ids_in_same_section(self) -> None:
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### fetch

            First fetch.

            - type: http

            ### fetch

            Second fetch.

            - type: http
        """)
        with pytest.raises(MarkdownParseError, match="Duplicate entity ID 'fetch'"):
            parse_markdown(content)

    def test_duplicate_steps_section_raises(self) -> None:
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### hello

            Says hello.

            - type: shell

            ## Steps

            ### goodbye

            Says goodbye.

            - type: shell
        """)
        with pytest.raises(MarkdownParseError, match="Duplicate '## Steps' section") as exc_info:
            parse_markdown(content)
        assert "Merge with the existing" in str(exc_info.value.suggestion)
        # Error line points to the duplicate (line 13), suggestion references the original (line 5)
        assert exc_info.value.line == 13
        assert "line 5" in str(exc_info.value.suggestion)

    def test_duplicate_inputs_section_raises(self) -> None:
        content = _md("""\
            # Test

            A test.

            ## Inputs

            ### message

            A message.

            - type: string

            ## Inputs

            ### name

            A name.

            - type: string

            ## Steps

            ### hello

            Says hello.

            - type: shell
        """)
        with pytest.raises(MarkdownParseError, match="Duplicate '## Inputs' section"):
            parse_markdown(content)

    def test_duplicate_outputs_section_raises(self) -> None:
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### hello

            Says hello.

            - type: shell

            ## Outputs

            ### result

            The result.

            - from: hello

            ## Outputs

            ### other

            Another output.

            - from: hello
        """)
        with pytest.raises(MarkdownParseError, match="Duplicate '## Outputs' section"):
            parse_markdown(content)

    def test_duplicate_section_case_insensitive(self) -> None:
        """## Steps and ## steps both resolve to STEPS — duplicate detected."""
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### hello

            Says hello.

            - type: shell

            ## steps

            ### goodbye

            Says goodbye.

            - type: shell
        """)
        with pytest.raises(MarkdownParseError, match="Duplicate '## Steps' section"):
            parse_markdown(content)

    def test_duplicate_unknown_sections_allowed(self) -> None:
        """Unknown sections (not Inputs/Steps/Outputs) can repeat without error."""
        content = _md("""\
            # Test

            A test.

            ## Notes

            Some notes.

            ## Steps

            ### hello

            Says hello.

            - type: shell

            ## Notes

            More notes.
        """)
        result = parse_markdown(content)
        assert len(result.ir["nodes"]) == 1


# ===========================================================================
# 4. YAML param parsing
# ===========================================================================


class TestYAMLParamParsing:
    def test_flat_params(self) -> None:
        result = parse_markdown(MINIMAL_WORKFLOW)
        node = result.ir["nodes"][0]
        assert node["type"] == "shell"

    def test_nested_yaml_params(self) -> None:
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### fetch

            Fetches data.

            - type: http
            - headers:
                Authorization: Bearer ${token}
                Content-Type: application/json
        """)
        result = parse_markdown(content)
        headers = result.ir["nodes"][0]["params"]["headers"]
        assert headers["Authorization"] == "Bearer ${token}"
        assert headers["Content-Type"] == "application/json"

    def test_non_contiguous_params(self) -> None:
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### fetch

            Fetches data.

            - type: http

            We use this particular URL for reasons.

            - url: https://example.com
            - timeout: 30
        """)
        result = parse_markdown(content)
        node = result.ir["nodes"][0]
        assert node["type"] == "http"
        assert node["params"]["url"] == "https://example.com"
        assert node["params"]["timeout"] == 30

    def test_inline_comments_become_part_of_value(self) -> None:
        """Inline # is NOT stripped as YAML comment — it becomes part of the raw value.

        This is intentional: stripping # causes silent corruption for URLs
        (fragments), hex colors, and prompts with markdown headings.
        Users should use markdown prose (* note) for annotations.
        """
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### fetch

            Fetches data.

            - type: http  # Best choice
            - timeout: 30  # Long timeout
        """)
        result = parse_markdown(content)
        node = result.ir["nodes"][0]
        # Inline comments are now part of the value (not stripped)
        assert node["type"] == "http  # Best choice"
        # timeout is no longer int because "30  # Long timeout" can't be coerced
        assert node["params"]["timeout"] == "30  # Long timeout"

    def test_yaml_boolean_coercion(self) -> None:
        content = _md("""\
            # Test

            A test.

            ## Inputs

            ### flag

            A boolean input.

            - type: boolean
            - required: true
            - default: false

            ## Steps

            ### hello

            Says hello.

            - type: shell

            ```shell command
            echo hello
            ```
        """)
        result = parse_markdown(content)
        inp = result.ir["inputs"]["flag"]
        assert inp["required"] is True
        assert inp["default"] is False

    def test_yaml_block_scalar_literal(self) -> None:
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### process

            Processes data.

            - type: shell
            - env_vars: |
                FOO=bar
                BAZ=qux
        """)
        result = parse_markdown(content)
        node = result.ir["nodes"][0]
        assert "FOO=bar" in node["params"]["env_vars"]
        assert "BAZ=qux" in node["params"]["env_vars"]

    def test_yaml_block_scalar_in_code_block(self) -> None:
        content = _md("""\
            # Test

            Block scalars in yaml code blocks.

            ## Steps

            ### notify

            Send a notification.

            - type: mcp-slack-SEND_MESSAGE
            - channel: general

            ```yaml data
            channel: general
            text: |
              Deployment complete for my-app

              Changes:
              - Fixed login bug
              - Added search

              Status: Success
            metadata:
              source: ci
            ```
        """)
        result = parse_markdown(content)
        node = result.ir["nodes"][0]
        data = node["params"]["data"]
        assert data["channel"] == "general"
        assert "Deployment complete" in data["text"]
        assert "Fixed login bug" in data["text"]
        assert "Status: Success" in data["text"]
        assert data["metadata"] == {"source": "ci"}

    def test_yaml_block_scalar_in_batch_code_block(self) -> None:
        content = _md("""\
            # Test

            Block scalars in batch items.

            ## Steps

            ### process

            Process items.

            - type: llm
            - prompt: ${item.prompt}

            ```yaml batch
            items:
              - prompt: |
                  Summarize this data in 2 sentences.
                  Focus on key findings.

                  Data: some-data
              - prompt: "Extract action items"
            parallel: true
            ```
        """)
        result = parse_markdown(content)
        node = result.ir["nodes"][0]
        batch = node["batch"]
        assert batch["parallel"] is True
        assert len(batch["items"]) == 2
        assert "Summarize this data" in batch["items"][0]["prompt"]
        assert "Focus on key findings" in batch["items"][0]["prompt"]
        assert batch["items"][1]["prompt"] == "Extract action items"


# ===========================================================================
# 5. Code block parsing
# ===========================================================================


class TestCodeBlockParsing:
    def test_shell_command_block(self) -> None:
        result = parse_markdown(MINIMAL_WORKFLOW)
        assert result.ir["nodes"][0]["params"]["command"] == "echo hello"

    def test_prompt_block(self) -> None:
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### ask

            Asks a question.

            - type: llm

            ```prompt
            What is the meaning of life?
            ```
        """)
        result = parse_markdown(content)
        assert result.ir["nodes"][0]["params"]["prompt"] == "What is the meaning of life?"

    def test_markdown_prompt_block(self) -> None:
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### ask

            Asks a question.

            - type: llm

            ```markdown prompt
            # Instructions

            Do the thing.
            ```
        """)
        result = parse_markdown(content)
        assert "# Instructions" in result.ir["nodes"][0]["params"]["prompt"]

    def test_python_code_block(self) -> None:
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### compute

            Computes something.

            - type: code

            ```python code
            def process(inputs):
                return {"result": inputs["x"] * 2}
            ```
        """)
        result = parse_markdown(content)
        assert "def process(inputs):" in result.ir["nodes"][0]["params"]["code"]

    def test_yaml_batch_block(self) -> None:
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### process

            Processes items.

            - type: llm

            ```yaml batch
            items: ${source.data}
            parallel: true
            max_concurrent: 10
            ```

            ```prompt
            Process this item.
            ```
        """)
        result = parse_markdown(content)
        node = result.ir["nodes"][0]
        assert node["batch"]["items"] == "${source.data}"
        assert node["batch"]["parallel"] is True

    def test_yaml_stdin_block(self) -> None:
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### process

            Processes data.

            - type: shell

            ```yaml stdin
            filter: ${source.stdout}
            commits: ${other.stdout}
            ```

            ```shell command
            jq '.'
            ```
        """)
        result = parse_markdown(content)
        node = result.ir["nodes"][0]
        assert node["params"]["stdin"]["filter"] == "${source.stdout}"
        assert node["params"]["stdin"]["commits"] == "${other.stdout}"

    def test_yaml_headers_block(self) -> None:
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### fetch

            Fetches data.

            - type: http
            - url: https://example.com

            ```yaml headers
            Authorization: Bearer ${token}
            Accept: application/json
            ```
        """)
        result = parse_markdown(content)
        node = result.ir["nodes"][0]
        assert node["params"]["headers"]["Authorization"] == "Bearer ${token}"

    def test_nested_code_fences(self) -> None:
        """Prompts containing code blocks use 4+ backticks."""
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### ask

            Asks a question.

            - type: llm

            ````markdown prompt
            Here is an example:

            ```python
            print("hello")
            ```

            Now do the thing.
            ````
        """)
        result = parse_markdown(content)
        prompt = result.ir["nodes"][0]["params"]["prompt"]
        assert "```python" in prompt
        assert 'print("hello")' in prompt

    def test_bare_code_block_error(self) -> None:
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### hello

            Says hello.

            - type: shell

            ```
            echo hello
            ```
        """)
        with pytest.raises(MarkdownParseError, match="Code block has no tag"):
            parse_markdown(content)

    def test_bare_code_block_nested_backticks_detected(self) -> None:
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### my-llm

            Uses an LLM.

            - type: llm

            ```prompt
            - Exact format:
            ```
            [project] [version] tagged.
            ```
            ```
        """)
        with pytest.raises(MarkdownParseError) as exc_info:
            parse_markdown(content)
        error_msg = str(exc_info.value)
        assert "Code block has no tag" in error_msg
        assert "nested" in error_msg.lower()
        assert "prompt" in error_msg

    def test_duplicate_code_block_error(self) -> None:
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### hello

            Says hello.

            - type: shell

            ```shell command
            echo hello
            ```

            ```shell command
            echo world
            ```
        """)
        with pytest.raises(MarkdownParseError, match="Duplicate code block"):
            parse_markdown(content)

    def test_output_source_code_block(self) -> None:
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### gen

            Generates content.

            - type: llm

            ```prompt
            Write a story.
            ```

            ## Outputs

            ### report

            The full report.

            ```markdown source
            # Report

            ## Content
            ${gen.response}

            ## Footer
            Generated automatically.
            ```
        """)
        result = parse_markdown(content)
        source = result.ir["outputs"]["report"]["source"]
        assert "# Report" in source
        assert "${gen.response}" in source

    def test_yaml_output_schema_block(self) -> None:
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### ask

            Asks Claude.

            - type: claude-code

            ```yaml output_schema
            type: object
            properties:
              answer:
                type: string
            ```

            ```prompt
            Answer the question.
            ```
        """)
        result = parse_markdown(content)
        schema = result.ir["nodes"][0]["params"]["output_schema"]
        assert schema["type"] == "object"
        assert "answer" in schema["properties"]


# ===========================================================================
# 6. Param routing
# ===========================================================================


class TestParamRouting:
    def test_input_params_flat_no_wrapper(self) -> None:
        content = _md("""\
            # Test

            A test.

            ## Inputs

            ### url

            The URL to fetch.

            - type: string
            - required: true
            - default: "https://example.com"

            ## Steps

            ### hello

            Says hello.

            - type: shell

            ```shell command
            echo hello
            ```
        """)
        result = parse_markdown(content)
        inp = result.ir["inputs"]["url"]
        # Flat — no "params" wrapper
        assert inp["type"] == "string"
        assert inp["required"] is True
        assert "params" not in inp

    def test_output_params_flat_no_wrapper(self) -> None:
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### gen

            Generates content.

            - type: shell

            ```shell command
            echo output
            ```

            ## Outputs

            ### result

            The result.

            - type: string
            - source: ${gen.stdout}
        """)
        result = parse_markdown(content)
        out = result.ir["outputs"]["result"]
        assert out["type"] == "string"
        assert out["source"] == "${gen.stdout}"
        assert "params" not in out

    def test_node_type_to_top_level(self) -> None:
        result = parse_markdown(MINIMAL_WORKFLOW)
        node = result.ir["nodes"][0]
        assert node["type"] == "shell"
        assert "type" not in node.get("params", {})

    def test_node_batch_to_top_level(self) -> None:
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### process

            Processes items.

            - type: llm

            ```yaml batch
            items: ${data.stdout}
            parallel: true
            ```

            ```prompt
            Process this.
            ```
        """)
        result = parse_markdown(content)
        node = result.ir["nodes"][0]
        assert "batch" in node
        assert node["batch"]["items"] == "${data.stdout}"
        # batch should NOT be in params
        assert "batch" not in node.get("params", {})

    def test_inline_batch_to_top_level(self) -> None:
        """Inline - batch: with nested YAML goes to top-level, not params."""
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### process

            Processes items in batch.

            - type: llm
            - batch:
                items: ${data.stdout}
                parallel: true
        """)
        result = parse_markdown(content)
        node = result.ir["nodes"][0]
        assert "batch" in node
        assert node["batch"]["items"] == "${data.stdout}"
        assert node["batch"]["parallel"] is True
        # batch should NOT be in params
        assert "batch" not in node.get("params", {})

    def test_inline_batch_simple_to_top_level(self) -> None:
        """Inline - batch: with simple items template goes to top-level."""
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### process

            Processes items.

            - type: shell
            - batch:
                items: ${fetch.stdout}

            ```shell command
            echo ${item}
            ```
        """)
        result = parse_markdown(content)
        node = result.ir["nodes"][0]
        assert "batch" in node
        assert node["batch"]["items"] == "${fetch.stdout}"
        assert "batch" not in node.get("params", {})

    def test_inline_and_code_block_batch_is_error(self) -> None:
        """Having both inline - batch: and yaml batch code block is a conflict."""
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### process

            Processes items.

            - type: llm
            - batch:
                items: ${data.stdout}

            ```yaml batch
            items: ${other.stdout}
            parallel: true
            ```
        """)
        with pytest.raises(MarkdownParseError, match="defined both inline and as a code block"):
            parse_markdown(content)

    def test_node_prose_to_purpose(self) -> None:
        result = parse_markdown(MINIMAL_WORKFLOW)
        node = result.ir["nodes"][0]
        assert node["purpose"] == "Says hello."

    def test_node_remaining_params_to_params_dict(self) -> None:
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### fetch

            Fetches a URL.

            - type: http
            - url: https://example.com
            - timeout: 30
        """)
        result = parse_markdown(content)
        node = result.ir["nodes"][0]
        assert node["params"]["url"] == "https://example.com"
        assert node["params"]["timeout"] == 30


# ===========================================================================
# 7. Edge generation
# ===========================================================================


class TestEdgeGeneration:
    def test_edges_from_document_order(self) -> None:
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### step-a

            First step.

            - type: shell

            ```shell command
            echo a
            ```

            ### step-b

            Second step.

            - type: shell

            ```shell command
            echo b
            ```

            ### step-c

            Third step.

            - type: shell

            ```shell command
            echo c
            ```
        """)
        result = parse_markdown(content)
        assert result.ir["edges"] == [
            {"from": "step-a", "to": "step-b"},
            {"from": "step-b", "to": "step-c"},
        ]

    def test_single_node_no_edges(self) -> None:
        result = parse_markdown(MINIMAL_WORKFLOW)
        assert result.ir["edges"] == []


# ===========================================================================
# 8. Frontmatter
# ===========================================================================


class TestFrontmatter:
    def test_frontmatter_parsing(self) -> None:
        content = _md("""\
            ---
            created_at: "2026-01-14T15:43:57"
            version: "1.0.0"
            execution_count: 5
            ---

            # Test

            A test.

            ## Steps

            ### hello

            Says hello.

            - type: shell

            ```shell command
            echo hello
            ```
        """)
        result = parse_markdown(content)
        assert result.metadata is not None
        assert result.metadata["version"] == "1.0.0"
        assert result.metadata["execution_count"] == 5
        assert result.title == "Test"

    def test_no_frontmatter(self) -> None:
        result = parse_markdown(MINIMAL_WORKFLOW)
        assert result.metadata is None

    def test_frontmatter_with_nested_data(self) -> None:
        content = _md("""\
            ---
            created_at: "2026-01-14"
            last_execution_params:
              version: "1.0.0"
              channel: releases
            search_keywords:
              - changelog
              - git
            ---

            # Test

            A test.

            ## Steps

            ### hello

            Says hello.

            - type: shell

            ```shell command
            echo hello
            ```
        """)
        result = parse_markdown(content)
        assert result.metadata is not None
        assert result.metadata["last_execution_params"]["version"] == "1.0.0"
        assert result.metadata["search_keywords"] == ["changelog", "git"]

    def test_invalid_frontmatter_yaml(self) -> None:
        content = _md("""\
            ---
            bad: [unclosed
            ---

            # Test

            A test.

            ## Steps

            ### hello

            Says hello.

            - type: shell

            ```shell command
            echo hello
            ```
        """)
        with pytest.raises(MarkdownParseError, match="Invalid YAML in frontmatter"):
            parse_markdown(content)


# ===========================================================================
# 9. Prose joining
# ===========================================================================


class TestProseJoining:
    def test_workflow_description_paragraphs(self) -> None:
        content = _md("""\
            # Test

            First paragraph about the workflow.
            Second line of first paragraph.

            ## Steps

            ### hello

            Says hello.

            - type: shell

            ```shell command
            echo hello
            ```
        """)
        result = parse_markdown(content)
        assert result.description is not None
        assert "First paragraph" in result.description
        assert "Second line" in result.description

    def test_node_prose_before_and_after_params(self) -> None:
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### analyze

            Classifies each commit.

            - type: llm
            - model: gpt-4

            We chose GPT-4 for accuracy.

            ```prompt
            Classify this.
            ```
        """)
        result = parse_markdown(content)
        purpose = result.ir["nodes"][0]["purpose"]
        assert "Classifies each commit." in purpose
        assert "We chose GPT-4 for accuracy." in purpose

    def test_prose_stripped(self) -> None:
        result = parse_markdown(MINIMAL_WORKFLOW)
        assert result.ir["nodes"][0]["purpose"] == "Says hello."


# ===========================================================================
# 10. Validation errors
# ===========================================================================


class TestValidationErrors:
    def test_missing_description(self) -> None:
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### hello

            - type: shell

            ```shell command
            echo hello
            ```
        """)
        with pytest.raises(MarkdownParseError, match="missing a description"):
            parse_markdown(content)

    def test_missing_type(self) -> None:
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### hello

            Says hello.

            - timeout: 30
        """)
        with pytest.raises(MarkdownParseError, match="missing a 'type' parameter"):
            parse_markdown(content)

    def test_unclosed_code_fence(self) -> None:
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### hello

            Says hello.

            - type: shell

            ```shell command
            echo hello
        """)
        with pytest.raises(MarkdownParseError, match="Unclosed code block"):
            parse_markdown(content)

    def test_empty_steps_section(self) -> None:
        content = _md("""\
            # Test

            A test.

            ## Steps
        """)
        with pytest.raises(MarkdownParseError, match="has no nodes"):
            parse_markdown(content)

    def test_inline_and_code_block_conflict(self) -> None:
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### process

            Processes data.

            - type: shell
            - stdin: ${fetch.response}

            ```yaml stdin
            data: ${other.value}
            ```

            ```shell command
            echo test
            ```
        """)
        with pytest.raises(MarkdownParseError, match="defined both inline and as a code block"):
            parse_markdown(content)


# ===========================================================================
# 11. Non-dict YAML items
# ===========================================================================


class TestNonDictYAMLItems:
    def test_bare_yaml_item_error(self) -> None:
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### hello

            Says hello.

            - type: shell
            - This is just a note

            ```shell command
            echo hello
            ```
        """)
        with pytest.raises(MarkdownParseError, match="not a valid parameter"):
            parse_markdown(content)


# ===========================================================================
# 12. ast.parse() Python validation
# ===========================================================================


class TestPythonCodeValidation:
    def test_valid_python_code(self) -> None:
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### compute

            Computes something.

            - type: code

            ```python code
            x = 1 + 2
            result = x * 3
            ```
        """)
        result = parse_markdown(content)
        assert "x = 1 + 2" in result.ir["nodes"][0]["params"]["code"]

    def test_invalid_python_syntax_error(self) -> None:
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### compute

            Computes something.

            - type: code

            ```python code
            def broken(
                return 42
            ```
        """)
        with pytest.raises(MarkdownParseError, match="Python syntax error"):
            parse_markdown(content)


# ===========================================================================
# 13. yaml.safe_load() YAML config validation
# ===========================================================================


class TestYAMLConfigValidation:
    def test_valid_yaml_batch_config(self) -> None:
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### process

            Processes items.

            - type: llm

            ```yaml batch
            items: ${data.list}
            parallel: true
            ```

            ```prompt
            Process this.
            ```
        """)
        result = parse_markdown(content)
        assert result.ir["nodes"][0]["batch"]["parallel"] is True

    def test_invalid_yaml_in_config_block(self) -> None:
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### process

            Processes items.

            - type: llm

            ```yaml batch
            items: [unclosed
            ```

            ```prompt
            Process.
            ```
        """)
        with pytest.raises(MarkdownParseError, match="YAML syntax error"):
            parse_markdown(content)


# ===========================================================================
# 14. IR equivalence (round-trip tests)
# ===========================================================================


class TestIREquivalence:
    """Test that ir_to_markdown → parse_markdown produces equivalent IR."""

    def test_minimal_ir_round_trip(self) -> None:
        original_ir = {
            "nodes": [
                {
                    "id": "hello",
                    "type": "write-file",
                    "params": {"content": "Hello!", "file_path": "out.txt"},
                }
            ],
            "edges": [],
        }
        markdown = ir_to_markdown(original_ir)
        result = parse_markdown(markdown)
        parsed_ir = result.ir

        assert len(parsed_ir["nodes"]) == 1
        node = parsed_ir["nodes"][0]
        assert node["id"] == "hello"
        assert node["type"] == "write-file"
        assert node["params"]["content"] == "Hello!"
        assert node["params"]["file_path"] == "out.txt"

    def test_pipeline_with_edges_round_trip(self) -> None:
        original_ir = {
            "nodes": [
                {"id": "step-a", "type": "shell", "params": {"command": "echo a"}},
                {"id": "step-b", "type": "shell", "params": {"command": "echo b"}},
                {"id": "step-c", "type": "shell", "params": {"command": "echo c"}},
            ],
            "edges": [
                {"from": "step-a", "to": "step-b"},
                {"from": "step-b", "to": "step-c"},
            ],
        }
        markdown = ir_to_markdown(original_ir)
        result = parse_markdown(markdown)
        parsed_ir = result.ir

        assert len(parsed_ir["nodes"]) == 3
        assert parsed_ir["edges"] == original_ir["edges"]

        for orig, parsed in zip(original_ir["nodes"], parsed_ir["nodes"]):
            assert parsed["id"] == orig["id"]
            assert parsed["type"] == orig["type"]

    def test_complex_workflow_round_trip(self) -> None:
        """Round-trip a workflow with inputs, batch, stdin, outputs."""
        original_ir = {
            "inputs": {
                "target_url": {
                    "type": "string",
                    "required": True,
                    "description": "URL to fetch",
                },
                "output_file": {
                    "type": "string",
                    "default": "auto",
                    "description": "Output path",
                },
            },
            "nodes": [
                {
                    "id": "fetch",
                    "type": "http",
                    "purpose": "Fetch the page",
                    "params": {"url": "https://example.com/${target_url}"},
                },
                {
                    "id": "process",
                    "type": "shell",
                    "purpose": "Process the data",
                    "params": {
                        "stdin": "${fetch.response}",
                        "command": "cat | wc -l",
                    },
                },
                {
                    "id": "analyze",
                    "type": "llm",
                    "purpose": "Analyze results",
                    "batch": {
                        "items": "${process.stdout}",
                        "parallel": True,
                        "max_concurrent": 10,
                    },
                    "params": {
                        "prompt": "Analyze this:\n\n${item}",
                        "model": "gpt-4",
                    },
                },
            ],
            "edges": [
                {"from": "fetch", "to": "process"},
                {"from": "process", "to": "analyze"},
            ],
            "outputs": {
                "result": {
                    "source": "${analyze.results}",
                    "description": "Analysis results",
                },
            },
        }
        markdown = ir_to_markdown(original_ir)
        result = parse_markdown(markdown)
        parsed_ir = result.ir

        # Inputs
        assert parsed_ir["inputs"]["target_url"]["type"] == "string"
        assert parsed_ir["inputs"]["target_url"]["required"] is True
        assert parsed_ir["inputs"]["output_file"]["default"] == "auto"

        # Nodes
        assert len(parsed_ir["nodes"]) == 3
        assert parsed_ir["nodes"][0]["type"] == "http"
        assert parsed_ir["nodes"][1]["params"]["command"] == "cat | wc -l"
        assert parsed_ir["nodes"][2]["batch"]["parallel"] is True
        assert parsed_ir["nodes"][2]["batch"]["max_concurrent"] == 10

        # Edges
        assert parsed_ir["edges"] == original_ir["edges"]

        # Outputs
        assert parsed_ir["outputs"]["result"]["source"] == "${analyze.results}"

    def test_complex_stdin_dict_round_trip(self) -> None:
        """Round-trip a node with complex stdin (dict)."""
        original_ir = {
            "nodes": [
                {
                    "id": "prepare",
                    "type": "shell",
                    "purpose": "Prepare context",
                    "params": {
                        "stdin": {
                            "filter": "${source.stdout}",
                            "commits": "${other.stdout}",
                        },
                        "command": "jq '.'",
                    },
                },
            ],
            "edges": [],
        }
        markdown = ir_to_markdown(original_ir)
        result = parse_markdown(markdown)
        parsed_ir = result.ir

        node = parsed_ir["nodes"][0]
        assert node["params"]["stdin"]["filter"] == "${source.stdout}"
        assert node["params"]["stdin"]["commits"] == "${other.stdout}"

    def test_inline_batch_items_round_trip(self) -> None:
        """Round-trip batch with inline array items."""
        original_ir = {
            "nodes": [
                {
                    "id": "format",
                    "type": "llm",
                    "purpose": "Format output",
                    "batch": {
                        "items": [
                            {"format": "markdown", "prompt": "Format as markdown"},
                            {"format": "html", "prompt": "Format as HTML"},
                        ],
                        "parallel": True,
                    },
                    "params": {"prompt": "${item.prompt}"},
                },
            ],
            "edges": [],
        }
        markdown = ir_to_markdown(original_ir)
        result = parse_markdown(markdown)
        parsed_ir = result.ir

        node = parsed_ir["nodes"][0]
        assert node["batch"]["parallel"] is True
        items = node["batch"]["items"]
        assert len(items) == 2
        assert items[0]["format"] == "markdown"
        assert items[1]["format"] == "html"


# ===========================================================================
# 15. Edge cases
# ===========================================================================


class TestEdgeCases:
    def test_single_node_workflow(self) -> None:
        result = parse_markdown(MINIMAL_WORKFLOW)
        assert len(result.ir["nodes"]) == 1
        assert result.ir["edges"] == []

    def test_no_h1_title(self) -> None:
        content = _md("""\
            ## Steps

            ### hello

            Says hello.

            - type: shell

            ```shell command
            echo hello
            ```
        """)
        result = parse_markdown(content)
        assert result.title is None
        assert len(result.ir["nodes"]) == 1

    def test_source_preserved(self) -> None:
        result = parse_markdown(MINIMAL_WORKFLOW)
        assert result.source == MINIMAL_WORKFLOW

    def test_tilde_fence(self) -> None:
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### hello

            Says hello.

            - type: shell

            ~~~shell command
            echo hello
            ~~~
        """)
        result = parse_markdown(content)
        assert result.ir["nodes"][0]["params"]["command"] == "echo hello"

    def test_node_without_params_except_type(self) -> None:
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### step

            A test node.

            - type: test
        """)
        result = parse_markdown(content)
        node = result.ir["nodes"][0]
        assert node["type"] == "test"
        # No extra params → params dict should be absent or empty
        assert node.get("params") is None or node.get("params") == {}

    def test_empty_inputs_section(self) -> None:
        content = _md("""\
            # Test

            A test.

            ## Inputs

            ## Steps

            ### hello

            Says hello.

            - type: shell

            ```shell command
            echo hello
            ```
        """)
        result = parse_markdown(content)
        # Empty Inputs section → no inputs in IR
        assert result.ir.get("inputs", {}) == {}

    def test_input_with_stdin_field(self) -> None:
        content = _md("""\
            # Test

            A test.

            ## Inputs

            ### data

            Piped input data.

            - type: string
            - stdin: true

            ## Steps

            ### hello

            Says hello.

            - type: shell

            ```shell command
            echo hello
            ```
        """)
        result = parse_markdown(content)
        assert result.ir["inputs"]["data"]["stdin"] is True

    def test_large_workflow_multiple_nodes(self) -> None:
        """Test with many nodes to verify edge generation scales."""
        nodes_md = ""
        for i in range(10):
            nodes_md += f"""
### step-{i}

Step {i} description.

- type: shell

```shell command
echo step {i}
```

"""
        content = f"# Test\n\nA test.\n\n## Steps\n\n{nodes_md}"
        result = parse_markdown(content)
        assert len(result.ir["nodes"]) == 10
        assert len(result.ir["edges"]) == 9
        # Verify edge chain
        for i in range(9):
            assert result.ir["edges"][i] == {
                "from": f"step-{i}",
                "to": f"step-{i + 1}",
            }

    def test_json_source_output_block(self) -> None:
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### gen

            Generates data.

            - type: shell

            ```shell command
            echo '{"key": "value"}'
            ```

            ## Outputs

            ### data

            JSON data output.

            ```json source
            {"result": "${gen.stdout}"}
            ```
        """)
        result = parse_markdown(content)
        assert '{"result": "${gen.stdout}"}' in result.ir["outputs"]["data"]["source"]

    def test_orphaned_yaml_content_in_inputs_error(self) -> None:
        """YAML-block syntax under ## Inputs with no ### headings raises error."""
        content = _md("""\
            # Test

            A test.

            ## Inputs

            message:
              type: string
              description: A message
              required: true

            ## Steps

            ### hello

            Says hello.

            - type: shell

            ```shell command
            echo hello
            ```
        """)
        with pytest.raises(MarkdownParseError, match="'Inputs' section has content but no inputs were parsed"):
            parse_markdown(content)

    def test_orphaned_yaml_content_in_outputs_error(self) -> None:
        """YAML-block syntax under ## Outputs with no ### headings raises error."""
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### hello

            Says hello.

            - type: shell

            ```shell command
            echo hello
            ```

            ## Outputs

            result:
              value: ${hello.output}
        """)
        with pytest.raises(MarkdownParseError, match="'Outputs' section has content but no outputs were parsed"):
            parse_markdown(content)

    def test_orphaned_content_in_steps_error(self) -> None:
        """Non-heading content under ## Steps with no ### headings raises error."""
        content = _md("""\
            # Test

            A test.

            ## Steps

            - name: fetch-data
              type: shell
              run: curl http://example.com
        """)
        with pytest.raises(MarkdownParseError, match="'Steps' section has content but no steps were parsed"):
            parse_markdown(content)

    def test_orphaned_prose_before_entity_warning(self) -> None:
        """Prose before the first ### entity in a known section produces a warning."""
        content = _md("""\
            # Test

            A test.

            ## Inputs

            These are the workflow parameters.

            ### message

            A message.

            - type: string

            ## Steps

            ### hello

            Says hello.

            - type: shell

            ```shell command
            echo hello
            ```
        """)
        result = parse_markdown(content)
        assert any("Unparsed content" in w.message and "Inputs" in w.message for w in result.warnings)
        # Workflow still parses correctly
        assert "message" in result.ir["inputs"]

    def test_orphaned_code_fence_in_known_section(self) -> None:
        """Code fence between ## and ### in known section is detected as orphaned."""
        content = _md("""\
            # Test

            A test.

            ## Inputs

            ```yaml
            message:
              type: string
            ```

            ### actual-input

            A real input.

            - type: string

            ## Steps

            ### hello

            Says hello.

            - type: shell

            ```shell command
            echo hello
            ```
        """)
        result = parse_markdown(content)
        assert any("Unparsed content" in w.message and "Inputs" in w.message for w in result.warnings)

    def test_no_orphan_detection_for_unknown_sections(self) -> None:
        """Content under unknown ## sections does not trigger orphan warnings."""
        content = _md("""\
            # Test

            A test.

            ## Notes

            This is a design note that should not trigger warnings.

            ## Steps

            ### hello

            Says hello.

            - type: shell

            ```shell command
            echo hello
            ```
        """)
        result = parse_markdown(content)
        orphan_warnings = [w for w in result.warnings if "Unparsed content" in w.message]
        assert orphan_warnings == []

    def test_orphaned_content_error_includes_syntax_hint(self) -> None:
        """Orphan error for inputs includes the correct syntax example."""
        content = _md("""\
            # Test

            A test.

            ## Inputs

            message:
              type: string

            ## Steps

            ### hello

            Says hello.

            - type: shell

            ```shell command
            echo hello
            ```
        """)
        with pytest.raises(MarkdownParseError) as exc_info:
            parse_markdown(content)
        err = exc_info.value
        assert err.suggestion is not None
        assert "### input-name" in err.suggestion
        assert "- type: string" in err.suggestion


# ===========================================================================
# 16. Source line tracking for runtime error references
# ===========================================================================


class TestSourceLineTracking:
    """Verify the parser records _source_lines for non-YAML code blocks.

    When a code block like ```python code is parsed, the parser stores
    the 1-based line number where the code content starts (the line
    after the opening fence) in node["_source_lines"]["code"]. The
    runtime uses this to map code errors back to the workflow file.

    Off-by-one errors are the exact bug these tests catch: the fence
    line vs the content start line vs 0-based vs 1-based indexing.
    """

    def test_code_block_source_line_points_to_content_start(self):
        """_source_lines["code"] equals fence_line + 1 (content starts after fence).

        The markdown below has the opening fence ```python code on line 15.
        Content starts on line 16, so _source_lines["code"] should be 16.
        """
        # Line numbers annotated:
        # 1:  # Test Workflow
        # 2:  (blank)
        # 3:  A test workflow.
        # 4:  (blank)
        # 5:  ## Steps
        # 6:  (blank)
        # 7:  ### my-node
        # 8:  (blank)
        # 9:  Does something.
        # 10: (blank)
        # 11: - type: code
        # 12: - inputs:
        # 13:     x: ${x}
        # 14: (blank)
        # 15: ```python code
        # 16: x: int
        # 17: result: int = x + 1
        # 18: ```
        workflow_md = (
            "# Test Workflow\n"
            "\n"
            "A test workflow.\n"
            "\n"
            "## Steps\n"
            "\n"
            "### my-node\n"
            "\n"
            "Does something.\n"
            "\n"
            "- type: code\n"
            "- inputs:\n"
            "    x: ${x}\n"
            "\n"
            "```python code\n"
            "x: int\n"
            "result: int = x + 1\n"
            "```\n"
        )
        result = parse_markdown(workflow_md)
        node = result.ir["nodes"][0]

        assert "_source_lines" in node, "Parser should store _source_lines for code blocks"
        assert "code" in node["_source_lines"], "_source_lines should have 'code' entry"
        # Fence on line 15, content starts on line 16
        assert node["_source_lines"]["code"] == 16


# ===========================================================================
# 17. Conditional branching
# ===========================================================================


class TestConditionalBranching:
    """Tests for conditional branching edge generation via next, on-error, and AST detection."""

    def test_next_overrides_document_order(self) -> None:
        """When a node has '- next: step-c', the edge skips step-b."""
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### step-a

            First step.

            - type: shell
            - next: step-c

            ```shell command
            echo a
            ```

            ### step-b

            Second step.

            - type: shell

            ```shell command
            echo b
            ```

            ### step-c

            Third step.

            - type: shell

            ```shell command
            echo c
            ```
        """)
        result = parse_markdown(content)
        edges = result.ir["edges"]

        # step-a should go to step-c with action "default", NOT to step-b
        a_edges = [e for e in edges if e["from"] == "step-a"]
        assert len(a_edges) == 1
        assert a_edges[0]["to"] == "step-c"
        assert a_edges[0]["action"] == "default"

        # step-b should still have a document-order edge to step-c (no action field)
        b_edges = [e for e in edges if e["from"] == "step-b"]
        assert len(b_edges) == 1
        assert b_edges[0] == {"from": "step-b", "to": "step-c"}

    def test_next_end_produces_no_outgoing_edge(self) -> None:
        """When a node has '- next: end', it produces no outgoing edge."""
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### step-a

            First step.

            - type: shell

            ```shell command
            echo a
            ```

            ### step-b

            Second step.

            - type: shell
            - next: end

            ```shell command
            echo b
            ```

            ### step-c

            Third step.

            - type: shell

            ```shell command
            echo c
            ```
        """)
        result = parse_markdown(content)
        edges = result.ir["edges"]

        # No edge should have from == "step-b"
        b_edges = [e for e in edges if e["from"] == "step-b"]
        assert b_edges == []

    def test_next_single_target_has_default_action(self) -> None:
        """A single '- next: step-b' produces an edge with action 'default'."""
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### step-a

            First step.

            - type: shell
            - next: step-b

            ```shell command
            echo a
            ```

            ### step-b

            Second step.

            - type: shell

            ```shell command
            echo b
            ```
        """)
        result = parse_markdown(content)
        edges = result.ir["edges"]

        a_edges = [e for e in edges if e["from"] == "step-a"]
        assert len(a_edges) == 1
        assert a_edges[0] == {"from": "step-a", "to": "step-b", "action": "default"}

    def test_next_multiple_targets_comma_separated(self) -> None:
        """Comma-separated '- next: path-a, path-b' produces named edges plus default."""
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### classify

            Classifies input.

            - type: shell
            - next: path-a, path-b

            ```shell command
            echo classify
            ```

            ### path-a

            Fast path.

            - type: shell
            - next: end

            ```shell command
            echo a
            ```

            ### path-b

            Slow path.

            - type: shell
            - next: end

            ```shell command
            echo b
            ```
        """)
        result = parse_markdown(content)
        edges = result.ir["edges"]

        classify_edges = [e for e in edges if e["from"] == "classify"]
        # Should have: action=path-a, action=path-b, action=default (to first target)
        assert len(classify_edges) == 3
        assert {"from": "classify", "to": "path-a", "action": "path-a"} in classify_edges
        assert {"from": "classify", "to": "path-b", "action": "path-b"} in classify_edges
        assert {"from": "classify", "to": "path-a", "action": "default"} in classify_edges

    def test_on_error_produces_error_action_edge(self) -> None:
        """'- on-error: handler' produces an edge with action 'error'."""
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### step-a

            First step.

            - type: shell
            - on-error: handler

            ```shell command
            echo a
            ```

            ### step-b

            Second step.

            - type: shell
            - next: end

            ```shell command
            echo b
            ```

            ### handler

            Error handler.

            - type: shell
            - next: end

            ```shell command
            echo error
            ```
        """)
        result = parse_markdown(content)
        edges = result.ir["edges"]

        a_edges = [e for e in edges if e["from"] == "step-a"]
        # Should have document-order edge to step-b AND error edge to handler
        assert len(a_edges) == 2
        assert {"from": "step-a", "to": "step-b"} in a_edges
        assert {"from": "step-a", "to": "handler", "action": "error"} in a_edges

    def test_on_error_combined_with_next(self) -> None:
        """Both '- next: step-b' and '- on-error: handler' produce two edges."""
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### step-a

            First step.

            - type: shell
            - next: step-b
            - on-error: handler

            ```shell command
            echo a
            ```

            ### step-b

            Second step.

            - type: shell
            - next: end

            ```shell command
            echo b
            ```

            ### handler

            Error handler.

            - type: shell
            - next: end

            ```shell command
            echo error
            ```
        """)
        result = parse_markdown(content)
        edges = result.ir["edges"]

        a_edges = [e for e in edges if e["from"] == "step-a"]
        assert len(a_edges) == 2
        assert {"from": "step-a", "to": "step-b", "action": "default"} in a_edges
        assert {"from": "step-a", "to": "handler", "action": "error"} in a_edges

    def test_ast_detects_next_literal(self) -> None:
        """Python code with 'next: str = "target"' produces an extra edge."""
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### classify

            Classify the input.

            - type: code

            ```python code
            data: str
            if data == "high":
                next: str = "fast-path"
            result: int = 0
            ```

            ### fast-path

            Fast processing.

            - type: shell
            - next: end

            ```shell command
            echo fast
            ```
        """)
        result = parse_markdown(content)
        edges = result.ir["edges"]

        classify_edges = [e for e in edges if e["from"] == "classify"]
        # Document-order edge to fast-path (no action) + AST edge with action "fast-path"
        assert {"from": "classify", "to": "fast-path", "action": "fast-path"} in classify_edges

    def test_ast_detects_multiple_next_literals(self) -> None:
        """Code with if/else setting next to different values produces edges for both."""
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### classify

            Classify the input.

            - type: code

            ```python code
            data: str
            if data == "high":
                next: str = "fast-path"
            else:
                next: str = "slow-path"
            result: int = 0
            ```

            ### fast-path

            Fast processing.

            - type: shell
            - next: end

            ```shell command
            echo fast
            ```

            ### slow-path

            Slow processing.

            - type: shell
            - next: end

            ```shell command
            echo slow
            ```
        """)
        result = parse_markdown(content)
        edges = result.ir["edges"]

        classify_edges = [e for e in edges if e["from"] == "classify"]
        actions = {e.get("action") for e in classify_edges}
        assert "fast-path" in actions
        assert "slow-path" in actions

    def test_ast_ignores_non_literal_next(self) -> None:
        """Dynamic 'next = some_variable' produces no extra edge (but requires - next:)."""
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### classify

            Classify the input.

            - type: code
            - next: output

            ```python code
            data: str
            target = "fast" if data == "high" else "slow"
            next = target
            result: int = 0
            ```

            ### output

            Output step.

            - type: shell

            ```shell command
            echo done
            ```
        """)
        result = parse_markdown(content)
        edges = result.ir["edges"]

        # Only the declared - next: edge from classify to output (action=default)
        classify_edges = [e for e in edges if e["from"] == "classify"]
        assert len(classify_edges) == 1
        assert classify_edges[0] == {"from": "classify", "to": "output", "action": "default"}

    def test_invalid_target_raises_with_suggestion(self) -> None:
        """'- next: nonexistent' raises MarkdownParseError with a suggestion."""
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### step-a

            First step.

            - type: shell
            - next: nonexistent

            ```shell command
            echo a
            ```

            ### step-b

            Second step.

            - type: shell

            ```shell command
            echo b
            ```
        """)
        with pytest.raises(MarkdownParseError, match=r"(Did you mean|Available nodes)"):
            parse_markdown(content)

    def test_on_error_invalid_target_raises(self) -> None:
        """'- on-error: nonexistent' raises MarkdownParseError."""
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### step-a

            First step.

            - type: shell
            - on-error: nonexistent

            ```shell command
            echo a
            ```

            ### step-b

            Second step.

            - type: shell

            ```shell command
            echo b
            ```
        """)
        with pytest.raises(MarkdownParseError, match=r"unknown target 'nonexistent'"):
            parse_markdown(content)

    def test_next_end_not_validated_as_node(self) -> None:
        """'- next: end' should NOT raise an invalid target error."""
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### step-a

            First step.

            - type: shell
            - next: end

            ```shell command
            echo a
            ```

            ### step-b

            Second step.

            - type: shell

            ```shell command
            echo b
            ```
        """)
        # Should not raise — "end" is a special keyword, not a node reference
        result = parse_markdown(content)
        edges = result.ir["edges"]
        a_edges = [e for e in edges if e["from"] == "step-a"]
        assert a_edges == []

    def test_next_and_on_error_not_in_params(self) -> None:
        """Routing keys 'next' and 'on-error' should not appear in node params."""
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### step-a

            First step.

            - type: shell
            - next: step-b
            - on-error: handler

            ```shell command
            echo a
            ```

            ### step-b

            Second step.

            - type: shell
            - next: end

            ```shell command
            echo b
            ```

            ### handler

            Error handler.

            - type: shell
            - next: end

            ```shell command
            echo error
            ```
        """)
        result = parse_markdown(content)
        for node in result.ir["nodes"]:
            params = node.get("params", {})
            assert "next" not in params, f"'next' should not be in params for {node['id']}"
            assert "on-error" not in params, f"'on-error' should not be in params for {node['id']}"

    def test_document_order_unchanged_without_routing(self) -> None:
        """Without any routing syntax, edges are plain document-order with NO action field."""
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### a

            First step.

            - type: shell

            ```shell command
            echo a
            ```

            ### b

            Second step.

            - type: shell

            ```shell command
            echo b
            ```

            ### c

            Third step.

            - type: shell

            ```shell command
            echo c
            ```
        """)
        result = parse_markdown(content)
        edges = result.ir["edges"]

        assert edges == [
            {"from": "a", "to": "b"},
            {"from": "b", "to": "c"},
        ]
        # Verify NO action field is present on any edge
        for edge in edges:
            assert "action" not in edge

    def test_ast_detection_plus_document_order_default(self) -> None:
        """Code node with 'next = "target"' still gets document-order default edge."""
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### classify

            Classify the input.

            - type: code

            ```python code
            data: str
            if data == "high":
                next: str = "fast-path"
            result: int = 0
            ```

            ### slow-path

            Default next step.

            - type: shell
            - next: end

            ```shell command
            echo slow
            ```

            ### fast-path

            Fast processing.

            - type: shell
            - next: end

            ```shell command
            echo fast
            ```
        """)
        result = parse_markdown(content)
        edges = result.ir["edges"]

        classify_edges = [e for e in edges if e["from"] == "classify"]
        # Document-order edge to slow-path (no action) since no explicit "- next:"
        assert {"from": "classify", "to": "slow-path"} in classify_edges
        # AST-detected edge to fast-path with action
        assert {"from": "classify", "to": "fast-path", "action": "fast-path"} in classify_edges

    # --- Validation 1: Dynamic next without - next: declaration ---

    def test_dynamic_next_without_declaration_raises(self) -> None:
        """Code with dynamic 'next = variable' and no '- next:' raises error."""
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### router

            Route dynamically.

            - type: code

            ```python code
            data: str
            target = "a" if data == "x" else "b"
            next = target
            result: int = 0
            ```

            ### step-b

            Next step.

            - type: shell

            ```shell command
            echo b
            ```
        """)
        with pytest.raises(MarkdownParseError, match=r"dynamic routing.*no.*'- next:'"):
            parse_markdown(content)

    def test_dynamic_next_with_declaration_passes(self) -> None:
        """Code with dynamic 'next = variable' and '- next:' declaration passes."""
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### router

            Route dynamically.

            - type: code
            - next: path-a, path-b

            ```python code
            data: str
            target = "a" if data == "x" else "b"
            next = target
            result: int = 0
            ```

            ### path-a

            Path A.

            - type: shell
            - next: end

            ```shell command
            echo a
            ```

            ### path-b

            Path B.

            - type: shell
            - next: end

            ```shell command
            echo b
            ```
        """)
        # Should not raise
        result = parse_markdown(content)
        assert result.ir is not None

    def test_annotated_dynamic_next_without_declaration_raises(self) -> None:
        """Code with 'next: str = variable' (annotated dynamic) and no '- next:' raises."""
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### router

            Route dynamically.

            - type: code

            ```python code
            data: str
            next: str = data.split("-")[0]
            result: int = 0
            ```

            ### step-b

            Next step.

            - type: shell

            ```shell command
            echo b
            ```
        """)
        with pytest.raises(MarkdownParseError, match=r"dynamic routing.*no.*'- next:'"):
            parse_markdown(content)

    def test_literal_next_no_declaration_needed(self) -> None:
        """Code with only literal 'next: str = \"target\"' needs no '- next:' declaration."""
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### router

            Route to target.

            - type: code

            ```python code
            next: str = "target"
            result: int = 0
            ```

            ### fallback

            Default fallback.

            - type: shell
            - next: end

            ```shell command
            echo fallback
            ```

            ### target

            Target node.

            - type: shell
            - next: end

            ```shell command
            echo target
            ```
        """)
        # Should not raise — AST creates the edge for the literal
        result = parse_markdown(content)
        assert result.ir is not None

    def test_annotation_without_assignment_not_flagged(self) -> None:
        """Bare 'next: str' annotation (no assignment) does not trigger dynamic detection."""
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### step-a

            A step with a bare next annotation.

            - type: code

            ```python code
            next: str
            result: int = 0
            ```

            ### step-b

            Next step.

            - type: shell

            ```shell command
            echo b
            ```
        """)
        # Should not raise — bare annotation has no routing intent
        result = parse_markdown(content)
        assert result.ir is not None

    # --- Validation 2: Branch target without explicit - next: ---

    def test_branch_target_without_next_raises(self) -> None:
        """Branch target of a named routing action without '- next:' raises error."""
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### router

            Route to branch.

            - type: code

            ```python code
            next: str = "branch"
            result: int = 0
            ```

            ### fallback

            Default next.

            - type: shell
            - next: end

            ```shell command
            echo fallback
            ```

            ### branch

            Branch target without - next:.

            - type: shell

            ```shell command
            echo branch
            ```
        """)
        with pytest.raises(MarkdownParseError, match=r"'branch'.*routing target.*no.*'- next:'"):
            parse_markdown(content)

    def test_error_target_without_next_raises(self) -> None:
        """Error handler target without '- next:' raises error."""
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### step-a

            Risky step.

            - type: shell
            - on-error: handler
            - next: end

            ```shell command
            echo a
            ```

            ### handler

            Error handler without - next:.

            - type: shell

            ```shell command
            echo error
            ```
        """)
        with pytest.raises(MarkdownParseError, match=r"'handler'.*routing target.*no.*'- next:'"):
            parse_markdown(content)

    def test_branch_target_with_next_end_passes(self) -> None:
        """Branch target with '- next: end' passes validation."""
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### router

            Route to branch.

            - type: code

            ```python code
            next: str = "branch"
            result: int = 0
            ```

            ### fallback

            Default next.

            - type: shell
            - next: end

            ```shell command
            echo fallback
            ```

            ### branch

            Branch target with explicit termination.

            - type: shell
            - next: end

            ```shell command
            echo branch
            ```
        """)
        result = parse_markdown(content)
        assert result.ir is not None

    def test_branch_target_with_next_node_passes(self) -> None:
        """Branch target with '- next: convergence-node' passes validation."""
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### router

            Route to branch.

            - type: code

            ```python code
            next: str = "branch"
            result: int = 0
            ```

            ### fallback

            Default next.

            - type: shell
            - next: done

            ```shell command
            echo fallback
            ```

            ### branch

            Branch target routing to convergence.

            - type: shell
            - next: done

            ```shell command
            echo branch
            ```

            ### done

            Convergence point.

            - type: shell

            ```shell command
            echo done
            ```
        """)
        result = parse_markdown(content)
        assert result.ir is not None

    def test_single_target_redirect_not_flagged(self) -> None:
        """Target of '- next: node-id' (single, action=default) is NOT a branch target."""
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### step-a

            Redirect to step-c.

            - type: shell
            - next: step-c

            ```shell command
            echo a
            ```

            ### step-b

            Skipped step.

            - type: shell

            ```shell command
            echo b
            ```

            ### step-c

            Target of redirect (no - next: needed).

            - type: shell

            ```shell command
            echo c
            ```
        """)
        # Should not raise — step-c is target of action="default", not a branch target
        result = parse_markdown(content)
        assert result.ir is not None

    def test_last_node_branch_target_still_requires_next(self) -> None:
        """Branch target as last node still requires '- next:' for consistency."""
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### router

            Route to handler on error.

            - type: shell
            - on-error: handler
            - next: end

            ```shell command
            echo route
            ```

            ### handler

            Error handler as last node, no - next:.

            - type: shell

            ```shell command
            echo error
            ```
        """)
        with pytest.raises(MarkdownParseError, match=r"'handler'.*routing target.*no.*'- next:'"):
            parse_markdown(content)

    def test_missing_next_fix_snippet_includes_doc_successor(self) -> None:
        """Regression guard for #308: when a document-order successor exists,
        the Fix snippet must offer ``- next: <doc_successor>`` as the likely
        continuation — not only ``- next: end``.

        Before the fix, prose named the successor but the code snippet only
        showed ``- next: end``. Users who copy-pasted the snippet silently
        converted a fall-through bug into a terminate bug (dropping the
        successor from every run of that branch).
        """
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### router

            Route to branch.

            - type: code

            ```python code
            next: str = "branch"
            result: int = 0
            ```

            ### fallback

            Default next.

            - type: shell
            - next: end

            ```shell command
            echo fallback
            ```

            ### branch

            Branch target missing - next:, with doc-order successor.

            - type: shell

            ```shell command
            echo branch
            ```

            ### continuation

            Document-order successor of branch.

            - type: shell
            - next: end

            ```shell command
            echo continuation
            ```
        """)
        with pytest.raises(MarkdownParseError) as excinfo:
            parse_markdown(content)

        msg = str(excinfo.value)
        assert "- next: continuation" in msg, (
            "Fix snippet must include the document-order successor as the likely "
            f"continuation (regression guard for #308). Got:\n{msg}"
        )
        assert "- next: end" in msg, "Fix snippet must still include '- next: end' as the safe fallback."

    def test_missing_next_annotates_on_error_router(self) -> None:
        """When the router reaches the target via '- on-error:', the error
        message annotates the router as '(on-error)'.

        The on-error mechanism is the only routing distinction that's reliably
        recoverable from edge data. Surfacing it in the message helps agents
        understand *why* this node is a routing target without re-reading the
        router.
        """
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### step-a

            Risky step.

            - type: shell
            - on-error: handler
            - next: end

            ```shell command
            echo a
            ```

            ### handler

            Error handler without - next:.

            - type: shell

            ```shell command
            echo error
            ```
        """)
        with pytest.raises(MarkdownParseError) as excinfo:
            parse_markdown(content)
        msg = str(excinfo.value)
        assert "(on-error)" in msg, (
            f"Router reaching target via '- on-error:' should be annotated '(on-error)' in the error. Got:\n{msg}"
        )

    # --- Validation 3: Non-router node falling into branch target ---

    def test_non_router_falling_into_branch_target_raises(self) -> None:
        """Main flow node with doc-order edge into a branch target raises error."""
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### router

            Route to handler on error.

            - type: shell
            - on-error: handler

            ```shell command
            echo route
            ```

            ### main-flow

            Continues main flow, falls through to handler.

            - type: shell

            ```shell command
            echo main
            ```

            ### handler

            Error handler.

            - type: shell
            - next: end

            ```shell command
            echo error
            ```
        """)
        with pytest.raises(MarkdownParseError, match=r"'main-flow'.*flows into.*'handler'"):
            parse_markdown(content)

    def test_router_doc_order_to_own_branch_target_ok(self) -> None:
        """Router's document-order edge to its own branch target is NOT an error."""
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### router

            Route to handler on error; default goes to handler too.

            - type: shell
            - on-error: handler

            ```shell command
            echo route
            ```

            ### handler

            Error handler (also doc-order successor of router).

            - type: shell
            - next: end

            ```shell command
            echo error
            ```
        """)
        # Should not raise — router IS the source of the error edge to handler
        result = parse_markdown(content)
        assert result.ir is not None

    def test_fallthrough_fix_includes_convergence_when_inferred(self) -> None:
        """When multiple branch targets explicitly route to the same
        non-branch-target node, that node is the likely convergence point.
        The fall-through-into-branch-target error should offer it as the
        likely-continuation fix alongside '- next: end'.

        Analogous to the #308 fix for the sibling validator: when pflow can
        infer the probable intent, the fix snippet should name it rather than
        suggesting only the safe terminator.
        """
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### step-a

            First router with error handler.

            - type: shell
            - on-error: handler-a
            - next: main-flow

            ```shell command
            echo a
            ```

            ### main-flow

            Main flow node that falls through into handler-a.

            - type: shell

            ```shell command
            echo main
            ```

            ### handler-a

            First branch target, converges on 'merge'.

            - type: shell
            - next: merge

            ```shell command
            echo ha
            ```

            ### step-b

            Second router with error handler.

            - type: shell
            - on-error: handler-b
            - next: merge

            ```shell command
            echo b
            ```

            ### handler-b

            Second branch target, also converges on 'merge'.

            - type: shell
            - next: merge

            ```shell command
            echo hb
            ```

            ### merge

            Convergence point (not a branch target).

            - type: shell
            - next: end

            ```shell command
            echo merge
            ```
        """)
        with pytest.raises(MarkdownParseError) as excinfo:
            parse_markdown(content)
        msg = str(excinfo.value)

        assert "flows into" in msg, f"Expected the fall-through-into-branch-target error. Got:\n{msg}"
        assert "- next: merge" in msg, (
            f"Fix snippet must include the inferred convergence 'merge' as the "
            f"likely continuation (regression guard: sibling-validator version "
            f"of #308's trap). Got:\n{msg}"
        )
        assert "- next: end" in msg, "Fix snippet must still include '- next: end' as the safe fallback."

    def test_fallthrough_fix_omits_convergence_when_not_inferable(self) -> None:
        """When convergence evidence is weak (fewer than 2 branch targets
        route to the same non-branch-target node), the fall-through error's
        fix snippet must show ONLY '- next: end' — never fabricate a
        plausible-looking candidate.

        Guards the conservatism contract of ``_infer_convergence_candidate``
        (docstring: 'false positives would mislead the user worse than the
        current behavior'). A bug lowering the voter threshold to >=1 or
        dropping the 'exclude branch targets' filter would pass the positive
        convergence test but fail this one.
        """
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### router

            Single router with one handler — not enough voters for
            convergence inference.

            - type: shell
            - on-error: handler
            - next: end

            ```shell command
            echo route
            ```

            ### main-flow

            Main flow node that falls through into handler.

            - type: shell

            ```shell command
            echo main
            ```

            ### handler

            The only branch target.

            - type: shell
            - next: tail

            ```shell command
            echo h
            ```

            ### tail

            Non-branch-target; only 1 voter (handler), below threshold.

            - type: shell
            - next: end

            ```shell command
            echo tail
            ```
        """)
        with pytest.raises(MarkdownParseError) as excinfo:
            parse_markdown(content)
        msg = str(excinfo.value)

        assert "flows into" in msg, f"Expected the fall-through error. Got:\n{msg}"
        # Extract only the code-snippet `- next:` lines and assert the sole
        # suggestion is `end` — no fabricated candidate like `- next: tail`
        # or `- next: handler` should leak into the fix block.
        fix_snippets = [line.strip() for line in msg.split("\n") if line.strip().startswith("- next:")]
        assert fix_snippets == ["- next: end"], (
            f"When no convergence is inferable, fix snippet must be exactly "
            f"'- next: end' with no fabricated candidate. Got: {fix_snippets}\n"
            f"Full message:\n{msg}"
        )
        # Convergence language should not appear when no convergence is inferred.
        assert "convergence point" not in msg, (
            f"Convergence language must only appear when an actual convergence node was inferred. Got:\n{msg}"
        )

    def test_next_multi_target_with_end(self) -> None:
        """'- next: step-3, end' creates edges for step-3 only, not for 'end'."""
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### router

            Route to step-3 or end.

            - type: code
            - next: step-3, end

            ```python code
            if True:
                next: str = "step-3"
            else:
                next: str = "end"
            result: str = "routed"
            ```

            ### step-3

            Final step.

            - type: echo
            - message: reached
            - next: end
        """)
        result = parse_markdown(content)
        edges = result.ir["edges"]

        router_edges = [e for e in edges if e["from"] == "router"]
        targets = {e["to"] for e in router_edges}
        assert "step-3" in targets
        assert "end" not in targets
        # Single real target → should get action "default"
        assert {"from": "router", "to": "step-3", "action": "default"} in router_edges

    def test_node_named_end_rejected(self) -> None:
        """A node with ID 'end' is rejected as reserved keyword."""
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### start

            First step.

            - type: echo
            - message: hello

            ### end

            This should not be allowed.

            - type: echo
            - message: bye
        """)
        with pytest.raises(MarkdownParseError, match="reserved keyword"):
            parse_markdown(content)


# ===========================================================================
# 18. YAML colon-in-value error enhancement
# ===========================================================================


class TestYAMLColonErrorEnhancement:
    """Tests for actionable error messages when a param value contains unquoted ': '."""

    def test_unquoted_colon_in_single_line_value_preserved(self) -> None:
        """Single-line values with colon-space are preserved as raw strings."""
        content = _md("""\
            # Test

            A test workflow.

            ## Steps

            ### ask

            Asks a question.

            - type: llm
            - system: You are helpful: always be concise

            ```prompt
            Hello
            ```
        """)
        result = parse_markdown(content)
        node = result.ir["nodes"][0]
        assert node["params"]["system"] == "You are helpful: always be concise"

    def test_quoted_value_with_colon_parses_successfully(self) -> None:
        """A value with ': ' that is already quoted should parse without error."""
        content = _md("""\
            # Test

            A test workflow.

            ## Steps

            ### ask

            Asks a question.

            - type: llm
            - prompt: "Write a sentence: about dogs"

            ```shell command
            echo placeholder
            ```
        """)
        result = parse_markdown(content)
        node = result.ir["nodes"][0]
        assert node["params"]["prompt"] == "Write a sentence: about dogs"

    def test_other_yaml_errors_get_generic_message(self) -> None:
        """Non-colon YAML errors should still show 'YAML syntax error', not the enhanced message."""
        content = _md("""\
            # Test

            A test workflow.

            ## Steps

            ### fetch

            Fetches data.

            - type: http
            - headers:
                invalid: [unclosed bracket

            ```shell command
            echo placeholder
            ```
        """)
        with pytest.raises(MarkdownParseError, match="YAML syntax error") as exc_info:
            parse_markdown(content)

        # The generic path should NOT have the colon-specific suggestion
        err = exc_info.value
        assert err.suggestion is None


class TestFindColonOffendingLine:
    """Unit tests for _find_colon_offending_line helper."""

    def test_returns_key_value_for_unquoted_colon(self) -> None:
        result = _find_colon_offending_line(["- prompt: text: more"])
        assert result == ("prompt", "text: more")

    def test_returns_none_for_simple_value(self) -> None:
        result = _find_colon_offending_line(["- type: shell"])
        assert result is None

    def test_returns_none_for_already_quoted_value(self) -> None:
        result = _find_colon_offending_line(['- prompt: "text: quoted"'])
        assert result is None

    def test_returns_none_for_empty_list(self) -> None:
        result = _find_colon_offending_line([])
        assert result is None


class TestRawStringParsing:
    """Tests for single-line raw string parsing (no YAML structural parsing)."""

    def test_colon_space_in_value_preserved(self) -> None:
        """Colon-space in single-line values doesn't break parsing."""
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### run

            Runs a command.

            - type: shell
            - system: You are a helpful assistant: be concise

            ```shell command
            echo placeholder
            ```
        """)
        result = parse_markdown(content)
        node = result.ir["nodes"][0]
        assert node["params"]["system"] == "You are a helpful assistant: be concise"

    def test_url_fragment_preserved(self) -> None:
        """URL fragments (#...) are not stripped as YAML comments."""
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### fetch

            Fetches data.

            - type: http
            - url: https://example.com/search#results
        """)
        result = parse_markdown(content)
        node = result.ir["nodes"][0]
        assert node["params"]["url"] == "https://example.com/search#results"

    def test_hash_in_value_preserved(self) -> None:
        """Hash character anywhere in value is preserved."""
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### run

            Runs a command.

            - type: shell
            - color: #ff0000

            ```shell command
            echo color
            ```
        """)
        result = parse_markdown(content)
        node = result.ir["nodes"][0]
        assert node["params"]["color"] == "#ff0000"

    def test_scalar_coercion_int(self) -> None:
        """Integer values are coerced from raw strings."""
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### fetch

            Fetches data.

            - type: http
            - timeout: 30
        """)
        result = parse_markdown(content)
        node = result.ir["nodes"][0]
        assert node["params"]["timeout"] == 30
        assert isinstance(node["params"]["timeout"], int)

    def test_scalar_coercion_float(self) -> None:
        """Float values are coerced from raw strings."""
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### ask

            Asks something.

            - type: llm
            - temperature: 0.7

            ```prompt
            Hello
            ```
        """)
        result = parse_markdown(content)
        node = result.ir["nodes"][0]
        assert node["params"]["temperature"] == 0.7
        assert isinstance(node["params"]["temperature"], float)

    def test_scalar_coercion_bool(self) -> None:
        """Boolean values are coerced from raw strings."""
        content = _md("""\
            # Test

            A test.

            ## Inputs

            ### flag

            A boolean flag.

            - type: boolean
            - required: true
            - default: false

            ## Steps

            ### run

            Runs something.

            - type: shell

            ```shell command
            echo hello
            ```
        """)
        result = parse_markdown(content)
        inp = result.ir["inputs"]["flag"]
        assert inp["required"] is True
        assert inp["default"] is False

    def test_scalar_coercion_null(self) -> None:
        """Null/empty values are coerced to None."""
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### ask

            Asks something.

            - type: llm
            - model: null

            ```prompt
            Hello
            ```
        """)
        result = parse_markdown(content)
        node = result.ir["nodes"][0]
        assert node["params"]["model"] is None

    def test_double_quoted_string_preserved(self) -> None:
        """Double-quoted values have quotes stripped and escapes processed."""
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### ask

            Asks something.

            - type: llm
            - system: "Write about: dogs"

            ```prompt
            Hello
            ```
        """)
        result = parse_markdown(content)
        node = result.ir["nodes"][0]
        assert node["params"]["system"] == "Write about: dogs"

    def test_quoted_bool_string_not_coerced(self) -> None:
        """Quoted 'true'/'false' stays as string, not coerced to bool."""
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### ask

            Asks something.

            - type: llm
            - label: "true"

            ```prompt
            Hello
            ```
        """)
        result = parse_markdown(content)
        node = result.ir["nodes"][0]
        assert node["params"]["label"] == "true"
        assert isinstance(node["params"]["label"], str)

    def test_multiline_items_still_yaml_parsed(self) -> None:
        """Multi-line items with continuations use YAML parsing for structure."""
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### run

            Runs code.

            - type: code
            - inputs:
                text: ${fetch.stdout}
                count: 10

            ```python code
            print(inputs["text"])
            ```
        """)
        result = parse_markdown(content)
        node = result.ir["nodes"][0]
        assert node["params"]["inputs"] == {"text": "${fetch.stdout}", "count": 10}

    def test_flow_style_dict_parsed(self) -> None:
        """Flow-style YAML dicts on single lines are parsed as dicts."""
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### run

            Runs code.

            - type: code
            - inputs: {text: "${fetch.stdout}", count: 10}

            ```python code
            print(inputs["text"])
            ```
        """)
        result = parse_markdown(content)
        node = result.ir["nodes"][0]
        assert isinstance(node["params"]["inputs"], dict)
        assert node["params"]["inputs"]["text"] == "${fetch.stdout}"
        assert node["params"]["inputs"]["count"] == 10

    def test_flow_style_list_parsed(self) -> None:
        """Flow-style YAML lists on single lines are parsed as lists."""
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### run

            Runs a command.

            - type: shell
            - sections: [features, fixes, breaking]

            ```shell command
            echo hello
            ```
        """)
        result = parse_markdown(content)
        node = result.ir["nodes"][0]
        assert node["params"]["sections"] == ["features", "fixes", "breaking"]

    def test_multiline_yaml_syntax_error(self) -> None:
        """Multi-line items with invalid YAML still produce errors."""
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### fetch

            Fetches data.

            - type: http
            - headers:
                invalid: [unclosed bracket
        """)
        with pytest.raises(MarkdownParseError, match="YAML"):
            parse_markdown(content)

    def test_malformed_flow_style_produces_parse_error(self) -> None:
        """Malformed flow-style YAML on a single line produces a parse error."""
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### fetch

            Fetches data.

            - type: http
            - headers: {Authorization: Bearer token
        """)
        with pytest.raises(MarkdownParseError, match="YAML"):
            parse_markdown(content)

    def test_unterminated_quote_produces_parse_error(self) -> None:
        """Unterminated quoted value produces a parse error, not a silent string."""
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### ask

            Asks something.

            - type: llm
            - system: "unterminated

            ```prompt
            Hello
            ```
        """)
        with pytest.raises(MarkdownParseError, match="Unterminated"):
            parse_markdown(content)

    def test_bare_key_no_value_is_none(self) -> None:
        """A bare ``- key:`` with no value produces None."""
        content = _md("""\
            # Test

            A test.

            ## Steps

            ### ask

            Asks something.

            - type: llm
            - model:

            ```prompt
            Hello
            ```
        """)
        result = parse_markdown(content)
        node = result.ir["nodes"][0]
        assert node["params"]["model"] is None


class TestCoerceYamlScalar:
    """Unit tests for _coerce_yaml_scalar helper."""

    def test_empty_returns_none(self) -> None:
        assert _coerce_yaml_scalar("") is None

    def test_null_values(self) -> None:
        for val in ("null", "Null", "NULL", "~"):
            assert _coerce_yaml_scalar(val) is None, f"Failed for {val!r}"

    def test_bool_true_variants(self) -> None:
        for val in ("true", "True", "TRUE", "yes", "Yes", "YES", "on", "On", "ON"):
            assert _coerce_yaml_scalar(val) is True, f"Failed for {val!r}"

    def test_bool_false_variants(self) -> None:
        for val in ("false", "False", "FALSE", "no", "No", "NO", "off", "Off", "OFF"):
            assert _coerce_yaml_scalar(val) is False, f"Failed for {val!r}"

    def test_integers(self) -> None:
        assert _coerce_yaml_scalar("0") == 0
        assert _coerce_yaml_scalar("30") == 30
        assert _coerce_yaml_scalar("-5") == -5
        assert _coerce_yaml_scalar("+42") == 42
        assert isinstance(_coerce_yaml_scalar("30"), int)

    def test_floats(self) -> None:
        assert _coerce_yaml_scalar("3.14") == 3.14
        assert _coerce_yaml_scalar("0.7") == 0.7
        assert _coerce_yaml_scalar("-1.5") == -1.5
        # 1.5e10: PyYAML keeps as string (YAML 1.1 requires explicit sign "1.5e+10"),
        # but pflow intentionally coerces to float (more useful for workflow authors)
        assert _coerce_yaml_scalar("1.5e10") == 1.5e10
        assert _coerce_yaml_scalar(".5") == 0.5
        assert isinstance(_coerce_yaml_scalar("3.14"), float)

    def test_scientific_notation_without_dot_stays_string(self) -> None:
        """'1e5' has no dot — stays string (matches PyYAML behavior)."""
        assert _coerce_yaml_scalar("1e5") == "1e5"
        assert isinstance(_coerce_yaml_scalar("1e5"), str)

    def test_inf_nan_stay_string(self) -> None:
        """'inf', 'nan', 'infinity' stay as strings (matches PyYAML behavior)."""
        for val in ("inf", "nan", "Inf", "NaN", "infinity", "Infinity", "-inf"):
            assert isinstance(_coerce_yaml_scalar(val), str), f"{val!r} should be string"

    def test_raw_strings(self) -> None:
        assert _coerce_yaml_scalar("hello") == "hello"
        assert _coerce_yaml_scalar("echo hello world") == "echo hello world"
        assert _coerce_yaml_scalar("https://example.com#frag") == "https://example.com#frag"
        assert _coerce_yaml_scalar("value: with colon") == "value: with colon"

    def test_double_quoted_strips_quotes(self) -> None:
        assert _coerce_yaml_scalar('"hello"') == "hello"
        assert _coerce_yaml_scalar('"value: with colon"') == "value: with colon"

    def test_double_quoted_escapes(self) -> None:
        assert _coerce_yaml_scalar(r'"line1\nline2"') == "line1\nline2"
        assert _coerce_yaml_scalar(r'"tab\there"') == "tab\there"
        assert _coerce_yaml_scalar(r'"back\\slash"') == "back\\slash"
        assert _coerce_yaml_scalar(r'"say \"hi\""') == 'say "hi"'

    def test_single_quoted_strips_quotes(self) -> None:
        assert _coerce_yaml_scalar("'hello'") == "hello"
        assert _coerce_yaml_scalar("'value: with colon'") == "value: with colon"

    def test_single_quoted_double_apostrophe(self) -> None:
        assert _coerce_yaml_scalar("'it''s'") == "it's"

    def test_quoted_bool_stays_string(self) -> None:
        assert _coerce_yaml_scalar('"true"') == "true"
        assert isinstance(_coerce_yaml_scalar('"true"'), str)

    def test_quoted_null_stays_string(self) -> None:
        assert _coerce_yaml_scalar('"null"') == "null"
        assert isinstance(_coerce_yaml_scalar('"null"'), str)

    def test_quoted_number_stays_string(self) -> None:
        assert _coerce_yaml_scalar('"30"') == "30"
        assert isinstance(_coerce_yaml_scalar('"30"'), str)

    def test_flow_style_dict(self) -> None:
        result = _coerce_yaml_scalar("{a: 1, b: 2}")
        assert result == {"a": 1, "b": 2}

    def test_flow_style_list(self) -> None:
        result = _coerce_yaml_scalar("[x, y, z]")
        assert result == ["x", "y", "z"]

    def test_unterminated_double_quote_raises(self) -> None:
        """Unterminated double-quoted string raises ValueError."""
        with pytest.raises(ValueError, match="Unterminated double-quoted"):
            _coerce_yaml_scalar('"unterminated')

    def test_unterminated_single_quote_raises(self) -> None:
        """Unterminated single-quoted string raises ValueError."""
        with pytest.raises(ValueError, match="Unterminated single-quoted"):
            _coerce_yaml_scalar("'unterminated")

    def test_lone_quote_raises(self) -> None:
        """A single quote character raises ValueError."""
        with pytest.raises(ValueError, match="Unterminated"):
            _coerce_yaml_scalar('"')

    def test_malformed_flow_style_raises_yaml_error(self) -> None:
        """Malformed flow-style YAML raises an error instead of silently returning a string."""
        import yaml

        with pytest.raises(yaml.YAMLError):
            _coerce_yaml_scalar("{invalid: [unclosed")
