# Python track

Read [`../SKILL.md`](../SKILL.md) first. This is the Python procedure behind the
four rules. Follow it end to end, including the proof.

## Step 1 - Confirm the packages root

- If `src/` exists, use `src/packages/`; otherwise use `packages/`.
- The **root package** is the dotted import path of that root: normally
  `packages`, or `mypkg.packages` if the root is nested under another package.
  Import-linter's `root_package` takes that name, not the filesystem path.
  Replace `packages` with that dotted path throughout the contracts below.
- With a `src/` layout, either install the project editable or run the checker
  with `PYTHONPATH=src`. The examples below use the explicit path.
- A namespace package (no `src/packages/__init__.py`) is fine; add an empty
  `__init__.py` only if the repository already uses one there. Never put
  imports in it.
- If an obvious third convention exists, confirm it instead of creating a
  second one.
- Check for `[tool.importlinter]` in `pyproject.toml` or a `.importlinter`
  file. Merge into it; never overwrite it.
- If the Python code is a directory of flat modules loaded by path rather than
  packages, **stop and ask**. This skill installs package boundaries; inventing
  a package split is a refactor, not a setup.

**Done when:** the packages root, the root package name and the existing
config status are known.

## Step 2 - Install import-linter

Add `import-linter` to the project's development dependencies. Pin a version
that supports the project's Python floor:

Choose the line that matches the project's Python floor:

```text
import-linter>=2.6,<2.16   # Python 3.10 still supported
import-linter>=2.6         # Python >= 3.11; lock the resolved version
```

Why those bounds: `protected` arrived in 2.5 and `acyclic_siblings` in 2.6;
2.16 drops Python 3.10. Use the project's existing tool (`uv`, `pip`,
`poetry`, `pdm`) and commit its lockfile. Do not install globally.

**Done when:** `import-linter` is in the development dependency set and
`lint-imports` resolves inside the project environment.

## Step 3 - Write the contracts

Add this block to `pyproject.toml` under `[tool.importlinter]`, or translate it
to INI if the repository uses `.importlinter`. Replace `example` with the
package name. Keep the contracts together so the four rules are visible in one
place.

```toml
[tool.importlinter]
root_package = "packages"

# Rule 1 + 2: the package and its descendants may reach _lib; outsiders may not.
[[tool.importlinter.contracts]]
name = "example internals are private"
type = "protected"
protected_modules = ["packages.example._lib"]
allowed_importers = [
    "packages.example",
    "packages.example.*",
    "packages.example.**",
]

# Rule 3a: tests are private to their own package's test tree.
[[tool.importlinter.contracts]]
name = "example tests are private"
type = "protected"
protected_modules = ["packages.example.tests"]
allowed_importers = [
    "packages.example.tests",
    "packages.example.tests.*",
    "packages.example.tests.**",
]

# Rule 3b: no test imports any package's implementation directly.
# allow_indirect_imports is essential: a test -> entry point -> _lib is the
# public path, not a deep import. Without it, the clean example fails.
[[tool.importlinter.contracts]]
name = "tests never import implementation"
type = "forbidden"
source_modules = ["packages.*.tests"]
forbidden_modules = ["packages.*._lib"]
allow_indirect_imports = true

# Rule 4: no cycles between packages or their descendants.
[[tool.importlinter.contracts]]
name = "no package cycles"
type = "acyclic_siblings"
ancestors = ["packages"]

# Layering is separate. Fill this in only when the repository has decided its
# dependency direction; the four rules above do not require it.
# [[tool.importlinter.contracts]]
# name = "package layers"
# type = "layers"
# layers = ["packages.api", "packages.service", "packages.storage"]
```

For each additional package that has a `_lib/` folder, duplicate the
`example internals are private` block and change the package name. For each
package that has a `tests/` package, duplicate the `example tests are private`
block too. A package with no `_lib` or no `tests` needs no block: import-linter
fails if a protected module does not exist. Keep the generic `forbidden` and
`acyclic_siblings` blocks once: their wildcards cover every package.

Why the importer lists include three forms:

- `packages.example` lets `__init__.py` itself import `_lib`;
- `packages.example.*` covers direct modules such as `client.py` and the
  `tests` package;
- `packages.example.**` covers deeper subpackages.

`as_packages` defaults to true, so a protected package's descendants may also
import each other. That is what lets files inside `_lib` cooperate.

If the clean tree reports pre-existing cycles, do not delete the contract.
Either fix the cycle or add a narrow `ignore_imports` entry with a TODO and a
ticket reference, and say so in the final report.

