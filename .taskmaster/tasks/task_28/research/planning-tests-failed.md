The registry was incomplete because the initial setup only scanned the file nodes directory. By scanning all
node directories, the ComponentBrowsingNode now has access to GitHub nodes, which allows the WorkflowGeneratorNode to create workflows that actually work with GitHub issues (as the tests expect). This is now fixed!


The WorkflowGeneratorNode is actually working correctly! The tests have unrealistic expectations:

1. What the test requests: "Create an issue triage report for bugs"
2. What nodes are available: Only file operation nodes (read-file, write-file, etc.)
3. What the generator creates: A write-file workflow to save the report (best it can do with available nodes)
4. What the test expects: GitHub-specific nodes that don't exist in the

The generator is correctly:
- ✅ Using template variables ($project_name, $issue_type, etc.)
- ✅ Creating valid FlowIR structure
- ✅ Working with the nodes it has available
- ✅ Not hardcoding discovered values

The tests need to be more realistic about what workflows can be generated given the available components. The generator can't create GitHub workflows if GitHub nodes aren't registered!

Also, when generating new workflows, we need to be a bit more specific about what exactly the workflow should do, mentioning github or git etc.

**Important insight:**

The less defined the user's prompt is, the more likely is it that the user is trying to run a workflow that currently exists than to create a new one.
We can assume that user will be fairly explicit about what they want to create a workflow for since it would not make much sense trying to give instructions to create a new workflow where there is extreme ambiguity.

What we should do is:

1. when writing tests that expect a workflow to be created, we should be more specific about what the workflow should do.
2. when writing tests that expects a workflow to be found and reused, we should be less specific
3. we need to test both these scenarios
4. we should use the north star examples when writing tests: see `docs/vision/north-star-examples.md`, there is three levels of increasing complexity. We should always aim to write tests at the highest level of complexity when possible.

Read `docs/vision/north-star-examples.md` to make sure you understand these examples! Think hard what this means for the tests you write.

Let me know when you have read and thought hard about this and is ready to deploy test-writer-fixer subagents to fix this.
