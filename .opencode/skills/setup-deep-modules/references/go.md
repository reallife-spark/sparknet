# Go track

Read [`../SKILL.md`](../SKILL.md) first. This is the Go procedure behind the
four rules. Follow it end to end, including the proof.

## Step 1 - Confirm the module and packages root

```bash
go list -m
```

If that fails, this is not a Go module; stop and ask. Otherwise:

- If `internal/` already contains package directories, use `internal/` as the
  packages root.
- Else if `pkg/` contains package directories, use `pkg/`.
- Else create `internal/`.
- If packages already live directly at the repository root, use `.` as the
  packages root and keep the same one-tier shape.
- If an obvious third convention exists, confirm it instead of creating a
  second one.

The packages root is flat: packages are its immediate children. A package's
private tree may nest as deeply as needed.

Check for an existing `.go-arch-lint.yml`; if present, merge into it rather
than replacing it.

**Done when:** the module path and packages root are known and the existing
config status is known.

## Step 2 - Create the copy-me package

Use `<module>`, `<root>` and `<name>` as placeholders. For example:
`example.com/acme/app`, `internal`, `example`.

```bash
MODULE="$(go list -m)"
ROOT=internal
NAME=example
mkdir -p "$ROOT/$NAME/internal/impl"
```

Write `<root>/<name>/<name>.go` as a thin entry point that delegates to the
private implementation:

```go
// Package example is the only public entry point for the example module.
package example

import "example.com/acme/app/internal/example/internal/impl"

// Run performs the module's work.
func Run(input string) (string, error) {
	return impl.Run(input)
}
```

Replace the import path with `<module>/<root>/<name>/internal/impl`. If
`<root>` is `.`, omit it: `<module>/<name>/internal/impl`.

Write `<root>/<name>/internal/impl/impl.go`:

```go
package impl

// Run is implementation detail: outside code reaches it through example.Run.
func Run(input string) (string, error) {
	return input, nil
}
```

Write `<root>/<name>/<name>_test.go` as an **external** test package:

```go
package example_test

import (
	"testing"

	"example.com/acme/app/internal/example"
)

func TestRun(t *testing.T) {
	got, err := example.Run("x")
	if err != nil {
		t.Fatal(err)
	}
	if got != "x" {
		t.Fatalf("got %q, want %q", got, "x")
	}
}
```

The `_test` suffix on the package name is the convention that keeps the test
on the public side of the boundary. A test in `package example` is a white-box
test and is rejected by the check in Step 3.

**Done when:** the entry package exposes behaviour, the implementation is
under `internal/`, and the test imports only the entry package.

## Step 3 - Wire the compiler and black-box test checks

The Go compiler enforces two rules with no configuration:

- `<root>/<name>/internal/...` is importable only by code rooted at
  `<root>/<name>`, so other packages cannot deep-import it.
- Go rejects import cycles.

Add `scripts/check-black-box-tests.sh` to enforce the test convention:

```sh
#!/bin/sh
set -eu

root="${1:-internal}"
pattern="./..."
[ "$root" != "." ] && pattern="./$root/..."

bad=$(go list -f '{{if .TestGoFiles}}{{.ImportPath}}: {{join .TestGoFiles ", "}}{{end}}' "$pattern")
if [ -n "$bad" ]; then
	printf '%s\n' "white-box tests found; use package <name>_test:" "$bad" >&2
	exit 1
fi
```

Make it executable and run `go build ./...`, `go test ./...` and the script
with the packages root as its argument.

The script is scoped to the packages root, so legacy white-box tests elsewhere
are not a day-one blocker. If it finds white-box tests inside the root, do not
delete the script to get a green run: convert them to the external package, or
report them and land the script once they are converted.

**Done when:** `go build ./...`, `go test ./...` and the black-box test check
pass on the clean tree.

## Step 4 - Install and configure go-arch-lint

The compiler owns the deep-module boundary. `go-arch-lint` is the optional
layering gate: it lets the repository declare which packages may depend on
which, without weakening the compiler rule.

Install a pinned version (v1.19.1 requires Go 1.25 or newer):

```bash
go install github.com/fe3dback/go-arch-lint@v1.19.1
```

`go install` writes to `$(go env GOPATH)/bin`; make sure that directory is on
PATH in CI, or use `go run github.com/fe3dback/go-arch-lint@v1.19.1 check`
instead.

