---
name: Bug report
about: Something in the fabric, a role, a script or the image is wrong
title: ""
labels: ""
assignees: ""
---

## What happened

<!-- What you observed, and what you expected instead. -->

## How to reproduce

```
# the smallest sequence of commands, from the repo root
```

## Where

<!-- The path or command at fault, with line numbers if you have them. -->

## What the gates say

<!-- Output of `make ci CI_QUICK=1`, `make test-all`, or the single failing
     suite — whichever is relevant. Paste the failing lines, not the whole log. -->

## Environment

- Commit or tag:
- Which role/surface: fabric root / `peer-node` / `master-node` / image
- `make -C peer-node help-role` or `make help-role` output, if it differs from
  what the docs claim
