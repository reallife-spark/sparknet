---
name: computer-user
description: >
  Use a computer the way a person does — see a screen, aim at a target, click or type, and remember how the
  run went. Based on the Agent-Computer Interface pattern from Agent-S (simular-ai): screen observation,
  UI grounding, mouse/keyboard input, and experience memory (narrative + episodic). Use this skill when the
  user says "use the computer", "control the desktop", "click that", "drive the GUI", "automate this app",
  "take over the screen", "computer-use", "Agent-S", "ACI", "screen control", "UI automation", or wants any
  task done by operating a graphical interface rather than a shell. Triggers for both local desktops and
  remote/virtual displays. This skill is about *operating* a GUI; it does not run web searches or produce
  plans — those are separate skills.
---

# Computer User — operate a computer like a person

You operate a graphical computer the way a human operator would: watch the screen, ground
your intent to an on-screen element, act through mouse and keyboard, verify the screen
changed, and remember what worked so the next run is cheaper. This is the Agent-Computer
Interface (ACI) pattern from Agent-S: perception and action are mediated through the
*screen*, not the shell.

**Before you act:** follow the Config Resolution Protocol in `llm-wiki/SKILL.md` (walk up
CWD for `.env` → `~/.wiki/config`). It gives `VAULT_PATH`. Read `MEMORY.md`, `log.md`, and
today's `sessions/<date>.md` so your experience memory extends the vault instead of
restarting it.

## Principles

1. **Ground on the screen, not the DOM.** If the environment exposes accessibility or
   DOM data use it to *verify*, but the source of truth is what a person sees. Aim is
   always to a visual target, then confirmed by a screenshot difference.
2. **One action per observation.** Screenshot → pick one target → act → verify. Never
   blind-fire a sequence against an image of a stale screen.
3. **Experience is reusable.** A successful multi-step interaction is a *procedure*: save
   it (narrative memory) with enough context to replay or recall later. A failed one is a
   *lesson*: record the failure mode and the correction (episodic memory).
4. **Hierarchy when the task is long.** Decompose a large goal into sub-goals; execute
   each sub-goal with the observe–act–verify loop and hand the chain off explicitly.
   Small atomic tasks (one click) never need decomposition.

## The Observe–Aim–Act–Verify loop

Run this loop for every single action.

1. **Observe.** Capture the current screen (or the active window's region). If the
   environment offers accessibility data, OCR, or element trees, use them as *auxiliary
   input to aim* — never as the only truth.
2. **Aim.** Decide the exact target. For a click: *what* (button/field/menu item), *where*
   (coordinates or element identity). For typing: *what text, into which field, with which
   modifier state*. State the intent in one line before acting.
3. **Act.** Deliver the input — mouse move, click, double-click, drag, scroll, key,
   key-combo, text entry. Prefer the environment's own input API when it exists (native
   automation library, OS accessibility, remote-control channel); fall back to generic
   coordinate input only when no API is available, and say so.
4. **Verify.** Take a fresh screenshot. Confirm the screen state matched what you
   expected (same screen, focus moved, field filled, dialog opened, content changed). If
   it did not, do *not* repeat the same input — reobserve and re-aim.

If verification fails twice in a row on the same target, stop and report: the aim was
probably wrong (different element than intended), not the input.

## Tooling by environment

Pick the first input mechanism that exists on the target machine. Never assume a tool is
installed; check, and degrade gracefully.

- **Native automation library present** — use it (e.g. an automation framework bound to
  the desktop session). Prefer element-level targeting: role, name, label, handle.
- **Removable input device** — a keycap relay / HID emulator that types and clicks on
  the target computer without installing software on it. Good for air-gapped or head-
  locked machines; the skill sees the target via screen capture or the relay's channel.
- **Good old screen capture + coordinate input** — screenshot from the display output, aim
  with OCR / template match, deliver input by coordinates. Least reliable, always last.

Whatever the mechanism, the loop is identical. The skill text reads the same on a local
desktop, a VM display, or a remote screen.

## Experience memory — narrative and episodic

Two memory streams, both compact and vault-resident.

### Narrative memory (procedures — *how to do X*)

When a multi-step task completes, distill the working action sequence into a procedure
page. One procedure per page, with: the goal, the starting screen state, the exact
sequence that worked (targets + inputs), and the failure modes encountered. File it under
the vault's `skills/` category (or the role subvault's equivalent). Cross-link it from the
index. This is the Agent-S "experience-augmented" payoff: next time the same task appears,
recall the procedure instead of rediscovering it.

### Episodic memory (runs — *what happened this time*)

When you attempted a non-trivial goal, append a dated one-line summary to today's session
file: goal, outcome, the one thing that changed the result. If it was a novel failure,
record the failure mode and correction so the narrative procedure (above) is written from
evidence, not memory.

Do not bloat `MEMORY.md` — it holds standing state only. Procedures and run summaries go
to their dated/category locations.

## Long tasks — hierarchical decomposition

For anything with more than ~5 actions, or with a decision point:

1. State the goal. Split it into sub-goals that each end at a *verifiable screen state*.
2. Execute sub-goals in dependency order. Finish each one (verified) before starting the
   next. Record partial progress so an interruption can resume.
3. If a sub-goal is itself long, recurse — delegate to yourself as a sub-step rather than
   flattening everything into one chain.
4. Collapse the completed chain into a narrative procedure when done (see above).

## Hard stops

- **No input during destructive dialogs** — if a dialog warns about data loss, stop and
  ask. Do not click through it.
- **No aim-at-OCR when intent is ambiguous** — if a visible element's meaning is unclear,
  ask before acting.
- **Do not fight a machine you cannot observe** — if the screen capture channel is dead,
  stop. Acting blind is how a stray click lands on the wrong thing.
- **Human in the loop for irreversible actions** — destructive operations (delete,
  overwrite, format, purchase, send) require user confirmation before the click.

## Cross-references

- `llm-wiki/SKILL.md` — vault config resolution, retrieval primitives
- `wiki-capture/SKILL.md` — saving a finding/procedure as a lasting vault page
- The role's `AGENTS.md` — role-specific automation boundaries and owned services