Copy [`go-arch-lint.yml`](go-arch-lint.yml) to the repository root as
`.go-arch-lint.yml` and set `workdir` to the packages root. The starter lists
one component per immediate package directory under that root. Add every
existing package; a file that is not attached to a component makes
`go-arch-lint check` fail.

For a packages root with an existing set of directories, generate the
component list from the real directories. The loop below lists every directory;
skip any that contain no Go files:

```bash
for dir in "$ROOT"/*/; do
	name=$(basename "$dir")
	printf '  %s: { in: %s/** }\n' "$name" "$name"
done
```

Every component starts with `anyProjectDeps: true` so the first run is green.
Tighten one component to `mayDependOn` only when the repository has decided
its layering. A component that should use its own private tree must include
itself in `mayDependOn`, for example `example: { mayDependOn: [example] }`;
otherwise the linter treats its own subpackages as forbidden imports.

Run:

```bash
go-arch-lint check
```

If it reports unattached files, add the missing components. If it reports a
real layering violation, fix it or record the debt; do not delete the
component.

**Done when:** `.go-arch-lint.yml` exists, every package under the packages
root is attached to a component, and `go-arch-lint check` passes.

## Step 5 - Wire the commands

Add a `boundaries` target to the Makefile (or the equivalent CI step):

```make
boundaries:
	go build ./...
	./scripts/check-black-box-tests.sh internal
	go-arch-lint check
```

Fold `boundaries` into the command that already runs lint or CI. If there is
no umbrella command, add the target and tell the user to call it. Do not
replace the repository's existing test or build targets.

**Done when:** the boundary commands run as part of the same gate as the
repository's normal checks.

## Step 6 - Prove the gates bite

Do this in order and revert each temporary violation:

1. **Clean pass**: `go build ./...`, `go test ./...`, the black-box test
   script and `go-arch-lint check` all pass.
2. **Compiler boundary**: add a file in a package outside the
   `<root>/<name>/` tree that imports
   `<module>/<root>/<name>/internal/impl`. Run `go build ./...`; it must fail
   with `use of internal package ... not allowed`. Remove the file; the build
   must pass again.
3. **Test convention**: add a white-box `_test.go` file with
   `package <name>` (no imports needed). Run the black-box test script with the
   packages root; it must fail and name the file. Remove it; the script must
   pass again.
4. **Layering** (only if there is more than one component): replace one
   component's `anyProjectDeps: true` with `mayDependOn: [<itself>]`, add a
   temporary import to another component, and run `go-arch-lint check`. It
   must fail. Revert both changes; it must pass again.

**Done when:** you have observed a pass, a failure on a deliberate violation,
and a pass after reverting. If a gate cannot fail, fix it before finishing.

## Step 7 - Document the convention

Write `<root>/README.md` (next to the packages it governs) covering:

- the layout: entry package, `internal/` for implementation, `_test.go` for
  black-box tests;
- the import rule: only the entry package is public; never import another
  package's `internal/`;
- the commands: `go build ./...`, `go test ./...`,
  `./scripts/check-black-box-tests.sh internal`, `go-arch-lint check`;
- the fact that a Go package is one entry point, and that several public
  surfaces are separate packages, not one barrel package.

Then add a one-line pointer from the repository's `CLAUDE.md` if present, else
`AGENTS.md` (create `AGENTS.md` if neither exists), for example:

```markdown
Go packages are deep modules: see [internal/README.md](./internal/README.md)
before adding or importing one.
```

**Done when:** the packages-root README exists and the agent-instructions file
links to it.

## Notes

- `go-arch-lint` v1.19.1 requires Go 1.25+. Pin a version compatible with the
  repository's Go toolchain; do not use `@latest` in CI.
- `excludeFiles` excludes `_test.go` from layering analysis. That is
  deliberate: tests may import another package's entry point. The black-box
  script enforces the external test package name; it does not inspect imports
  inside a test, so a test that imports its own `internal/...` is a review
  failure.
- The starter is permissive on purpose. A gate that fails on day one because
  the repository's existing layering was never declared is not useful; make
  the first run green, then tighten one component at a time.
- If the repository has no Makefile, put the same commands in its CI
  configuration and leave a note in the README.
