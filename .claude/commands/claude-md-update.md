---
description: Read before updating CLAUDE.md files
---

Your task is to keep the CLAUDE.md files in the project in perfect shape.

These files are made for AI agents operating the codebase and are read automatically by agents when they either read or write to a file in the same folder of the CLAUDE.md file or any of the subfolders. This means that in order to not waste tokens and confuse rather than help the agents, the files should be kept up to date with the latest changes in the codebase and  be free from the following:

- Stale information
- Contradicting information
- Reduntant information
- Repetitive information
- Information that is very easy to understand by just reading the code
- Information that is easy to find
- Explaining code that is obvious

You should NOT remove information that you are not sure about. If you have read the related code and is still unsure, thats a good sign that the explanation is not obvious and belongs in the CLAUDE.md file. If you suspect the information is wrong you should dig deeper and verfiy before removing or updating the information.

Only edit, remove or add information that you KNOW will make the document a more valuable artifact for any future agents.

Think about what information they are likely to need and how the file can make it as accessible as possible.

If you have extensive knowledge by a specific task, issue or feature in your context window. make sure to not overfit to your current knowledge. Instead, take a step back and think about what minor parts of your vast knowledge that would actually help. This is not a knowledge dump, every line should have a purpose. And you need to provide a clear rationale for every change you make before you make it.