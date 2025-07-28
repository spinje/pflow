
Inputs: --taskId=$ARGUMENTS

Available inputs:
- taskId: The ID of the task to implement

---

Before resetting your context window, your final responsibility is to prepare a handoff memo for the agent who will implement **Task <taskId>**.

## 🎯 **Your mission**:
Perform a strategic *braindump* of the most important information the next agent needs to know implementing **Task <taskId>**. This is **not** a summary or a formal report. It's a focused transfer of **tacit knowledge**—insights that would otherwise vanish with your context window.

## 🧠 **Your Edge**:
You have been selected to write this handoff memo based on what you have in your context window. Everything you have in your context window is most likely relevant to the task and you should write from your unique perspective and consider the task based on your knowledge and experience from the conversation with the user. Do NOT rely on anything outside of your context window when writing details. Focus on what you know!

## ✅ **What to include:**

- The **core outcomes and side effects** that <taskId> must build on or avoid
- Any **assumptions made** that might constrain or impact <taskId>
- Unexpected **discoveries, edge cases, or fixes** that changed your approach
- **Patterns or anti-patterns** you uncovered that should be reused or avoided
- Warnings about **subtle bugs, performance issues, or architectural caveats**
- Any **changes to shared interfaces, data structures, or contracts**
- If applicable: **Which previous sibling tasks you leaned on**, and why
- **Links to files and code** that are relevant to the next agent
- **Links to docs** that will be invaluable to the next agent
- **All relevant context or knowledge** that you have in your context window that might be useful to the agent implementing the task

## 🚫 **What NOT to include:**

- Do not rehash the refined spec for <taskId>—it will be read separately
- Do not list implementation steps or details
- Do not include generic advice or boilerplate reminders
- Do not repeat the context file or the implementation plan, here is your chance to provide context that fills the gaps of what the other documents are missing
- Do not include anything that is not directly relevant to the task
- Do not include anything that you are not sure about or that you are not sure you understand, if something seems important but you are not sure, write it down as a question or a TODO item to investigate during the implementation

## 📦 **Your mindset**:
Imagine you're leaving a note for your future self, knowing you'll return with no memory of what you've done. What would you be furious at yourself for *not* mentioning?

Write clearly, concisely, and with care. This is your final contribution to the success of this task.

Include information that was hard for you to find out or easy to misinterpret or that is not intuitively obvious.

## 🔁 Self-Reflection Loop

Before starting to write the handoff memo ask yourself these questions:

1. **What do I know that no one else knows?**
2. **What is the most valuable information I can provide to the agent implementing the task?**
3. **What is the most important things the user has told me that is relevant to the task?**
4. **What is the most profound and hidden insights I have gained from the conversation with the user?**
5. **What feels intuitive to me but might not be obvious to the next agent?**
6. **What assumptions did I make that weren't explicitly stated?**
7. **What would break if my understanding were wrong?**
8. **Did I prioritize elegance where robustness matters more?**
9. **Have I shown my reasoning or only my conclusions?**
9. **Will someone else understand why I made these choices?**
10. **What patterns am I carrying forward that may no longer apply?**

## 🧠 Think and make a plan

Ultrathink and make a detailed plan of what to include in the document before you start writing it (this is your chance to really think through everything you know and how it might be useful to the next agent)

## Output

Write your output in markdown format in a `.taskmaster/tasks/task_<taskId>/<taskId>_handover.md` file.


## Notes

Make sure to remind the agent recieving the handoff to not begin implementing just read and say that they are ready to begin at the end of the document.
