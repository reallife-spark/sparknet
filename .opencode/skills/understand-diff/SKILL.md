---
name: understand-diff
description: Compare two code-understanding graphs and summarize added, removed and changed nodes and edges. Use to review architectural impact after a branch, commit or refactor.
argument-hint: "[old-graph] [new-graph]"
---

# /understand-diff

Compare an old graph with a new one. The output is derived data, not authority.

## Steps

1. Resolve the old graph (default `<project>/.ua/knowledge-graph.json`) and the
   new graph. If only one project is given, build the new graph to a temporary
   path with `/understand`.
2. Run:

   ```sh
   sparknet-understand diff --old "<old>" --new "<new>"
   ```

   or with the Python core, compare node ids and `(source, target, type)` edge
   keys directly.
3. Summarize by category: files added/removed, symbols added/removed, edge types
   gained or lost. Name the highest-impact changes first (public functions,
   endpoints, schemas, cross-layer edges).
4. Offer `/understand-dashboard` for the visual view.

## Boundaries

- A graph diff is not a semantic proof of behaviour change; say what the graph
  shows and what it cannot show.
- Do not overwrite the old graph. Write the new graph to a separate path.