**Done when:** the four contracts are present (plus one pair of protected
blocks per package) and the config names the correct root package.

## Step 4 - Scaffold the example package

```text
src/packages/
  example/
    __init__.py        # entry point
    _lib/
      __init__.py
      impl.py          # implementation
    tests/
      __init__.py
      test_example.py  # black-box test
```

`src/packages/example/__init__.py`:

```python
"""Public entry point for example."""

from ._lib.impl import run

__all__ = ["run"]
```

`src/packages/example/_lib/impl.py`:

```python
def run(value: str) -> str:
    """Implementation detail: outside code reaches it through the package."""
    return value
```

`src/packages/example/tests/test_example.py`:

```python
from packages.example import run


def test_run() -> None:
    assert run("x") == "x"
```

The `tests/__init__.py` file is required: without it, the test directory is
not a package and the `protected`/`forbidden` patterns cannot see it. Keep
`_lib` and `tests` as the only conventional private folders; the contracts
name them explicitly.

A Python package may expose several small root modules (`client.py`,
`server.py`) next to `__init__.py`. Each is an entry point and may import
`_lib`; none should re-export the whole implementation tree.

**Done when:** the example exists, its entry point delegates to `_lib`, and
its test imports only `packages.example`.

## Step 5 - Wire the command

Add a `lint:boundaries` script or Makefile target:

```bash
PYTHONPATH=src lint-imports
```

Use `PYTHONPATH=src` for a `src/` layout; omit it for a root `packages/`
layout. If the project already installs itself editable, `lint-imports` also
works without the variable, but the explicit form is predictable in CI.

Fold the target into the command that already runs lint or CI. If there is no
umbrella command, add it and tell the user to call it. Do not replace the
existing test or typecheck targets.

**Done when:** `lint-imports` runs as part of the same gate as the repository's
normal checks.

## Step 6 - Prove the contracts bite

Do this in order and revert each temporary violation:

1. **Clean pass**: `PYTHONPATH=src lint-imports` reports all contracts kept,
   and the project's test command runs the example test (for example,
   `PYTHONPATH=src pytest src/packages/example/tests`).
2. **Tests cannot deep-import**: change the test's import to
   `from packages.example._lib.impl import run`. Run `lint-imports`; the
   `tests never import implementation` contract must break. Revert; it must
   pass again.
3. **Outsiders cannot deep-import**: create a temporary sibling package at
   `<packages-root>/other/__init__.py` that imports
   `packages.example._lib.impl`. Run `lint-imports`; the
   `example internals are private` contract must break. Remove the temporary
   import; it must pass again. Keep the empty temporary package for the next
   step.
4. **Cycles fail**: make the two entry points import each other, for example
   `packages.example` imports `packages.other` and `packages.other` imports
   `packages.example`. Run `lint-imports`; `no package cycles` must break.
   Revert; it must pass again. Remove the temporary package if it was only for
   the proof.

**Done when:** you have observed a pass, a failure on a deliberate deep
import, and a pass after reverting. If a contract cannot fail, fix the config
before finishing.

## Step 7 - Document the convention

Write `<packages-root>/README.md` (next to the packages it governs) covering:

- the layout: `__init__.py` and public root modules are entry points, `_lib/`
  is implementation, `tests/` is the package's own test tree;
- the import rule: import only `packages.<name>` (or another package's public
  root module); never import `packages.<name>._lib` from outside;
- tests import only the package's entry point, never `_lib`;
- the command: `PYTHONPATH=src lint-imports` (adjust for the layout);
- the no-barrel rule: several small entry modules are fine, one giant
  re-export is not.

Then add a one-line pointer from the repository's `CLAUDE.md` if present, else
`AGENTS.md` (create `AGENTS.md` if neither exists), for example:

```markdown
Python packages are deep modules: see
[src/packages/README.md](./src/packages/README.md) before adding or importing
one.
```

**Done when:** the packages-root README exists and the agent-instructions file
links to it.

## Notes

- Import-linter follows **indirect** imports for `forbidden` contracts. That
  is why `allow_indirect_imports = true` is not optional here: tests reach the
  public entry point, which reaches `_lib`, and that is the intended path.
- `protected` checks direct imports; `forbidden` checks direct and indirect
  unless `allow_indirect_imports` is set.
- Wildcards operate on module names: `*` matches one name, `**` includes
  subpackages. A package named `example_extra` does not match `example`.
- Keep the four rule names stable. They are the contract names a failing gate
  prints, and the proof steps refer to them.
