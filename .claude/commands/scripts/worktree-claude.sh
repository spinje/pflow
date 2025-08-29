#!/bin/bash

# Enhanced worktree script that opens Claude in a new terminal
# Usage: ./scripts/worktree-claude.sh <branch-type> <branch-name> [task-description] [--bring-changes]

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Check arguments
if [ $# -lt 2 ]; then
    echo -e "${RED}Error: Missing arguments${NC}"
    echo "Usage: $0 <branch-type> <branch-name> [task-description] [--bring-changes]"
    echo "Branch types: feat, fix, docs, refactor, test"
    echo "Options:"
    echo "  --bring-changes  Stash and apply uncommitted changes to new worktree"
    echo "Example: $0 feat github-list-prs \"Implement GitHub List PRs node\""
    exit 1
fi

BRANCH_TYPE=$1
BRANCH_NAME=$2
TASK_DESC=${3:-"Work on $BRANCH_NAME"}
BRING_CHANGES=false

# Check for --bring-changes flag
if [ "$4" = "--bring-changes" ] || [ "$3" = "--bring-changes" ]; then
    BRING_CHANGES=true
    if [ "$3" = "--bring-changes" ]; then
        TASK_DESC="Work on $BRANCH_NAME"
    fi
fi

# Validate branch type
case $BRANCH_TYPE in
    feat|fix|docs|refactor|test)
        ;;
    *)
        echo -e "${RED}Error: Invalid branch type '$BRANCH_TYPE'${NC}"
        echo "Valid types: feat, fix, docs, refactor, test"
        exit 1
        ;;
esac

# Construct full branch name
FULL_BRANCH="$BRANCH_TYPE/$BRANCH_NAME"
WORKTREE_DIR="../pflow-$BRANCH_TYPE-$BRANCH_NAME"
FULL_WORKTREE_PATH="$(cd .. && pwd)/pflow-$BRANCH_TYPE-$BRANCH_NAME"

# Check git status
echo -e "${BLUE}Checking git status...${NC}"
UNCOMMITTED_CHANGES=false
STASH_NAME=""

if ! git diff --quiet || ! git diff --cached --quiet; then
    UNCOMMITTED_CHANGES=true
    echo -e "${YELLOW}⚠️  Warning: You have uncommitted changes${NC}"
    git status --short
    echo ""
    
    if [ "$BRING_CHANGES" = true ]; then
        echo -e "${BLUE}--bring-changes flag detected. Stashing changes to bring to new worktree...${NC}"
        STASH_NAME="worktree-auto-stash-$(date +%s)"
        git stash push -m "$STASH_NAME" --include-untracked
        echo -e "${GREEN}Changes stashed as: $STASH_NAME${NC}"
    else
        read -p "Continue anyway? (y/N): " -n 1 -r
        echo ""
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            echo "Aborted."
            exit 1
        fi
    fi
fi

# Check if worktree already exists
if [ -d "$WORKTREE_DIR" ]; then
    echo -e "${YELLOW}Worktree already exists at $WORKTREE_DIR${NC}"
    EXISTING_BRANCH=$(cd "$WORKTREE_DIR" && git rev-parse --abbrev-ref HEAD)
    echo "Currently on branch: $EXISTING_BRANCH"
    echo ""
    echo "Would you like to:"
    echo "  1) Remove and recreate it"
    echo "  2) Open Claude in existing worktree"
    echo "  3) Cancel"
    read -p "Choice (1/2/3): " -n 1 -r
    echo ""
    case $REPLY in
        1)
            echo "Removing existing worktree..."
            git worktree remove "$WORKTREE_DIR" --force
            ;;
        2)
            # Skip to opening terminal
            ;;
        *)
            echo "Cancelled."
            exit 1
            ;;
    esac
fi

# Create worktree if it doesn't exist or was just removed
if [ ! -d "$WORKTREE_DIR" ]; then
    echo -e "${BLUE}Creating worktree...${NC}"
    git worktree add "$WORKTREE_DIR" -b "$FULL_BRANCH"
    echo -e "${GREEN}✅ Worktree created successfully!${NC}"
    
    # Apply stashed changes if we have them
    if [ "$BRING_CHANGES" = true ] && [ -n "$STASH_NAME" ]; then
        echo -e "${BLUE}Applying stashed changes to new worktree...${NC}"
        cd "$WORKTREE_DIR"
        git stash pop
        cd - > /dev/null
        echo -e "${GREEN}✅ Changes applied to new worktree${NC}"
    fi
fi

# Detect OS and open terminal accordingly
echo -e "${BLUE}Opening Claude in new terminal...${NC}"

# Create the initial message for Claude with full context
CHANGES_MSG=""
if [ "$BRING_CHANGES" = true ] && [ -n "$STASH_NAME" ]; then
    CHANGES_MSG="

Note: Uncommitted changes from the main worktree have been brought over to this worktree."
fi

CLAUDE_INITIAL_MSG="You have been assigned to work in a dedicated git worktree for this task.

Current worktree: $FULL_WORKTREE_PATH
Branch: $FULL_BRANCH
Original request: $TASK_DESC$CHANGES_MSG

You are now in an isolated git worktree specifically created for this task. All changes you make here are completely separate from the main branch. 

Please wait for the user to provide specific instructions on how to proceed with: $TASK_DESC. Do not do anything until the user has provided specific instructions. STOP and WAIT after this message."

# Create a command to run in the new terminal
CLAUDE_CMD="cd '$FULL_WORKTREE_PATH' && claude '$CLAUDE_INITIAL_MSG'"

if [[ "$OSTYPE" == "darwin"* ]]; then
    # macOS
    # Check which terminal app is available
    if [[ -d "/Applications/iTerm.app" ]]; then
        # iTerm2
        osascript -e "
        tell application \"iTerm\"
            activate
            create window with default profile
            tell current session of current window
                write text \"$CLAUDE_CMD\"
            end tell
        end tell"
    else
        # Default Terminal.app
        osascript -e "
        tell application \"Terminal\"
            activate
            do script \"$CLAUDE_CMD\"
        end tell"
    fi
    echo -e "${GREEN}✅ Opened Claude in new terminal window${NC}"
elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
    # Linux
    if command -v gnome-terminal &> /dev/null; then
        gnome-terminal -- bash -c "$CLAUDE_CMD; exec bash"
    elif command -v konsole &> /dev/null; then
        konsole -e bash -c "$CLAUDE_CMD; exec bash"
    elif command -v xterm &> /dev/null; then
        xterm -e bash -c "$CLAUDE_CMD; exec bash"
    else
        echo -e "${YELLOW}Could not auto-open terminal. Please run manually:${NC}"
        echo "  $CLAUDE_CMD"
    fi
else
    echo -e "${YELLOW}Unsupported OS for auto-terminal. Please run manually:${NC}"
    echo "  $CLAUDE_CMD"
fi

echo ""
echo -e "${GREEN}Summary:${NC}"
echo "  Branch: $FULL_BRANCH"
echo "  Location: $FULL_WORKTREE_PATH"
echo "  Task: $TASK_DESC"
if [ "$UNCOMMITTED_CHANGES" = true ]; then
    echo -e "  ${YELLOW}Note: Uncommitted changes remain in main worktree${NC}"
fi
echo ""
echo "A new terminal window should open with Claude ready to work on your task."
echo "If it doesn't, manually run:"
echo "  cd $WORKTREE_DIR && claude \"$TASK_DESC\""