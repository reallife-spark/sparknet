## What changed

<!-- One logical change. Say what and why; link the PLAN step if there is one. -->

## How it was verified

<!-- The gates you actually ran, and what they printed. The local gate is
     authoritative; CI only mirrors it. -->

- [ ] `make ci CI_QUICK=1` (fast pass) — or `make ci` for the full run
- [ ] `make test-all` when a suite beyond the fast pass is relevant
- [ ] `make contract-test` when `contracts/` or `shared/` is touched

## Cross-role check

- [ ] If this changes anything a role depends on, `contracts/` **and both
      roles** were edited in this same change (they are atomic), and
      `make contract-test` passes.

## Could not verify

<!-- A DoD that needs a live GitHub runner or real hardware is a first-class
     answer here, not a failure. Name what is unverified and why. -->

## Checklist

- [ ] No secret material or plausible placeholder is added; `make keys-check`
      passes (see `../SECURITY.md`).
- [ ] New scripts answer `--help` and answering it changes nothing.
- [ ] New documented commands were run at least once; anything derived
      (`contracts/manifest.json`, an SBOM) is regenerated, not hand-edited.
- [ ] Conventions follow `../STYLE_GUIDE.md`; new knowledge goes to its wiki
      category rather than the root.
