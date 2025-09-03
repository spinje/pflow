You are currently working on a task that requires deep understanding of the system and potentially external research and resources to be implemented correctly.

To help you gain full understanding of the task and the system, you will need to deploy @agent-pflow-codebase-researcher subagents IN PARALLEL to gather information from the codebase and external resources.

Before you deploy the subagents, you will need to do the following:

1. Think hard about what information you need to gather from the codebase You need to:
    - Resolve any amibiguity in the task specification and requirements
    - Resolve ALL assumptions you have about how the system works
    - Resolve all potential issues or pitfalls that may arise during implementation

2. Consider if you need to gather information from external resources like documentation or websites
    - Make sure to be clear in the subagent instructions that the subagent should only use the internet to gather the requrested information

3. Think hard and before deploying the subagents, write down a plan of what you will do with the information you gather.

4. Deploy the subagents in paralell. This means using ONE function call block to deploy all subagents simoultainously. Do not use sequential function calls to deploy subagents since this will be highly inefficient.

5. Once the subagents have finished gathering information, you will need to review the information and make sure it is accurate and complete. If any new information is needed, you will need to re-deploy the subagents to gather the missing information.

6. Once you are satisfied with the information clearly describe the information you have gathered in a file called `.taskmaster/tasks/task_<taskId>/starting-context/research-findings.md`. Make sure this file is structured in a way that is easy to understand and use and discusses indepth how the information you gathered is relevant to the task and how it will be used to implement the task.

Rules:
- Provide as detailed instructions as possible to the subagents on what to gather, be as specific as possible.
- All subagents must be deployed in paralell.
- Ultrathink in between each step.
- Only gather external information if it is absolutely necessary or instructions are given by the user to do so.
