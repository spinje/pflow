# Source line tracking — source inside a code block

Test that source declarations inside code blocks also get line tracking.
The code fence name must be `source` so the parser's per-block handler
at `markdown_parser.py::_build_output_dict` recognises the content as an
output source expression and assigns `_source_line = block.start_line + 1`.
A `yaml` fence would fall through the `elif block.param_name:` branch and
store the content under an unknown `yaml` key, which the IR schema rejects.

## Steps

### primary

Fails.

- type: shell
- on-error: fallback
- next: end
- cache: false

```shell command
exit 1
```

### fallback

Succeeds.

- type: shell
- next: end
- cache: false

```shell command
echo "ok"
```

## Outputs

### content

Output defined via a `source` code block.

```source
${primary.stdout}
```
