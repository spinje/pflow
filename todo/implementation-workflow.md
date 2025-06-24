# Implementation Workflow

## Overview

The implementation workflow is a systematic approach to building the pflow project. It is designed to be efficient and effective, and to ensure that the project is built to the highest standards.

## Variables

- `<taskId>`: The id of the task you are implementing
- `<subtaskId>`: The id of the subtask you are implementing

Can be used to reference the task or subtask in the `task-master` CLI and used in this document to reference the task or subtask.

## Phases

1. Refining the task
2. Refining and implementing the subtasks
    - Refining the subtask
    - Planning the subtaskimplementation
    - Implement subtask 🔄
    - Iterative refinement of the subtask 🔄
    - Finish implementing the subtask
    - Next subtask

---

1. **Planning**
2. **Sub task breakdown**
3. **Implementation**

## Prerequisites & Context

**Required:**
- You have been given a task to implement, typically an id referencing a task-master task. This id is a reference to a task in the `.taskmaster/tasks.json` file. But you will typically not interact with the `tasks.json` file directly. Instead, you will use the `task-master` CLI to manage the tasks and subtasks.
- You have understood how to use the `task-master` CLI to manage, read, and update the tasks and subtasks relevant to the task you are implementing.
- You have a deep understanding of the pflow project documentation (`docs/`) and the current state of the codebase (`src/pflow`).
- You have read all the relevant documentation relevant to the task you are implementing.

**Optional:**
- If relevant, you have a deep understanding of the PocketFlow framework documentation (`pocketflow/docs/`) and pocketflow source code (`pocketflow/__init__.py`).
- If applicable, you have checked the PocketFlow cookbook (`pocketflow/cookbook/`) for any relevant examaples, inspiration and code snippets that could be used to implement the task.

## Workflow for implementing a task

### 1. Evaluating the task

1. **Identify ambiguous or unclear parts of the task**
    - Ask the user for clarification on any ambiguous or unclear parts of the task.
    - Always present clear options and recommendations for different approaches and present it in a section in the `.taskmaster/tasks/<taskId>/evaluation.md` file.
    - The more ambiguous or unclear the task is, the more options you should present.
    - Always ultra think on the problem space and potential solutions and do not present any options that you know are not valid or feasible.

2. **Identify conflicting information found in the pflow or pocketflow documentation**
    - Ask the user for clarification on any conflicting information found in the pflow or pocketflow documentation.
    - Always present clear options and recommendations for different approaches and present it in a section in the `.taskmaster/tasks/<taskId>/evaluation.md` file.
    - Always ultra think on the problem space and potential solutions and do not present any options that you know are not valid or feasible.

3. **Identify any potential issues with the current implementation**
    - Evaluate the current implementation of the task and identify any potential issues or improvements that could be made.
    - Present the findings into a section in the `.taskmaster/tasks/<taskId>/evaluation.md` file.
    - Think hard about alternative solutions by evaluating a wide range of potential solutions and narrow down to the best two or three options.

When presenting the options to the user, always present them in a structured markdown file in the `.taskmaster/tasks/<taskId>/evaluation.md` file. Let the user choose by marking a checkbox in the file. This makes the process of deciding on the best approach for the task much easier for the user. Always STOP and ask the user after each step (1, 2, 3) before proceeding to the next step if any of the steps requires any user input, otherwise continue to the next step.

### 2. Planning the implementation

Now that the task is clear and the user has chosen the best approach, you can start planning the implementation in detail.

1. **Understand the Goal**
    - Use `task-master show <taskId>` to thoroughly understand the specific goals and requirements of the task

2. **Initial Exploration & Planning**
    - This is the first attempt at creating a concrete implementation plan
    - Explore the codebase to identify the precise files, functions, documentation and even specific lines of code that will need modification
    - Gather *all* relevant details from this exploration phase. Evaluate all **potentially relevant** files in the `docs`, `src`, `pocketflow/docs`, `pocketflow/cookbook` directory and ultra think on the problem space and potential ways of implementing the task.
    - If you are not sure about what the best approach is or if there are multiple potential ways to implement the task, always ask the user for input
    - Create the detailed plan in a new markdown file in `.taskmaster/tasks/<taskId>/task_<taskId>_implementation_plan.md`.



## Iterative Subtask Implementation

Once a task has been broken down into subtasks using `task-master expand` or similar methods, follow this iterative process for implementation:

1. **Understand the Goal (Preparation):**
   - Use `task-master show <subtaskId>` to thoroughly understand the specific goals and requirements of the subtask

2. **Initial Exploration & Planning (Iteration 1):**
   - This is the first attempt at creating a concrete implementation plan
   - Explore the codebase to identify the precise files, functions, documentation and even specific lines of code that will need modification
   - Determine the intended code changes (diffs) and their locations
   - Gather *all* relevant details from this exploration phase. Evaluate all **potentially relevant** files in the `docs`, `src`, `pocketflow/docs`, `pocketflow/cookbook` directory and ultra think on the problem space and potential solutions
   - If you are not sure about the solution or if there are multiple potential solutions, always ask the user for input
   - Create the detailed plan in a new markdown file in the `.taskmaster/tasks/<taskId>/<subtaskId>/<subtaskId>_implementation_plan.md` file

