# Reflex decision design — a System One sensor beside the agentic layer

Status: **adopted as code through 64F; 64G deferred (2026-10-24).** The local
reflex sensor, decision contract, shared client, Master broker on `4224`, node
`/v1/reflex/` surface, RAG pilot and local-only live pilot are implemented and
tested. The hosted cloud backend was removed outright in Step 65, and no mode
holds a credential. `reflex-consult` and peer broker access, the goSpark router
client, Open WebUI filter, opencode tool-guard plugin, groundedness pass and MCP
tool remain 64G work. New work gets its own step, not a renumbered 64.

This is the fabric-root sibling of `CLUSTER_INFERENCE_DESIGN.md` (Step 17),
`COMPUTE_CAPABILITY_DESIGN.md` (Step 24) and `CLUSTER_JOB_REALIZATION_DESIGN.md`
(Step 61). Those specify the reasoning/data plane. This one specifies the
**fast-decision plane** that sits beside it.

## 1. Why a reflex layer

The agentic layer is a System Two: it reads, plans, calls tools and generates
prose. That is the right tool for an open-ended task and the wrong tool for a
question a competent person answers in a few seconds: is this chunk relevant, is
this tool call risky, does this paragraph cite its source, which queue should
this prompt go to.

A System One sensor is built for exactly that second class. It takes a state and
typed questions and returns typed answers with probabilities; it does not
generate text. That is the whole reason it can be a **sensor** in a control loop
rather than another prompt to parse.

The four candidate touchpoints, in the order this note treats them:

1. **RAG relevance** — filter/rerank retrieved chunks before they reach a
   prompt.
2. **Input screening and intent routing** — classify a request and choose a
   lane.
3. **Tool-call safety** — flag a tool invocation for confirmation.
4. **Groundedness** — check a generated answer against its evidence.

A fifth, optional surface is an agent-callable decision tool: the agent stops
and asks a typed question mid-task.

## 2. The invariant: a sensor, never an authority

Sparknet's authority model is key possession, not a model's opinion. A
probabilistic classifier that could grant, sign, revoke or apply a change would
be a privilege-escalation surface, and prompt-injected state could steer it.

Therefore, for every consumer of this design:

- Reflex output may **rank, annotate, route or flag**.
- It may **never** sign, verify, grant or revoke a capability, approve a
  `guard-apply`, or widen a permission.
- It may only **tighten**: `allow -> confirm/deny` is permitted; `deny -> allow`
  is not.
- It **abstains** on timeout, low confidence, low margin, API error, unknown
  model, or exhausted budget. The caller then keeps its current deterministic
  behavior.
- Its output is **untrusted input** for logs and provenance: hash the request,
  record the model and verdict, never treat the decision as evidence.
- The guard, the signer and the registry never consult it.

If this invariant is not enforced in code, the most attractive touchpoint (tool
safety) is also the one that turns a classifier into a bypass.

## 3. The answer primitives, and what they force

The question types are the contract's own. They were originally shaped by a
hosted System One API that this design no longer calls; the primitives outlived
the vendor because they are the useful part, and they are now pinned by
`contracts/reflex-schema.json` rather than by anyone's documentation.

- Request: `{ "state": <text|object|array>, "model": <exact tag>,
  "questions": { <id>: <question> } }`
- Response: `{ "model", "answers": { <id>: <answer> }, "usage": {...} }`
- Primitives:
  - **Choice**: `choice`, full `probabilities`, `confidence`.
  - **Score**: `score`, `legend`, `probabilities`, `confidence`.
  - **Noul**: `noul` in `[0, 1]` and **no confidence field**.
- Every backend is local: a reranker, the node's own LLM on loopback, or rules.
  There are no hosted weights and no endpoint outside the fabric, so there is no
  credential to hold, no egress to permit, and no vendor's availability to
  become the fabric's availability.

Consequences encoded in the design:

1. **Ask atomic questions.** One judgment per question; combine results in code.
   It matches the fabric's one-concern style, and a local backend answers an
   atomic question cheaply enough that asking several is not a cost decision.
2. **Noul needs a different abstain rule.** Threshold on `p` and on
   `abs(p - 0.5)`; Choice/Score use `confidence` and the top-two margin.
3. **Pin an exact model tag.** Record the `model` the response actually names;
   a mismatch is `model_drift`, not a silent new behavior. A moving `latest`
   alias is refused, because the thing that answered yesterday has to be
   provably the thing that answers today.
