# Proxy Mappings

Demonstrates a pipeline using proxy mappings to rename shared store keys
between nodes with incompatible interfaces. The reader outputs `content`
but the processor expects `test_input` — mappings bridge the gap.

* Mappings are declared in the IR `mappings` field (not visible in markdown)
* Pattern: read → process (with key renaming) → write

## Steps

### reader

Read the input file from disk. Outputs content to the shared store
under the `content` key.

- type: read-file
- file_path: input.txt

### test_processor

Process the file content through a test node. Expects `test_input`
(mapped from `content`) and outputs `test_output` (mapped to
`processed_content`).

- type: test

### writer

Write the processed result to the output file. Receives
`processed_content` mapped to `content`.

- type: write-file
- file_path: output.txt
