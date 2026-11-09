# 0001 — Local markdown issue tracker

## Status

Accepted (2026-11-09).

## Context

The Matt Pocock engineering skills assume an issue tracker. A node may have no
GitHub remote, no network egress and no desire to publish its work items. The
fabric already has a signed peer→Master route and a local-only `.scratch/`
convention for the wiki suite's review queue.

## Decision

Use `.scratch/issues/<id>.md` as the tracker, with the `sparknet-issue/1`
frontmatter defined in `contracts/issue-schema.json`. The file is machine-local
and gitignored. A role workspace pushes its issues to the Master over the signed
`POST /api/v1/issues` route under the peer-held `issue-report` capability; the
root workspace keeps them local.

## Consequences

- No GitHub/GitLab credential or remote is required to track work.
- Issues do not survive a `git clone`; the schema and the docs do, and the
  Master keeps the recorded work items.
- An issue can never become a vault page, a knowledge answer or an authority
  message. It is operational work with a redacted body.
- A future hosted tracker is a superseding ADR, not a silent switch in a skill.
