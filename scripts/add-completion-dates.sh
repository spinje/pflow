#!/bin/bash
# Add ## Completed dates to done task files
# Usage: ./scripts/add-completion-dates.sh [--dry-run]

set -e

DRY_RUN=false
if [ "$1" = "--dry-run" ]; then
    DRY_RUN=true
    echo "=== DRY RUN - No files will be modified ==="
    echo ""
fi

TASKS_DIR=".taskmaster/tasks"
UPDATED=0
SKIPPED=0
UNKNOWN=0

for dir in "$TASKS_DIR"/task_*/; do
    task_num=$(basename "$dir" | sed 's/task_//')
    task_file="$dir/task-$task_num.md"
    review_file="$dir/task-review.md"
    progress_file="$dir/implementation/progress-log.md"

    # Skip if task file doesn't exist
    if [ ! -f "$task_file" ]; then
        continue
    fi

    # Check if task is done
    task_status=$(grep -A1 "^## Status" "$task_file" 2>/dev/null | tail -1 | xargs)
    if [ "$task_status" != "done" ]; then
        continue
    fi

    # Check if ## Completed already exists
    if grep -q "^## Completed" "$task_file" 2>/dev/null; then
        echo "Task $task_num: Already has ## Completed - skipping"
        ((SKIPPED++))
        continue
    fi

    # Determine completion date
    completion_date=""
    date_source=""

    # Try 1: task-review.md creation date
    if [ -f "$review_file" ]; then
        completion_date=$(git log --format="%ai" --diff-filter=A -- "$review_file" 2>/dev/null | head -1 | cut -d' ' -f1)
        date_source="task-review.md"
    fi

    # Try 2: progress-log.md last commit date
    if [ -z "$completion_date" ] && [ -f "$progress_file" ]; then
        completion_date=$(git log -1 --format="%ai" -- "$progress_file" 2>/dev/null | cut -d' ' -f1)
        date_source="progress-log.md"
    fi

    # Try 3: Unknown
    if [ -z "$completion_date" ]; then
        completion_date="unknown"
        date_source="no source"
        ((UNKNOWN++))
    fi

    echo "Task $task_num: $completion_date (from $date_source)"

    if [ "$DRY_RUN" = false ]; then
        # Insert ## Completed after ## Status section
        # Find line number of ## Status, then insert after the status value

        # Create temp file with the new content
        awk -v date="$completion_date" '
        /^## Status/ {
            print
            getline  # print the status value line
            print
            print ""
            print "## Completed"
            print date
            next
        }
        { print }
        ' "$task_file" > "$task_file.tmp"

        mv "$task_file.tmp" "$task_file"
    fi

    ((UPDATED++))
done

echo ""
echo "=== Summary ==="
echo "Updated: $UPDATED"
echo "Skipped (already had date): $SKIPPED"
echo "Unknown dates: $UNKNOWN"

if [ "$DRY_RUN" = true ]; then
    echo ""
    echo "Run without --dry-run to apply changes"
fi
