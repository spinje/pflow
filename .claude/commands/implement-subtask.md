Please implement Task with id: $ARGUMENTS.

You can find the task in the `.taskmaster/tasks_$id.txt` file.

BEFORE YOU START:
1. Mark as in-progress by using the `task-master set-status --id=$task_id --status=in-progress` command.
1. Read the task carefully and understand it fully.
2. Read and understand the tasks dependencies. They are referenced by their `task_id` and you can access them by using the `taskmaster show-task $task_id` command.
2. Read the documentation in the `docs/` folder to understand the project and the task.





// cat .taskmaster/tasks/tasks.json | jq '.tasks[] | select(.id == 1)'
