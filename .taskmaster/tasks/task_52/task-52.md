Improve planner

1. The planner needs to make a "plan" before writing the json ir

2. The planner needs to define requirements before starting to write the json ir
This could include:
    - How many nodes are needed
    - Required node types that should be used
    - The order of the nodes? (might be to strict, im not sure about this)
    - How many sub workflows are needed (sub workflows are not yet supported but these could be defined as an entry to the json schema with a detailed "prompt" for the sub workflow with clear requirements)
    - Anything else?

This will be used in the validator to validate these "dynamic" validation criteria