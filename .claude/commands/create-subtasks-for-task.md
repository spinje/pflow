# Create Subtasks Guidelines

This file contains guidelines for creating subtasks for a given task. It utilizes the `task-master` CLI to manage the tasks and subtasks that you can run directly from the command line.

## Variables

- `<taskId>` = $ARGUMENTS

Can be used to reference the task in the `task-master` CLI and used in this document to reference the task.

## Overview

Steps 1-7 are used to make sure that the task is well defined and updated if needed.
Steps 8-11 are used to create the subtasks and verify that they are well defined and updated if needed.

> Each step in the workflow should be completed before moving on to the next step. When all 11 steps are completed, the process is complete and the subtasks have been successfully created.

## Workflow

1. Run `task-master show --id=<taskId>` to make sure the task exists and that it has no subtasks. If it already has subtasks abort the process and notify the user.

2. Carefully read the tasks Implementation Details and Test Strategy and make sure you understand the task. If anything is unclear, read the documentation in the `docs` or `pocketflow/docs` directory that is relevant to the task.

3. If applicable look for any existing examples of pocketflow examples in the `pocketflow/examples` directory if pocketflow can be used to solve the task.

4. If applicable search internet for any relevant information that can help you better understand a particular part of the task, especially if any particular framework (other than pocketflow) is used.

5. Carefully evaluate if there are different ways to solve the task. These approaches should be grouded in a **deep understanding of both the task and the project**. If there are multiple valid approaches and the implications of the different approaches requires the users input to choose the best one, create a new markdown file in the folder `scratchpads/critical-user-decisions/` and write down the details about the decision and the reasoning why it matters. Remember to **stop** and pause the process to let the user review the decision and approve it before moving on to the next step if needed.

6. After the best and most viable soltution has been selected that best fits the pflow project. Evaluate if the current implementation details and test strategy for the task are sufficient. If not, expand on them by using the `task-master update-task --id=<taskId> --prompt="<prompt>"`. The <prompt>  should be a detailed instruction of how the implementation details and test strategy should be changed or expanded. Include as much detail and context as possible here on what needs to be changed and what is missing and why it is important.

7. Verify that the new implementation details and test strategy has been updated correctly by running `task-master show --id=<taskId>`.

8. Now that we are sure that the task is perfectly aligned with the project we move on to creating the base subtasks. We do this by adding another entry into the `.taskmaster/reports/task-complexity-report.json` file by following the format of the previous entries. Make sure that all the required fields are filled out (`taskId`, `taskTitle`, `complexityScore`, `recommendedSubtasks`, `expansionPrompt`, `reasoning`) and are carefully selected to be as accurate as possible for the current task and that the expansion prompt is *EXTREMELY detailed and specific*, outlining every nuance of the subtasks that needs to be created. This is the most important part of the process and should be done with the utmost care and attention to detail and *ultra thinking*. Consider creating a new markdown file in the `scratchpads/` directory to help you think through what the subtasks and the expansion prompt should be.

Json format to add:

```json
{
    "taskId": <number>,
    "taskTitle": "<string>",
    "complexityScore": <number 1-10>,
    "recommendedSubtasks": <number>,
    "expansionPrompt": "<string>",
    "reasoning": "<string>"
}
```

9. Run `task-master expand --id=<taskId> --num=<recommendedSubtasks>` to create the subtasks.

10. Verify that the subtasks have been created correctly by running `task-master show --id=<taskId>.<subtaskId>` for each of the expected subtasks. So if there was 3 recommendedSubtasks, you should run `task-master show --id=<taskId>.1`, `task-master show --id=<taskId>.2`, and `task-master show --id=<taskId>.3`. Note that you can utilize parallel tool calls to run these commands in parallel to speed up the process.

11. Evaluate that each subtask is well defined and that the implementation details are sufficient. If not, expand on them by using the `task-master update-subtask --id=<taskId>.<subtaskId> --prompt="<prompt>"`. The <prompt>  should be a detailed instruction of how the implementation details should be changed or expanded. Include as much detail and context as possible here on what needs to be changed and what is missing and why it is important.

## Instructions and Rules

- To make sure that no step in the workflow is skipped, always create a todo list with all the steps that need to be completed in a markdown file in the `scratchpads/` directory. Add a checkbox for each step and check it off as you complete it. This ensures that no step is skipped and that the workflow is followed correctly.
- Make sure you read the available documentation carefully and think hard about how to best solve the task and the subtasks.
- Make sure you are *ultra thinking* and *deeply understand* the task, subtasks and the project and the relevant components of the project.
- Make sure that you follow *every step in the workflow* and that you do not skip any steps.
- Make sure that you are *extremely detailed* and *specific* in your instructions and that you do not skip any details. The instructions should be so detailed that an AI coding agent or junior developer could follow them easily.
- Make sure that you reference the available documentation and existing code in the project when writing the instructions. Do not include code in the instructions, only reference the code and the documentation.
- Make sure *every important decision* is documented in a markdown file in the `scratchpads/critical-user-decisions/` directory and approved by the user before moving on to the next step.
- If you encounter any ambiguities or uncertainties in the documentation or in the task, ask the user for clarification before moving on to the next step.
- Always **STOP** when the user needs to review something or approve something, do not move on to the next step until the user has approved the current step.

## Notes

- Never assume that the task or even the documentation is accurate and complete, always ask the user for clarification if you are unsure about anything or if something does not make sense.
- Do not just read the documentation referenced in the task (this is a common mistake), make your own thorough search of the codebase and the documentation to understand the task and the subtasks.
- Use subagents to gather information and context efficiently.
- Document all your thinking and reasoning in the `scratchpads/` directory and explore multiple options before making a decision.

## Special Instructions from the user

Always do these first before you begin (if empty, ignore this section):

$ARGUMENTS
