We were evaluating **n8n’s AI workflow generation feature**, especially from the angle of whether there is a product gap for something like **pflow / chips**.

The main conclusion was:

> n8n’s AI builder is useful for generating workflow drafts, but it is not yet a robust AI-native workflow development environment.

It seems good for **simple-to-medium automations**: webhook → transform → API call → database/sheet → Slack/email. It can generate a usable first structure and help with refinement/debugging. But for larger workflows with branching, retries, pagination, state, credentials, custom APIs, and production reliability, it becomes more of a helper than something you can trust blindly.

We then looked at what users seem to want beyond n8n’s current AI features. The key demand is not merely “generate a workflow from a prompt,” but something closer to:

> plan → generate small part → validate → test → patch → preserve working parts → repeat

Users want more control over context, local/BYOK models, better node/schema awareness, safer edits, reusable HTTP patterns, stronger tool reliability, and something more like Cursor’s step-by-step guarded editing rather than a black-box “describe and generate” experience.

The important correction was around whether n8n “redos the workflow” every time. The answer is: **not necessarily**. n8n’s AI Workflow Builder can refine existing workflows and uses the current workflow context. So it is not purely regenerate-from-scratch. But the weakness is that users do not appear to get a strong **patch/diff/checkpoint model**. They may not clearly see what changed, whether unrelated nodes were preserved, or how to safely rollback or validate changes.

So the sharper distinction became:

> n8n supports conversational refinement, but not fully safe, inspectable, test-driven graph editing.

The product gap for pflow/chips is therefore not “beat n8n at visual automation.” It is more like:

> Build an AI-native workflow compiler/composition layer with typed primitives, reusable workflow chips, visible plans, small patches, validation, tests, and export/adapters to tools like n8n.

In other words, n8n is strong as a canvas/runtime, while pflow could differentiate as the **planning, validation, modularity, and safe-editing layer above workflow tools**.
