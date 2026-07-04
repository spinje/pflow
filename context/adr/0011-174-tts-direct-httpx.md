# TTS calls Gemini directly over httpx, bypassing the LiteLLM seam

**Status:** accepted (Task 174; survived implementation + four live demo iterations unchanged)

pflow's rule is that `core/llm_client.py` is the *single seam* for all LLM calls — but `core/tts.py`
(`pflow ui --say` narration) deliberately makes a raw `httpx` `generateContent` call to Gemini TTS
instead. Reasons: LiteLLM is pinned to exactly `==1.86.1` (intentional — deterministic offline
pricing map; bumping has side effects) and that version's Gemini-audio path is young and buggy
(BerriAI/litellm#11118: pcm16-only, no streaming); the `google-genai` SDK would be a new dependency;
and the direct call is simpler than LiteLLM's chat-completions-with-`modalities:["audio"]` shape.
`httpx` is already a core dependency, and stdlib `wave` wraps the returned PCM16.

Do not "fix" this by routing TTS through `complete()` — the deviation is deliberate. The seam for
change is `synthesize(text, *, model, voice)` itself: a future provider swap (OpenAI, ElevenLabs)
or the cross-provider delivery-tag translation layer lands *inside* it, with zero agent-command
change — the agent-facing `[bracket]` syntax stays the ONLY syntax. Revisit only if the LiteLLM pin
moves and its audio path matures (then consistency with the single-seam rule may win).