4. **Do not hard-code model numbers in prose.** Context limits, price and
   latency belong in the policy file and the evaluation report, where they can
   be updated without editing this document.

## 4. Topology: local-only, with one shared sensor

A peer's overlay admits exactly one address, the Master edge
(`contracts/overlay.json:14`), and the peer charter states the same rule
(`peer-node/AGENTS.md:43`). Nothing in this design needs to leave the fabric, so
nothing does: the backend vocabulary in `contracts/reflex-schema.json` has no
member that could, which is a stronger guarantee than a flag defaulting to off.

```
opencode / goSpark / Open WebUI / chroma CLI
        |  loopback + the existing Bearer grant
        v
peer dispatch bridge   /v1/reflex/*            (127.0.0.1:4096)
        |
        +-- mode=local   -> local reranker / local LLM   DEFAULT, never leaves
        +-- mode=broker  -> 10.100.0.1:4224             opt-in, large tasks
                                  |
                                  v
                     Master decision broker            (Master only)
                     local backend, redacts, budgets,
                     audits hashes — and stops there
```

Three modes, settable per question class:

| Mode | Behavior |
|---|---|
| `off` | no reflex call; existing behavior |
| `local` | the node's own reranker and/or local LLM; no network |
| `broker` | the Master's decision endpoint; also local — it adds one budget, one redaction point and one audit trail, and still never leaves the fabric |
| `auto` | local for small/interactive work; broker for configured massive-task classes or state above a token threshold |

**Default: `local` + `shadow`.** The reflex layer runs on the node (or on the
Master for broker traffic), makes **no call outside the fabric in any mode**, and
does not change an answer until the pilot is measured.
`SPARKNET_REFLEX_BACKEND=local` is the shipped posture, and there is no egress
flag to set because there is no egress path to guard. The broker is opt-in for
the "unified AI for massive tasks" workload — batch/corpus classification,
cross-node synthesis, large-state judgments — not for every interactive turn.

Why keep a broker at all, if it answers locally too: it is the one place a
sibling can ask for a judgment instead of running its own, so the fabric has a
single budget, a single redaction point and a single audit trail to review. This
design once justified the port as the only holder of a cloud credential; that
justification is gone, and the one that replaces it — central audit and budget —
is why 4224 stays in `contracts/ports.json`.

Why not a new node daemon: the dispatch bridge already owns the local surface,
already has the grant check and the loopback-only route class
(`peer-node/services/sparknet-dispatch-bridge.py:73`, `:1277`, `:1287`). A route
is cheaper than a second listener and cannot drift from the bridge's policy.

## 5. The decision contract

One shared module, `shared/sparknet-reflex.py`, with a frozen filename and
golden vectors, follows the `shared/sparknet-authz.py` discipline: one
implementation, loaded by path, canonical bytes pinned by a test.

```
Request   {schema_version, question_class, state, questions, model,
           policy_version, node_id, request_id}
Question  choice | score | noul        (the contract's own vocabulary)
Answer    choice | score | noul
Decision  {verdict: accept|reject|abstain, confidence, backend, model,
           usage, latency_ms, cached, state_digest, model_drift}
```

Non-negotiable semantics:

- **Abstain is first-class**, not an error path bolted on. Every consumer names
  its fallback; the default is "keep current behavior".
- **Canonical bytes** for audit and replay (sorted keys, fixed float
  formatting); a golden-vector test pins them.
- **Cache key** = hash(state) + hash(questions) + exact model + policy version.
  Never reuse a decision across models or policies.
- **Backends**: `broker`, `local-rerank`, `local-llm`, `rules`, `null`. Tests use
  fakes; `local-rerank`, `local-llm`, `rules` and `null` never leave loopback, and
  `broker` leaves the node but not the fabric. None of them can reach the internet,
  which is a property of the vocabulary rather than of a setting.
- **No authority fields.** The schema rejects `capability`, `grant`, `signature`,
  `approve` and `apply`.
- **Budgets**: per-node/day and global/day, with a hard `abstain` when exhausted;
  a config kill switch.

Question classes and their consumers:

| Class | Type | Consumer | Default mode |
|---|---|---|---|
| `rag.relevance` | Noul per chunk | Chroma query / Open WebUI retrieval | local + shadow |
| `intent.route` | Choice | goSpark `Router.Decide` | off |
| `input.injection` | Noul | bridge pre-flight | off |
| `tool.risk` | Choice/Score | opencode tool hook | off |
| `output.grounded` | Noul per claim | bridge post-generation | off |