3. **Log the Plan:**
   - Run `task-master update-subtask --id=<subtaskId> --prompt='<detailed plan for implementing the subtask> --'`
   - Provide the *complete and detailed* findings from the exploration phase (`<subtaskId>_implementation_plan.md`) in the prompt. Include file paths, line numbers, proposed diffs, reasoning, and any potential challenges identified. Do not omit details. The goal is to create a rich, timestamped log within the subtask's `details`
   - To avoid writing out all the content of the `<subtaskId>_implementation_plan.md` file in the prompt, you can use shell command substitution like so: `--prompt="Implementation plan: $(cat .taskmaster/tasks/<taskId>/<subtaskId>/<subtaskId>_implementation_plan.md) Additional details and instructions: ..."`.

4. **Verify the Plan:**
   - Run `task-master show <subtaskId>` again to confirm that the detailed implementation plan has been successfully appended to the subtask's details

5. **Begin Implementation:**
   - Set the subtask status using `task-master set-status --id=<subtaskId> --status=in-progress`
   - Start coding based on the logged plan

6. **Refine and Log Progress (Iteration 2+):**
   - As implementation progresses, you will encounter challenges, discover nuances, or confirm successful approaches
   - **Before appending new information**: Briefly review the *existing* details logged in the subtask to ensure the update adds fresh insights and avoids redundancy
   - **Regularly** use `task-master update-subtask --id=<subtaskId> --prompt='<update details>\n- What worked...\n- What didn't work...'` to append new findings
   - **Crucially, log:**
       - What worked ("fundamental truths" discovered)
       - What didn't work and why (to avoid repeating mistakes)
       - Specific code snippets or configurations that were successful
       - Decisions made, especially if confirmed with user input
       - Any deviations from the initial plan and the reasoning
   - The objective is to continuously enrich the subtask's details, creating a log of the implementation journey that helps the AI (and human developers) learn, adapt, and avoid repeating errors

7. **Review (Post-Implementation):**
   - Once the implementation for the subtask is functionally complete, review all code changes and the relevant chat history
   - Identify any new or modified code patterns, conventions, or best practices established during the implementation
   - Create a new markdown report in the `.taskmaster/tasks/<taskId>/<subtaskId>/<subtaskId>-implementation-review.md` file that summarizes the implementation of the subtask and carefully considers any implications for any of the remaining subtasks (use ). This is the time to reflect on what you have learned, what initial assumptions you had that were incorrect and what key decisions you and the user made that could potentially impact other tasks and the project as a whole. Also consider if any existing documentation needs to be updated to reflect any key insights you have gained

8. **Mark Task Complete:**
   - After verifying the implementation and updating any necessary rules, mark the subtask as completed: `task-master set-status --id=<subtaskId> --status=done`

9. **Commit Changes (If using Git):**
   - Stage the relevant code changes and any updated/new rule files (`git add .`)
   - Craft a comprehensive Git commit message summarizing the work done for the subtask, including both code implementation and any rule adjustments
   - Execute the commit command directly in the terminal (e.g., `git commit -m 'feat(module): Implement feature X for subtask <subtaskId>\n\n- Details about changes...\n- Updated rule Y for pattern Z'`)
   - Consider if a Changeset is needed according to internal versioning guidelines. If so, run `npm run changeset`, stage the generated file, and amend the commit or create a new one

10. **Proceed to Next Subtask:**
    - Identify the next subtask using `task-master next`

## Code Analysis & Refactoring Techniques

- **Top-Level Function Search**:
    - Useful for understanding module structure or planning refactors
    - Use grep/ripgrep to find exported functions/constants:
      `rg "export (async function|function|const) \w+"` or similar patterns
    - Can help compare functions between files during migrations or identify potential naming conflicts



---

## General Guidelines

After reading `task-master` tasks, documentation, and code, carefully reflect on their quality and determine optimal next steps before proceeding. Use your thinking to plan and iterate based on this new information, and then take the best next action following the workflow above. Just because the information already exists, does not mean it is correct or complete. Always think critically and carefully evaluate the information when determining the best next steps.


- Create a new subsection to the comprehensive report in the `.taskmaster/tasks/<taskId>/implementation-review.md` file that summarizes the implementation and carefully considers any implications for any other tasks that may be affected/dependent by the changes (You can see dependencies in the `dependencies` field of the task). This is the time to reflect on what you have learned, what initial assumptions you had that were incorrect and what key decisions you and the user made that could potentially impact other tasks and the project as a whole. Also consider if any existing documentation needs to be updated to reflect any key insights you have gained


## File Structure

- `.taskmaster/tasks/<taskId>/<subtaskId>/<subtaskId>_implementation_plan.md` - The implementation plan for each of the subtasks.
- `.taskmaster/tasks/<taskId>/<subtaskId>/<subtaskId>-implementation-review.md` - The implementation review for each of the subtasks. Used to inform the planning of future subtasks.
- `.taskmaster/tasks/<taskId>/<taskId>-implementation-plan.md` - The implementation plan for the task. Used as input for the `task-master` CLI to create the subtasks.
- `.taskmaster/tasks/<taskId>/<taskId>-implementation-review.md` - Final implementation review for the task. Used to inform the planning of future tasks.
- `.taskmaster/tasks/tasks.json` - The task master task list. (source of truth for the task master CLI)
