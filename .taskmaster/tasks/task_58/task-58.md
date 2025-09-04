# Task 58: Update workflow generator prompt-tests to use better real world test cases

## ID
57

## Title
Update workflow generator prompt-tests to use better real world test cases

## Description
Evaluate and improve the test cases for the `workflow_generator` prompt.
This is the prompt at `src/pflow/planning/prompts/workflow_generator.md` but we are NOT updating the prompt, we are only updating the test cases making sure they cover RELEVANT and hard real world examples.

Base the new tests on north star examples from the `architecture/vision/north-star-examples.md` file.

## Requirements
- Focus only on `tests/test_planning/llm/prompts/test_workflow_generator_prompt.py::TestWorkflowGeneratorPrompt`
- should include hard north star examples.
- should include using mcps in test cases.
- the special test command `uv run python tools/test_prompt_accuracy.py workflow_generator` should still work correctly after we are done

## Status
pending