## 6. Integration seams

### 6.1 RAG relevance — the first pilot

Current query path: `scripts/sparknet-chroma.py:631` (`cmd_query`) opens the
collection and calls `collection.query(query_texts=[query], n_results=top_k)`
at `:653`. The corpus policy is one allow-list with two scopes
(`scripts/sparknet-rag-corpus.py:84`); the fabric scope is 28 structural files /
242 chunks and contains no personal material (Step 63).

Design:

1. Chroma returns `top_k` candidates (default 50).
2. The local reranker (`bge-reranker-v2-m3`, already in the node stack) cuts to
   about 20. This is the default, offline path.
3. With `mode=broker`, the Master's broker scores each remaining chunk as a Noul:
   "is this chunk
   sufficient to answer the query?" Batch 10–20 chunks per call; cache.
4. Keep the top `reflex_top_k` above a probability threshold. On abstain, error
   or budget exhaustion, return the reranker order unchanged and mark the result
   `reflex=abstain`.
5. Start in `shadow`: compute both orders, return the existing one, log the
   difference. Only `assist` may filter; `enforce` is a later, measured step.

The first pilot is the **fabric scope only**. A node's own vault is opt-in and
requires the data-governance decision in §7. The live Open WebUI filter is a
later phase; the CLI path is testable now.

**Pilot result (Step 64E, 2026-10-23).** 14 fabric golden queries, top-k 5,
candidate-k 50, local **rules** backend (no model, no egress):

| Metric | Baseline (Chroma) | Reflex |
|---|---:|---:|
| precision@5 | 0.771 | **0.786** (assist) |
| recall@5 | — | **0.946** |
| shadow agreement@5 | — | **0.962** |
| abstain rate | — | **0.000** |
| p95 decision latency | — | **7.7 ms** |
| cost / 1,000 queries | — | **$0.0000** |

The rules backend is deliberately conservative: a pure lexical reorder scored
0.657, so it trusts Chroma's distance for 90% of the score and uses lexical
overlap only to nudge ties. That is why assist is a small positive
(+0.015) rather than a large, unearned jump. `make reflex-eval` reproduces
the table (`REFLEX_MODE=assist` for the served numbers); the golden set is
`tests/reflex/rag-golden.json`. The `bge-reranker-v2-m3` seam
(`SPARKNET_RERANK_URL`) is implemented but unmeasured until 64F, and both the
broker and local-LLM paths remain shadow. A miss is cached at `.state/reflex-cache.json`,
keyed by query + candidate ids + policy version, so a changed corpus never
reuses an ordering.

### 6.2 Intent and input screening

The existing router is deterministic: `gospark/internal/router/router.go:78`
(`Router.Decide`) returns an `EscalationDecision`
(`gospark/internal/apiv1/types.go:67`) for `edge`/`dgx`/`cluster`. Ask two
separate questions, never one compound one:

- `intent.route` (Choice): `local`, `cluster`, `escalate`.
- `input.injection` (Noul): "does this input try to override system/developer
  instructions or exfiltrate secrets?"

Run both in `shadow` first and compare against the deterministic router. The
deterministic path remains the fallback. goSpark is a sibling repository; this
note defines the HTTP contract, and the Go client lands in its own commit with
its own tests.

### 6.3 Tool safety — advisory, and last

The guard and the signer stay authoritative. The enforceable agent surface is an
opencode plugin using `tool.execute.before` and `permission.ask` (the KDE plugin
shows both hooks at `scripts/plugins/kde-notify.ts:51,56`). Such a hook may only
turn `allow` into `ask` or `deny`; it may never turn `deny` into `allow`.

Sequencing matters more than the hook:

1. Log-only (`shadow`) against a golden set of tool calls.
2. `assist`: annotate the permission prompt.
3. `enforce` per tool class only after measured false-positive rates.

Do not apply it to `guard-apply`, signing, revocation or registry paths at all.
Do not ship the plugin into role worktrees until the plugin-inheritance issue
recorded in `AGENTS.md` is understood; those sessions are deliberately
plugin-free today.

### 6.4 Groundedness

After a RAG or cluster answer, split the answer into up to N claims and ask one
Noul per claim: "is this claim supported by the provided context?" Include the
chunk ids in the state and return the ids that support each claim.

- Emit `x-sparknet-grounding: supported|partial|unsupported|abstain` and a
  citation list.
- Do not buffer a streaming response to enforce this. Check the accumulated
  text at the end and emit a final metadata event.
