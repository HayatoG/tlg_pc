# Debugging DLAA artifacts

DLAA (DLSS at native resolution) needs every scene draw shifted by a sub-pixel jitter each
frame. The game was not written for that, so some passes break when jitter is applied wrongly:
flicker, blocks, or surfaces that swim. This is the method that found the known cases, and the
rules they turned into. Code: `vk_rasterizer.cpp` (jitter decision per draw),
`vk_temporal_upscaler.cpp` (DLSS dispatch, jitter sequence), `camera_motion.comp` (motion).

## Method

1. **Is it jitter?** Run with `TLG_TOGGLE_FILE=<file>` and write `33554432` (bit 25) into the
   file: jitter off, live. Artifact gone → a draw is jittered that must not be, or two passes
   of one surface are jittered differently. Still there → not a jitter bug (for example DLSS on
   alpha-tested grass shimmers in motion; that is a DLSS limit).
2. **Find the draw.** Run with `TLG_JITTER_CONTROL=<file>`. The file is re-read twice a second,
   so stand at the broken spot and edit it while the game runs, no rebuilds:
   - `map`: logs one frame of jitter-eligible draws (`Jitter map:` index and pixel shader) and
     a line per scene-depth draw (`Jitter draw:` shader, indices, depth write and compare
     function, depth target id, whether it was jittered, bound images with ids).
   - `lo hi`: only eligible draws in that index range (counted from the sky pass) are
     jittered. Halve the range until one shader remains.
   - `only <ps>`, `not <ps>`: jitter only, or never, draws of that pixel shader (hex).
   - `skip <ps>`: drop the draws of that shader, to see what they are on screen.
   Judge each step by eye in the game. Scripted camera moves rarely frame the spot.
3. **Understand it, then write a rule.** Once a shader is isolated, look at its `Jitter draw:`
   lines: what it writes, what it samples, how it tests depth, and which other draws touch the
   same mesh or depth. Fix the class of draw, not the hash: other scenes have other shaders
   with the same pattern.
4. **Check the known cases** below still look right after a change.

## Rules in place

- **Only geometry drawn into the scene depth is jittered** (the depth the size of
  `GameSize()`, written by the sky pass). Full-screen passes are not: a shifted quad leaves an
  edge column unwritten.
- **Draws that sample a scene depth are not jittered** (`SamplesSceneDepth()`). Decal and
  light volumes rebuild positions per pixel from the already jittered depth. Jittering their
  boxes misplaced their G-buffer writes: blocks on the boy's face, neck and hair
  (ps `da3456ba`, 36-index boxes).
- **A redraw of a mesh takes the jitter of its first jittered depth pass**, sampling or not
  (mesh = index address and count, reset each frame). Cave water draws a depth pre-pass
  (ps `26c53528`) and then shades the same mesh with a LessEqual test (ps `05adfd4d`,
  `4755277d`). The shading samples the scene depth, so the previous rule left it unshifted and
  its test hit or missed the pre-pass per pixel: flicker.
- **One jitter per frame.** The emulator can start several "frames" per game frame. The jitter
  advances once, at the game's motion pass, so the pre-pass and G-buffer share one offset.
- **Hair writes no motion vectors**; it inherits those of the surface behind it. The motion
  shader replaces such vectors with camera motion at the hair's depth (mode 3).

## Known test spots

- The boy up close (face, neck, hair), any scene.
- Water in the first cave.
- Grass while moving: shimmer here is DLSS, not a bug (jitter off is worse).
