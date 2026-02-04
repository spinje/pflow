# Simple Pipeline

A three-step file processing pipeline demonstrating sequential node
execution. Reads a file, creates a backup copy, then writes the output.

* Flow: reader → copier → writer
* Pattern: read → backup → write using file operations

## Steps

### reader

Read the input file from disk. The content flows to subsequent nodes
via the shared store.

- type: read-file
- file_path: input.txt

### copier

Create a backup copy of the input file before any processing.

- type: copy-file
- destination: backup.txt

### writer

Write the processed output to a new file.

- type: write-file
- file_path: output.txt