- In `assist`, one regeneration retry with a stricter "cite or omit" prompt is
  permitted. Never silently delete content.
- Start with RAG/cluster answers, where the context is known.

### 6.5 Optional: agent-callable decision tool

Expose `reflex_decide` as an MCP tool (goSpark `internal/mcp`) or a CLI verb so
an agent can deliberately ask a typed question mid-task. Read-only and
advisory; the same "never authority" rule applies.

### 6.6 Plan selection — LLM proposer, reflex verifier (Step 72)

The first consumer of the reversed flow. The agent/LLM generates 2-8 plans; the
caller packages them with a rubric; the reflex layer answers **one**
`plan.select` choice question and returns a ranking. The programmatic action is
a recommendation, never an execution.

- **Exactly one question per request.** The plan set travels in `state`; the
  question criteria are the plan ids. A batch caller issues one request per
  question and correlates by `request_id`.
- **The decision carries the typed answer** for choice/score decisions: choice,
  probabilities and confidence. Abstains carry no answer; the verifier may still
  show a ranking from a captured answer, explicitly marked `advisory`.
- **The distribution is the signal, not self-reported confidence.** The policy
  (`plan-select-v1`) uses the top probability and top-two margin. The reported
  confidence is floored at the top probability because small models copy a
  template zero.
- **Hard constraints are deterministic.** A `forbid` term list is applied to
  the chosen plan's title and body after ranking. A violating plan is an abstain
  (`constraint-violation`) even if the model ranked it first. This is the
  caller's policy, not the LLM's judgment.
- **Sparse answers are handled conservatively.** A sparse distribution is
  accepted only when it names the chosen plan and its probabilities already sum
  to one; omitted plans become zero. A truncated distribution is refused.
- **Measurement (2026-10-29).** 12 golden cases, local `sparknet-reflex:v1`
  (a copy of qwen2.5-3b) on the LAN Ollama endpoint, no egress: top-1 agreement
  **0.833** (10/12), coverage **0.833**, abstain **0.167**, ECE **0.000**,
  false accepts **0**, p95 **3497 ms**, cost **$0**. The `no-kubernetes` case
  abstained correctly; `groundedness-policy` abstained (a miss). An explicit
  `none` option was removed from the model's option set after it acted as an
  attractor; abstention is now the policy's decision over the distribution.
  The LLM remains advisory and no class moves to assist on this probe alone.

## 7. Data governance and threat model

### Data classes

| Class | Examples | May leave the node? |
|---|---|---|
| structural | contracts, charters, design docs, allow-listed fabric corpus | yes, to the Master broker |
| node-local | a node's own vault pages | only with explicit opt-in and redaction |
| secret | keys, tokens, `.env`, PEM, credentials | never |
| runtime | sessions, `_raw`, `.state`, logs | never |

The client enforces the allow-list and the size cap; the broker re-checks both
(defense in depth). A payload that contains an excluded path or a secret pattern
is refused before it leaves the process. The fabric pilot asserts the payload is
a subset of `plan_index("fabric")`.

### Audit

Append one JSON line per decision to `/mnt/log/sparknet-reflex.jsonl`:
timestamp, class, backend, model returned, usage, latency, verdict, cache hit,
request digest. Never the state, never the API key, never a raw answer.

### Threats

| Threat | Control |
|---|---|
| Prompt injection flips a decision | reflex never authority; tighten-only; abstain; no single-Noul security boundary |
| Model version changes behavior | exact tag; returned-model check; `model_drift` abstain |
| Secret exfiltration to a third party | local-first default; allow-list + redaction on both sides before any optional egress; no secret class |
| Denial of wallet | local default (zero marginal cost); per-node/global budgets; cache; circuit breaker; kill switch |
| Latency stalls the agent | local default; short timeout; broker only for batch/large tasks |
| Master outage | local fallback; no dependency for correctness |
| Key leakage | there is no credential to leak: the cloud leg was removed rather than disabled, so no mode holds a key. The unit still runs dedicated, with no env dump, and the secret scan still runs |
| Source-address spoofing | overlay-only bind + existing AllowedIPs discipline; later a signed/capability check |
| Vendor lock-in | closed rather than mitigated: no backend in the vocabulary is hosted, so no vendor's availability, pricing or retention terms can become the fabric's |

## 8. Ports, capabilities and contract footprint

