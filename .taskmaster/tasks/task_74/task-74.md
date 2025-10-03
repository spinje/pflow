# Task 74: Create knowledge base system

I want to create some kind of system where the user is asked at the end of a completed workflow (after it has been saved to the workflow library/registry) if they want to store any important insights, knowledge, or information that they gained when creating the workflow.

This is especially important if there was a lot of trial and error, for example if the agent struggled to understand a certain api, command or parameter in a node (e.g. the agent failed multiple times to understand the how to use an mcp node).

I envision that the agent will save the information in a file in the `.pflow/knowledge-base/` directory and that it should have a frontmatter with the following information:
- related nodes
- related workflow name (the workflow that was being worked on to create the knowledge)

In the content of the file, the agent will include the following information:
description why it is important to know this
- what went wrong and how it was fixed
- anything else?

This information (related node) will be automatically included when the agent is using `pflow registry discover` or `pflow registry describe <node_name>`

And the related workflow name will be automatically included when the agent is using pflow `workflow describe <workflow_name>`

In the future these knowledge base files will be shared across a users team or organization when connected to pflow cloud.


