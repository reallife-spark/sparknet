# shared/

Executable implementations that **both roles** depend on. Deliberately
sparse, and deliberately not duplicated per role.

## `sparknet-authz.py`

The reference implementation of the signed authorization scheme:
canonical identity projection, SHA-256 fingerprinting, Ed25519 signing and
verification, registry evaluation.

**Why there is exactly one copy.** The Master calls `sign`; a peer calls
`verify`. Those two must agree byte-for-byte on the canonical form, or the
Master signs something the peer rejects. If each role carried its own copy,
they could drift — a changed separator, a sorted list, a different set of
identity fields — and the failure would be silent and intermittent: signatures
that verify on the node that produced them and fail everywhere else.

That is a security bug, not a duplication nit. So the algorithm lives here once,
and each role wraps it:

- `master-node/` — signs entries, manages the registry, revokes
- `peer-node/` — verifies entries, evaluates its own authorization posture

Neither role re-implements the algorithm. Neither role may edit this file to
serve a local need; a change belongs in `contracts/` first, with both roles
updated in the same commit.

## Adding to this directory

Only if **both** roles need the same code and any divergence would be a
correctness or security problem. Role-specific logic does not belong here — it
belongs in the role's own `services/`. The test is: if only one role would ever
call it, it is not shared.
## Never copy this into a role

`sparknet-authz.py` stays here, at exactly one path, for both roles. A copy in
`peer-node/services/` or a future `master-node/services/` is how the two roles
silently stop agreeing: each verifies against its own version, and the day they
differ — a changed canonical form, a reordered field — every signature
verification fails at once, on every node, with no obvious cause.

So it is a rule, not a preference, and `tests/test_contracts.py`
(`test_only_one_authz_implementation_exists`) fails the build if a second copy
appears anywhere in the tree. A role that needs different behaviour wants a
contract change in `contracts/`, not a patched local variant.

This also means a role subvault on its own is **not** a working deployment: it
cannot verify anything, because it does not have this file. `make bundle`
assembles the role together with `shared/` and `contracts/`.
