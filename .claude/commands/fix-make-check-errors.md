There are currently some make check errors that need to be fixed.

You have been assigned to fix them.

Input:
--use-parallel-subagents=$ARGUMENTS (default: false)

if --use-parallel-subagents=true, you must use subagents to fix the errors.
if --use-parallel-subagents=false, you must not use subagents to fix the errors.
if --use-parallel-subagents is empty, you should not use subagents to fix the errors.

Requirements:
- You must fix the errors without using #noqa comments if not absolutely necessary.
- You must think hard before attempting each error and make sure you understand the root cause of the error and the BEST way to fix it.
- If there are multiple ways to fix the error, you must reason through the pros and cons of each and choose the best option.
- You must never "cheat" by making the easy fix. You must always make the best fix.

Should you use subagents to fix the errors?

If yes, please carefully consider and followthe following requirements:

Requirements if using subagents:
- Use the @write-tests-fixer subagent to fix issues in tests
- Use the @code-implementer subagent to fix issues in code
- Only assign one subagent per file (never use the same subagent for errors in multiple files)
- Define a termination criteria for each subagent
- Provide a comprehensive context and instructions to each subagent
- Be clear about the scope of the subagent's work when writing the instructions to the subagent
- Make sure to point out that they should follow the general requirements from above (no cheating, make the best fix, etc.)
- Always deploy the subagents in PARALLEL if there are errors in multiple files (this means using ONE function call block to deploy all subagents)
- Use as many subagents as there are failing files (parallelise them, never use sequential function calls to deploy subagents)