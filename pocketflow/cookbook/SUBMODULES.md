# Git Submodules Guide for PocketFlow Cookbook

This document explains how to work with the advanced example repositories that are included as git submodules in the PocketFlow cookbook.

## What are Git Submodules?

Git submodules allow us to include other Git repositories within our repository at specific versions. The advanced PocketFlow examples are maintained as separate repositories but included here for convenience.

## Initial Setup

### When Cloning PocketFlow

If you're cloning PocketFlow for the first time:

```bash
# Clone with all submodules
git clone --recursive https://github.com/yourusername/pflow.git

# Or clone first, then initialize submodules
git clone https://github.com/yourusername/pflow.git
cd pflow
git submodule init
git submodule update
```

### For Existing Clones

If you already have PocketFlow cloned but don't have the submodules:

```bash
git submodule init
git submodule update
```

## List of Submodule Examples

The following advanced examples are included as submodules:

1. **PocketFlow-Tutorial-Website-Chatbot** - Autonomous website chatbot
2. **PocketFlow-Tutorial-Danganronpa-Simulator** - Multi-agent game simulation
3. **Tutorial-Codebase-Knowledge** - Code documentation generator
4. **Tutorial-Cursor** - AI coding assistant
5. **Tutorial-AI-Paul-Graham** - Domain-specific Q&A system
6. **Tutorial-Youtube-Made-Simple** - Video summarizer
7. **Tutorial-Cold-Email-Personalization** - Email personalization tool

## Common Operations

### Checking Submodule Status

```bash
# See status of all submodules
git submodule status

# See which commit each submodule is at
git submodule
```

### Updating Submodules

```bash
# Update all submodules to their latest remote version
git submodule update --remote

# Update a specific submodule
git submodule update --remote pocketflow/cookbook/PocketFlow-Tutorial-Website-Chatbot

# Pull latest changes for a specific submodule
cd pocketflow/cookbook/PocketFlow-Tutorial-Website-Chatbot
git pull origin main
cd ../../..
```

### Making Changes to Submodules

If you need to make changes to a submodule:

```bash
# Enter the submodule directory
cd pocketflow/cookbook/Tutorial-Cursor

# Check out a branch (submodules are in detached HEAD by default)
git checkout main

# Make your changes
# ... edit files ...

# Commit and push (if you have permissions)
git add .
git commit -m "Your changes"
git push origin main

# Go back to main repository
cd ../../..

# Update the submodule reference in main repo
git add pocketflow/cookbook/Tutorial-Cursor
git commit -m "Update Tutorial-Cursor submodule"
```

## Troubleshooting

### Empty Submodule Directories

If submodule directories are empty:

```bash
git submodule init
git submodule update
```

### Detached HEAD Warning

Submodules often show "detached HEAD" state - this is normal. To make changes:

```bash
cd path/to/submodule
git checkout main  # or appropriate branch
```

### Merge Conflicts in Submodules

If you get merge conflicts in `.gitmodules` or submodule pointers:

1. Resolve the conflict in `.gitmodules` if needed
2. Decide which submodule version to use
3. Run `git add <submodule-path>` with the correct version
4. Complete the merge

### VS Code and Submodules

VS Code handles submodules well, but you may need to:
- Open each submodule folder to see its git status
- Use "Git: Sync" to update submodules
- Check "Source Control" panel for submodule changes

## Best Practices

1. **Don't commit submodule changes accidentally** - Be aware when you've modified submodule contents
2. **Update deliberately** - Don't update submodules unless you need newer features
3. **Check submodule status** - Before committing, check `git status` includes submodule changes
4. **Document submodule updates** - When updating a submodule reference, explain why in the commit message

## IDE Integration

Most modern IDEs handle submodules automatically:

- **VS Code**: Shows submodule changes in Source Control panel
- **IntelliJ IDEA**: Manages submodules in VCS menu
- **GitHub Desktop**: Shows submodule status and changes

## Further Reading

- [Git Submodules Documentation](https://git-scm.com/book/en/v2/Git-Tools-Submodules)
- [GitHub's Submodule Guide](https://github.blog/2016-02-01-working-with-submodules/)
