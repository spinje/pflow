#!/bin/bash
# Migrate legacy flat-file saved workflows to folder-based format.
#
# Old format: ~/.pflow/workflows/{name}.pflow.md
# New format: ~/.pflow/workflows/{name}/{name}.pflow.md
#
# Usage:
#   ./scratchpads/workflow-bundling-save/migrate-flat-workflows.sh          # dry run
#   ./scratchpads/workflow-bundling-save/migrate-flat-workflows.sh --apply  # actually migrate

set -euo pipefail

WORKFLOWS_DIR="${HOME}/.pflow/workflows"
DRY_RUN=true

if [[ "${1:-}" == "--apply" ]]; then
    DRY_RUN=false
fi

if [[ ! -d "$WORKFLOWS_DIR" ]]; then
    echo "No workflows directory found at $WORKFLOWS_DIR"
    exit 0
fi

migrated=0
skipped=0
already_folder=0

for file in "$WORKFLOWS_DIR"/*.pflow.md; do
    [[ -e "$file" ]] || continue  # handle no matches

    basename=$(basename "$file")
    # Strip .pflow.md to get the workflow name
    name="${basename%.pflow.md}"
    target_dir="$WORKFLOWS_DIR/$name"
    target_file="$target_dir/$basename"

    # Skip if folder already exists (already migrated or name conflict)
    if [[ -d "$target_dir" ]]; then
        echo "  SKIP: $name (folder already exists)"
        ((already_folder++))
        continue
    fi

    if $DRY_RUN; then
        echo "  WOULD MIGRATE: $file → $target_file"
    else
        mkdir -p "$target_dir"
        mv "$file" "$target_file"
        echo "  MIGRATED: $name"
    fi
    ((migrated++))
done

echo ""
if $DRY_RUN; then
    echo "DRY RUN — no changes made."
    echo "  Would migrate: $migrated workflow(s)"
    echo "  Already folder: $already_folder"
    echo ""
    echo "Run with --apply to execute the migration."
else
    echo "Migration complete."
    echo "  Migrated: $migrated workflow(s)"
    echo "  Already folder: $already_folder"
fi
