#!/bin/bash
# Mark finished tasks done and stamp them with a ## Completed date.
#
# A task counts as done when its ## Status says "done" OR a post-implementation
# review (task-review.md) exists. Reviews are only written after the work ships,
# so their presence is authoritative even when the Status field drifted stale.
# For review-backed tasks whose Status isn't "done", the Status is normalized to
# "done" (existing prose is discarded) before the date is added.
#
# Usage: ./scripts/add-completion-dates.sh [--dry-run]

set -e

DRY_RUN=false
if [ "$1" = "--dry-run" ]; then
    DRY_RUN=true
    echo "=== DRY RUN - No files will be modified ==="
    echo ""
fi

TASKS_DIR=".taskmaster/tasks"
STATUS_FIXED=0
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

    # A task is done if its Status says so, OR a post-implementation review exists.
    # (tolerant of a blank line between the ## Status heading and its value)
    task_status=$(awk '/^## Status/{found=1; next} found && NF>0 && !/^## /{print; exit}' "$task_file" 2>/dev/null | xargs)
    has_review=false; [ -f "$review_file" ] && has_review=true
    has_status_heading=false; grep -q '^## Status' "$task_file" 2>/dev/null && has_status_heading=true

    if [ "$task_status" != "done" ] && [ "$has_review" != true ]; then
        continue
    fi

    # Normalize a stale status to "done" (only reachable when a review exists).
    if [ "$task_status" != "done" ]; then
        echo "Task $task_num: status '${task_status:-<none>}' -> done (has task-review.md)"
        if [ "$DRY_RUN" = false ]; then
            if [ "$has_status_heading" = true ]; then
                # Replace the whole Status body (up to the next ## heading) with "done".
                awk '
                /^## Status/ { print; print ""; print "done"; print ""; skip=1; next }
                skip && /^## / { skip=0; print; next }
                skip { next }
                { print }
                ' "$task_file" > "$task_file.tmp" && mv "$task_file.tmp" "$task_file"
            else
                # No ## Status section at all — insert one right after the title.
                awk '
                NR==1 { print; print ""; print "## Status"; print ""; print "done"; next }
                { print }
                ' "$task_file" > "$task_file.tmp" && mv "$task_file.tmp" "$task_file"
            fi
        fi
        task_status="done"
        ((STATUS_FIXED++))
    fi

    # Check if ## Completed already exists
    if grep -q "^## Completed" "$task_file" 2>/dev/null; then
        echo "Task $task_num: Already has ## Completed - skipping date"
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
        # Insert ## Completed block after the status value line.
        # Tolerant of a blank line between ## Status and the value.
        awk -v date="$completion_date" '
        /^## Status/ { in_status=1; print; next }
        in_status && !inserted && NF>0 && !/^## / {
            print  # the status value
            print ""
            print "## Completed"
            print ""
            print date
            in_status=0
            inserted=1
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
echo "Status set to done: $STATUS_FIXED"
echo "Completion dates added: $UPDATED"
echo "Skipped (already had date): $SKIPPED"
echo "Unknown dates: $UNKNOWN"

if [ "$DRY_RUN" = true ]; then
    echo ""
    echo "Run without --dry-run to apply changes"
fi
