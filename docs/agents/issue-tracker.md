# Issue tracker

This repository uses a **local markdown tracker**. The engineering skills read
and write issues here; no GitHub/GitLab remote is required.

## Location and schema

- Root: `.scratch/issues/`
- One issue per file: `.scratch/issues/<id>.md`
- Frontmatter schema: `sparknet-issue/1`, defined normatively in
  `contracts/issue-schema.json`.
- `.scratch/` is machine-local and gitignored. An issue reaches the Master as
  a signed work-item report, never as a commit.

## File shape

```markdown
---
schema: sparknet-issue/1
id: fix-console-token
title: Console rejects a valid token
status: open
labels: [needs-triage]
reporter: operator
created_at: 2026-11-09T10:00:00Z
updated_at: 2026-11-09T10:00:00Z
source: .
body_sha256: <sha256 of the body>
links:
  - kind: file
    ref: scripts/sparknet-console.py
---

What happened, what was expected, and the smallest useful reproduction.
```

## Lifecycle

`open` → `triaged` → `in-progress` → `blocked`/`done`/`wontfix`.

- Create an issue when the work is real but not yet a plan step.
- Triage before an agent claims it; `ready-for-agent` is the only label that
  means an agent may start.
- Link the plan step or commit in `links`; do not paste a secret, a vault page
  or a private conversation.
- A resolved issue is closed by moving it to `done` and recording the outcome;
  do not delete the file.

## Triage labels

The five canonical roles are `needs-triage`, `needs-info`, `ready-for-agent`,
`ready-for-human` and `wontfix`. See `triage-labels.md`.

## GitHub mirror

GitHub Issues may carry a **derived mirror** of local work for visibility. The
mirror is not the tracker: `.scratch/issues/` remains canonical under
[ADR-0001](../adr/0001-local-markdown-issue-tracker.md), and an issue that
exists only on GitHub is not triaged work.

- Mirror one local issue at a time with the same title and one canonical label.
- The mirror body ends with `Mirror of .scratch/issues/<id>.md; local is
  canonical.` and carries no private vault page, secret or live host state.
- A triage transition happens locally first; the mirror follows. Never let a
  GitHub edit become the only record of a decision.
- The five labels are created once with `gh label create`; `wontfix` may already
  exist and is updated rather than duplicated.

## Master

The root workspace keeps its issues local. A role workspace pushes its own
`.scratch/issues/` to the Master with its role pusher
(`services/sparknet-issue-push.py` in `peer-node/`). The Master records the
work item under `issue-report` on `POST /api/v1/issues` (8090) and exposes it at
`GET /api/issues`. The Master-local triage CLI is
`master-node/scripts/sparknet-issue-triage.py`; it appends to the triage ledger
and refreshes the derived view, but grants no authority. An issue is
operational work: it is never knowledge, never authority and never an answer
corpus.