| Item | Status in this note |
|---|---|
| `4224` reflex-broker | **implemented**; Master, overlay-only, `binds_to 10.100.0.1`; unit staged, not enabled |
| Node port | **none**; the dispatch bridge already listens on 4096 |
| `contracts/reflex-schema.json` | **implemented**; added in its own cross-role commit |
| `shared/sparknet-reflex.py` | **implemented**; frozen filename, golden vectors |
| `reflex-consult` capability | **deferred (64G)**; needed only when peers get broker access |
| `shared/sparknet-authz.py` | **unchanged**; no authority code in this design |
| Guard / signer / registry | **unchanged**; never consult reflex |

The `reflex-consult` capability, when it lands, is a confidentiality grant:
the holder may send allow-listed node state to the Master broker, which consults
the Master's **local** backend. It belongs in the closed vocabulary as a `peer`
capability and is `sensitive: true`, like `cluster-serve`, because it grants a
cross-node data path rather than a local read. There is no third-party egress:
the cloud leg was removed in Step 65.

## 9. Phases

The plan cursor opens at Step 64. Each phase is adopted by its own commit.

### 64A — design record, nothing adopted

- This document, registered in `tests/test_layout.py::EXPECTED_TOP_LEVEL` and
  linked from `index.md`.
- DoD: `git diff --stat contracts/ shared/` empty; `make validate`;
  `make ci CI_QUICK=1` green.

### 64B — decision contract and shared client (cross-role)

- `contracts/reflex-schema.json`, `shared/sparknet-reflex.py`,
  `tests/test_reflex_contract.py`, golden vectors.
- `contracts/README.md` + `index.md` row + `make render` + `make contract-test`.
- DoD: canonical round-trip; fakes only; abstain on timeout/low confidence/
  budget; redaction; audit hashes; no authority fields.

### 64C — Master broker and port 4224

- `master-node/services/sparknet-reflex-broker.py`,
  `master-node/systemd/sparknet-master-reflex.service`,
  `master-node/tests/test_reflex_broker.py`.
- `contracts/ports.json` entry; `master-node/Makefile` unit wiring; a master
  plan step for the port's status reference.
- DoD: overlay-only bind; peer source refused in Phase 1; **no credential** (the
  cloud leg is removed); local backend/model selection; timeout -> abstain;
  budgets; `/healthz` leaks nothing; `units-check` green.

### 64D — node surface

- `/v1/reflex/` added to `PLAIN_PREFIXES` and `LOCAL_ONLY_PREFIXES` in the
  dispatch bridge; `vault-openapi.json`; setup-script env; tests.
- DoD: 401 without grant; 403 from overlay; loopback-only; local default;
  broker opt-in; no new published port.

### 64E — RAG pilot (shadow -> assist)

- `scripts/sparknet-chroma.py --reflex`, reranker cascade, cache,
  `make reflex-eval`, golden set.
- DoD: fabric scope only; shadow agreement reported; fail-open on abstain;
  precision@5, recall, abstain rate, p95, cost per 1k; no regression without
  `--reflex`.

### 64F — live pilot (local-only)

- Every backend is local, so the pilot needed no governance approval and no
  credential — and after the cloud leg's removal, nothing could have used one.
  - `make reflex-live-check` — the only gate is broker `/healthz`. It carried two
    more gates while an egress backend existed; they were removed with it,
    because a gate nothing can trip is not a control, it is decoration.
  - `REFLEX_LIVE=1 make reflex-eval` — scores up to `--live-candidates` fabric
    chunks per golden query through the Master broker, fail-open on any
    transport/shape error.
  - `make reflex-live-query QUERY="…"` — one real broker-backed fabric query.
- State: **executed 2026-10-23; measurements accepted by the operator
  2026-10-24, which closed Step 64.** A loopback broker (`127.0.0.1:4224`, local
  backend) was paired with a LAN Ollama OpenAI endpoint at
  `192.168.178.21:11434`; the local LLM tag is `sparknet-reflex:v1` (a copy of
  `qwen2.5-3b-32k`). The live CLI surface is the eval harness for now;
  `chroma-query --backend broker` is a later convenience, not a 64F requirement.
- DoD: measured accuracy/calibration/cost recorded; `DoD: confirm: user` —
  **confirmed 2026-10-24**.

**Live pilot result (Step 64F, 2026-10-23).** 14 fabric golden queries,
candidate-k 50, top-k 5, loopback broker with the `local-rerank` backend (no
egress, no credential):

