---
name: setup-deep-modules
description: Set up deep-module boundaries in a Go or Python repo, with implementation hidden behind entry points, tests reaching only those entry points, and no cycles. Use when adding module boundaries, internal packages, import-linter or go-arch-lint, or when asked to make packages deep modules. For TypeScript, use setup-ts-deep-modules. User-invoked.
disable-model-invocation: true
---

# Setup Deep Modules

Make every package in this repo a **deep module**: a lot of behaviour behind a
small interface. A package's public surface is its **entry point**, and
everything under its private folder is hidden. This skill installs the
language's boundary gate, scaffolds one copy-me module, and proves the gate
bites.

For the vocabulary (deep module, interface, seam, depth), call the Skill tool
with "codebase-design" and use its language throughout.

## The shape this enforces

| Concern | Go | Python |
|---|---|---|
| Packages root | `internal/` if it already holds packages, else `pkg/`, else create `internal/` | `src/packages/` if `src/` exists, else `packages/` |
| Entry point | the `<name>/` package; its exported identifiers | `<name>/__init__.py` plus public root modules |
| Private implementation | `<name>/internal/...` | `<name>/_lib/...` |
| Tests | `package <name>_test` beside the entry package | `<name>/tests/` with `__init__.py` |
| Boundary gate | the Go compiler; `go-arch-lint` for layering | `import-linter` |
| Cycle gate | the Go compiler | `acyclic_siblings` |

Four rules, all errors:

1. **Entry-point boundary**: code outside a package (app code or another
   package) may import only that package's entry point, never its private
   implementation.
2. **Intra-package freedom**: a package's own files may import each other
   freely. In Go the compiler allows this inside the `internal/` tree; in
   Python the protected contract allows the package and its descendants.
3. **Tests through the entry point**: tests may import any package's entry
   point and their own test fixtures, but never a package's private
   implementation, not even their own.
4. **No cycles**: no dependency cycles between packages.

**Entry points, not a barrel.** A Python package may expose several small root
modules (`__init__.py`, `client.py`, `server.py`) instead of funnelling
everything through one giant `__init__.py`. A Go package is already one entry
point; if a module genuinely needs several public surfaces, make them separate
packages. Never re-export a whole subtree through one file.

Layering (which packages may depend on which) is a **different** concern. The
Go track wires `go-arch-lint` with a permissive starter and the Python track
leaves a commented `layers` contract; fill either in only when the repo has
decided its dependency direction.

## Step 1 - Detect and confirm

- **Language**: `go.mod` means Go; `pyproject.toml`, `setup.py` or
  `setup.cfg` means Python. If both exist, ask which tree to set up first. Do
  not try to convert both in one pass.
- **Packages root**: use the table above. If the repo already has a different
  obvious convention (for example packages directly at the repository root),
  confirm it rather than creating a second convention.
- **Existing config**: check for `.go-arch-lint.yml`, `[tool.importlinter]` or
  `.importlinter`. If one exists, merge the rules into it and say what you
  added. Never overwrite an existing architecture file.
- **Flat Python**: if Python code is a directory of flat modules loaded by
  path rather than packages, stop and ask. This skill installs package
  boundaries; inventing a package split is a refactor, not a setup.
- **Existing violations**: a brownfield repo may already have cycles or deep
  imports. Surface them. Do not silently weaken or delete a rule to get a
  green run.

**Done when:** language, packages root and existing-config status are known,
and you have permission to proceed on a brownfield tree.

## Step 2 - Follow the language track

Read the matching reference end to end and follow its steps:

- **Go**: [`references/go.md`](references/go.md)
- **Python**: [`references/python.md`](references/python.md)

Each reference contains the install, configuration, scaffold, wiring, proof
and documentation steps. Use [`references/go-arch-lint.yml`](references/go-arch-lint.yml)
or [`references/importlinter.toml`](references/importlinter.toml) as the
starter for the config.

## Step 3 - Completion criteria

The skill is complete only when all of these are true:

- The copy-me `example` package exists and is visibly deep: its entry point
  delegates to a private implementation, and its test imports only the entry
  point.
- The boundary gate is wired into the command that already runs lint or CI,
  not left as a command nobody runs.
- You have observed **pass -> intentional violation fails -> revert passes**
  for the deep-import rule. If the violation does not fail, the gate is
  decorative; fix it before finishing.
- The packages-root README explains the layout and the import rule, and the
  repository's agent-instructions file points at it.
- Existing violations are either fixed or recorded with a reason. A rule is
  never loosened just to make the first run green.

## Notes

- **Go privacy is path-scoped.** A package under
  `<parent>/internal/...` is importable only by code rooted at `<parent>`. That
  is what makes `<name>/internal/...` private to the module at `<name>/`, and
  what makes the compiler reject deep imports and import cycles.
- **Python privacy is convention plus the linter.** `_lib` is not private to
  the interpreter; the `protected` and `forbidden` contracts are the
  enforcement. Keep the `_lib` name so readers can see the boundary at a
  glance.
- **Do not split code just to satisfy the shape.** If a package is small, keep
  it small and one tier deep. The rules matter more than an empty `_lib`.
- **No secrets, no host paths.** Skill content and generated configs name
  repository-relative paths only.
- TypeScript repos are out of scope here; use `setup-ts-deep-modules`.
