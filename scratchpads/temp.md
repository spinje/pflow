1. I think this only disables memo layer, there is no downside to using llm prompt/context caching.

2. I think this was for having a 1hour TTL on the prompt cache. if using 5min as default is should be fine to do this.

3. Yes, great observation. If we discover when writing the implementation plan that tier 2 verification is straighforward to implement we can consider adding it in v1.

4. If using no prewarming there is no point in prompt caching parts of the batch prompt right? then we only apply existing declarative caching blocks. But this should be a clear warning or potentially even an error that for batched llm calls the agent writing the workflow has to make an explicit decision declare to use warmup or not. Maybe use error if batch is bigger than 10 and prompt is larger than 2k tokens or something like that otherwise just warning when running the analyze-cache command.

5. What do you mean here?

6. we should assume llm_pricing.py can be removed (hopefully). The task spec is currently including a bit too much implementation details. These things should ideally be in just the implementation plan when we write it and task spec is the what and why. Plan is the how.

7. We are using Ai agent for the implementation, all estimates are off. dont rely on them (this is not important information)

8. Yes absolutely, hopfully we can minimize this by using litellms pricing outputs rather than our current llm_pricing.py.

9. Im not sure what you mean here, are you talking about when you rerun the workflow? Prompt caching is mostly for optimizing for prompt caching in one run. But you are right this needs to be clear when analyzing the cache. Is this what you mean?

10. There shouldnt be, if there is we change this retroactively.

---

Other things I think we should consider:

1. batch_cache: false and prewarm: true fields are mentioned but missing from the IR schema requirements. How do we handle this?

2. Cache block references to batch outputs are partially specified. ${item.X} is rejected. But what about ${batch-node.some_output} — a batch's aggregate output? This should also be valid right as well as all other possible "template variables"?

3. How do we handle that the cache blocks used in llm nodes have been declared when used? These should be verified using the template variable referenced in the cache block right?

4. Template position → rendered position mapping for batch auto-prefix. Spec says detection reads from the unresolved template (to locate ${item.X}). But the content block split happens on the rendered string. The mapping from template position to rendered position isn't specified but this needs to be investigated when writing the implementation plan.

5. Do we need a LiteLLM dependency audit?

6. pflow settings llm subgroup has a slight circularity. Spec says help text should "point users at env vars and pflow settings llm itself" — pointing at the command the user is already running. Just needs wordsmithing at implementation time.

---

ultrathink about all of this and lets discuss the next steps and remaning assumptions or ambiguity.