| Metric | Baseline (Chroma) | Live reflex |
|---|---:|---:|
| precision@5 (shadow) | 0.771 | 0.757 (candidate signal) |
| precision@5 (assist) | 0.771 | **0.757** (served) |
| recall@5 | — | **0.946** (shadow) / **1.000** (assist) |
| shadow agreement@5 | — | **0.817** |
| abstain rate | — | **0.000** |
| p95 decision latency | — | **115.7 ms** (one outlier; median ~44 ms) |
| cost / 1,000 queries | — | **$0.0000** |

A direct `tool.risk` Noul probe through the local LLM returned **accept 0.80**
in **1.23 s**. The important negative result is structural: the broker receives
**one query+chunk per call**, so its local reranker has no candidate distances
and can only use lexical overlap. It therefore cannot reproduce the
distance-aware batch rerank behind 64E's 0.786; serving it in assist would
regress precision by 0.014. The in-process chroma reranker keeps **assist**;
the broker and local-LLM paths stay **shadow**.

### 64G — later, each its own step

1. `reflex-consult` + peer broker access (contract + both roles).
2. goSpark router client, shadow routing.
3. Open WebUI retrieval filter.
4. opencode tool-guard plugin, tighten-only.
5. Groundedness post-processing.
6. Agent-callable MCP tool.

Plan selection landed as **Step 72** (the advisory CLI + calibration harness);
the legs above remain separate steps. The Step 72 measurement is in §6.6.

## 10. Evaluation

Every question class gets a small, synthetic golden set committed under
`tests/reflex/golden/`:

- `rag.relevance`: (query, chunk, 0–3) triples from the fabric corpus.
- `intent.route`: prompts labelled `local`/`cluster`/`escalate`.
- `input.injection`: benign and adversarial prompts.
- `tool.risk`: tool-call fixtures labelled `allow`/`confirm`/`deny`.
- `output.grounded`: (context, claim, supported) triples.

Metrics: accuracy/macro-F1, abstain rate, calibration (ECE), p50/p95 latency,
cost per 1,000 decisions, and agreement with the deterministic baseline. A
threshold change is a policy-version change, not a code edit.

Gates: `make reflex-eval` is offline by default (rules/fake backend); the live
harness runs against the local broker backend with `REFLEX_LIVE=1` and needs
nothing but a reachable broker, because no backend can leave the fabric.
No class moves from `shadow` to `assist` until its golden set and the operator
review agree.

## 11. Open items for the implementation phase

1. Which local model endpoint peers should standardise on (vLLM/Ollama/Open
   WebUI) and its default `SPARKNET_REFLEX_LOCAL_MODEL`.
2. The default local RAG backend: `local-rerank` (shipped in 64E) or `rules`.
3. Whether the Phase 1 broker accepts only the Master's own bridge or also a
   same-host operator CLI.
4. The master-plan step number the `4224` status string will reference.
5. Whether the `SPARKNET_REFLEX_*` knobs enter `sparknet-node-setup.sh` in 64D
   or stay manual for the pilot.

The former item 2 — the exact cloud model tag, the vendor's data-retention terms
and who provisions the Master's 0600 key — is **closed rather than answered**:
the cloud leg was removed, so there is no tag to pin, no retention terms to
negotiate and no key to provision. It is recorded here because "we decided not
to need this" and "we never decided" age very differently.

## 12. References

- `contracts/overlay.json:14` — the one-address peer `AllowedIPs` rule.
- `peer-node/AGENTS.md:43` — peer egress is restricted to the Master.
- `peer-node/services/sparknet-dispatch-bridge.py:73,1277,1287` — local route
  class, source policy, grant check.
- `scripts/sparknet-chroma.py:631,653` — the current query path.
- `scripts/sparknet-rag-corpus.py:84` — the one policy, two allow-lists.
- `gospark/internal/router/router.go:78` — the deterministic routing seam.
- `gospark/internal/apiv1/types.go:67` — `EscalationDecision`.
- `scripts/plugins/kde-notify.ts:51,56` — `tool.execute.before`/`permission.ask`
  hook precedent.
- `master-node/systemd/sparknet-master-signer.service` — the dedicated-unit,
  filesystem-isolation precedent for the broker.
- `CLUSTER_JOB_REALIZATION_DESIGN.md` — the design-only pattern and the
  vector-substrate context.
- The hosted System One API this design was first written against (read
  2026-10-23) is no longer called and is deliberately not named here; the answer
  primitives it contributed are pinned by `contracts/reflex-schema.json` instead,
  so nothing in this design depends on that documentation staying reachable.
