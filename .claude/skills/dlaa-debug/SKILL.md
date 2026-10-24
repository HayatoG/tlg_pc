---
name: dlaa-debug
description: Find and fix DLAA/jitter artifacts in The Last Guardian port (flicker, blocks, swimming surfaces that appear only with DLAA on). Use when the user reports a visual glitch with DLAA or temporal jitter.
---

Read `port/docs/dlaa-debugging.md` first: it has the method, the live debug controls and the
rules already in place. Then:

1. Ask the user to stand at the broken spot. Launch the game with `TLG_TOGGLE_FILE` and
   `TLG_JITTER_CONTROL` pointing to two files you can edit, so all tests run live without
   rebuilds.
2. Confirm it is jitter (bit 25 in the toggle file), then bisect with the jitter control file.
   The user judges each step by eye. Keep the steps short and wait for the answer, no long
   scripted runs.
3. When one shader is isolated, write `map` and read its `Jitter draw:` lines. Explain the
   cause in terms of what the draw does, and write a general rule in `vk_rasterizer.cpp` next to
   the existing ones, commented with the symptom, shader hashes and date like those.
4. Before committing, have the user check the new spot and the known test spots in the doc.
   Add the new rule and spot to the doc in the same commit.
