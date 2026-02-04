# Minimal Workflow

The simplest possible pflow workflow: a single node that writes a file.
No edges, no inputs, no outputs — just one step. Perfect for testing
file node implementations or creating simple configuration files.

## Steps

### hello

Write a greeting message to a file on disk.

- type: write-file
- content: Hello, pflow!
- file_path: hello.txt
