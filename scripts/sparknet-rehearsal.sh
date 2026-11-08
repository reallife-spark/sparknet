#!/usr/bin/env bash
# Step 12 rehearsal: the election-to-escalation arc on this host, in real trees.
#
# Three node trees under /tmp/opencode (move them with SPARKNET_REHEARSAL_DIR)
# are built from a fresh master bundle and driven through the whole arc:
# peer-only boot, the unanimous election ceremony between three real member
# processes, the formed cluster trust root, the isolated signer bound to it on
# the elected node, the registry signed under that root, and the two escalation
# assertions Step 11's DoD (5) and (7) require — no information lost across the
# transition, and the elected master can sign where a still-peer cannot.
#
# Every assertion is a test: a failure makes the run exit nonzero. The dated
# transcript is written to $WORK/rehearsal-<date>.log; re-running from scratch
# starts over at /tmp/opencode.
set -euo pipefail

# Argument handling FIRST — before $WORK is touched, the transcript is
# truncated or output is redirected into it. Without this guard, running the
# script with `--help` executed the entire rehearsal: node trees built,
# transcript truncated, election port bound. Sourced-style invocation passes
# no arguments; the script takes none by design.
usage() {
  cat <<'USAGE'
sparknet-rehearsal.sh — Step 12 election-to-escalation rehearsal (local trees)

Usage:
  scripts/sparknet-rehearsal.sh          run the full rehearsal
  scripts/sparknet-rehearsal.sh --help    print this text and exit

Environment:
  SPARKNET_REHEARSAL_DIR   tree root   (default: /tmp/opencode/rehearsal)
  SPARKNET_ELECTION_PORT   ceremony port (default: 4210)
  SPARKNET_ELECTION_WAIT   max seconds per wait (default: 120)

The run writes a dated transcript under the tree root and starts over from
scratch on every invocation. Nothing outside the tree root is modified.
USAGE
}

case "${1:-}" in
  "") : ;;                                   # no arguments: run the rehearsal
  -h|--help) usage; exit 0 ;;
  *) printf 'sparknet-rehearsal: unexpected argument: %s\n\n' "$1" >&2
     usage >&2; exit 2 ;;
esac

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# All three are overridable so the same rehearsal can run inside the node image
# (scripts/sparknet-election-rehearsal-container.sh): the container supplies its
# own interpreter and its own copy of the ceremony scripts, and may hand in a
# pre-built master bundle instead of running `make bundle`.
PY="${SPARKNET_PYTHON:-$REPO_ROOT/.venv/bin/python}"
ELECTION="${SPARKNET_ELECTION_PY:-$REPO_ROOT/shared/sparknet-election.py}"
SIGNER="${SPARKNET_SIGNER_PY:-$REPO_ROOT/master-node/services/sparknet-signer.py}"
TGZ_OVERRIDE="${SPARKNET_REHEARSAL_TGZ:-}"

WORK="${SPARKNET_REHEARSAL_DIR:-/tmp/opencode/rehearsal}"
CAND="alpha"
NODES=(alpha beta gamma)
PORT="${SPARKNET_ELECTION_PORT:-4210}"
URL="http://127.0.0.1:$PORT"
WAIT="${SPARKNET_ELECTION_WAIT:-120}"

DATE="$(date +%F)"
TRANSCRIPT="$WORK/rehearsal-$DATE.log"
mkdir -p "$WORK"
: > "$TRANSCRIPT"
exec > >(tee -a "$TRANSCRIPT") 2>&1

PASS=0
FAIL=0
step() { printf '\n== %s ==\n' "$*"; }
ok()   { printf '   ok    %s\n' "$*"; PASS=$((PASS+1)); }
bad()  { printf '   FAIL  %s\n' "$*"; FAIL=$((FAIL+1)); }

node() { printf '%s/node-%s' "$WORK" "$1"; }

check() {
  local label="$1"; shift
  if "$@" >/dev/null 2>&1; then ok "$label"; else bad "$label"; fi
}

expect_refuse() {
  local label="$1" needle="$2"; shift 2
  local out
  out="$("$@" 2>&1 || true)"
  if printf '%s' "$out" | grep -qF "$needle"; then
    ok "$label"
  else
    bad "$label (wanted a refusal containing '$needle')"
    printf '%s\n' "$out" | tail -4 | sed 's/^/       /'
  fi
}

jfield() { # jfield <file> <dotted-path> — print the value
  "$PY" -c '
import json, sys
cur = json.load(open(sys.argv[1]))
for part in sys.argv[2].split("."):
    cur = cur[part]
print(cur)
' "$1" "$2"
}

jtest() { # jtest <file> <python-expr> — pass when eval(d) is truthy
  "$PY" -c '
import json, sys
d = json.load(open(sys.argv[1]))
sys.exit(0 if eval(sys.argv[2]) else 1)
' "$1" "$2"
}

EXC_PID=""
SIGNER_PID=""
cleanup() {
  [ -n "$EXC_PID" ] && kill "$EXC_PID" 2>/dev/null || true
  [ -n "$SIGNER_PID" ] && kill "$SIGNER_PID" 2>/dev/null || true
}
trap cleanup EXIT

step "build a fresh node bundle (the master bundle is the whole node)"
if [ -n "$TGZ_OVERRIDE" ]; then
  # Caller (containerised rehearsal) supplies a pre-built master worktree bundle;
  # the repository tree may be mounted read-only.
  [ -f "$TGZ_OVERRIDE" ] || { bad "bundle override not found: $TGZ_OVERRIDE"; exit 1; }
  TGZ="$TGZ_OVERRIDE"
  ok "using supplied bundle $(basename "$TGZ")"
elif make -C "$REPO_ROOT" bundle ROLE=master >/dev/null 2>&1; then
  ok "bundle build"
else
  bad "bundle build"; exit 1
fi
if [ -z "${TGZ:-}" ]; then
  TGZ="$(ls -t "$REPO_ROOT"/dist/sparknet-master-worktree-*.tar.gz | head -1)"
fi
step "extract three node trees from $(basename "$TGZ")"
mkdir -p "$WORK"
for n in "${NODES[@]}"; do
  rm -rf "$WORK/node-$n"
  mkdir -p "$WORK/node-$n"
  mkdir -p "$WORK/node-$n"
  python3 /fabric/scripts/sparknet-safe-extract.py "$TGZ" "$WORK/node-$n"
  if [ -d "$WORK/node-$n/sparknet-peer" ]; then
    cp -a "$WORK/node-$n/sparknet-peer/." "$WORK/node-$n/"
    rm -rf "$WORK/node-$n/sparknet-peer"
  fi
  check "node-$n extracted" test -f "$(node "$n")/master-node/AGENTS.md"
done

step "personalise node identities (distinct node_id, overlay, wireguard key)"
"$PY" - "$WORK" "${NODES[*]}" <<'PY'
import base64, json, sys
work, nodes = sys.argv[1], sys.argv[2].split()
for idx, name in enumerate(nodes):
    nid = f"node-{name}"
    wg = base64.b64encode((b"wg-" + nid.encode()).ljust(32, b"\x00")).decode()
    peer = f"{work}/node-{name}/peer-node/manifests/node-identity.json"
    d = json.load(open(peer))
    d["node_id"], d["wireguard_public_key_b64"], d["overlay_ipv4"] = nid, wg, f"10.100.0.{2 + idx}/32"
    json.dump(d, open(peer, "w"), indent=2, ensure_ascii=False)
    mast = f"{work}/node-{name}/master-node/manifests/master-identity.json"
    d = json.load(open(mast))
    d["node_id"], d["wireguard_public_key_b64"] = nid, wg
    json.dump(d, open(mast, "w"), indent=2, ensure_ascii=False)
PY
for n in "${NODES[@]}"; do
  check "node-$n identity personalised" \
    test "$(jfield "$(node "$n")/peer-node/manifests/node-identity.json" node_id)" = "node-$n"
done

step "cluster keys, minted out of band (never minted by the election)"
for n in "${NODES[@]}"; do
  "$PY" "$ELECTION" keygen --key-dir "$(node "$n")/cluster-keys" >/dev/null
  check "node-$n cluster keypair" test -f "$(node "$n")/cluster-keys/cluster.ed25519"
done
"$PY" - "$WORK" "${NODES[*]}" <<'PY'
import json, sys
work, nodes = sys.argv[1], sys.argv[2].split()
for name in nodes:
    path = f"{work}/node-{name}/master-node/manifests/master-identity.json"
    d = json.load(open(path))
    d["cluster_pubkey_b64"] = open(f"{work}/node-{name}/cluster-keys/cluster.pub.b64").read().strip()
    json.dump(d, open(path, "w"), indent=2, ensure_ascii=False)
PY
ok "master identities name their cluster public keys"

step "membership roster (the three nodes swapping keys, nothing more)"
"$PY" - "$WORK" "${NODES[*]}" <<'PY'
import base64, hashlib, json, sys
work, nodes = sys.argv[1], sys.argv[2].split()
members = []
for idx, name in enumerate(nodes):
    nid = f"node-{name}"
    wg = base64.b64encode((b"wg-" + nid.encode()).ljust(32, b"\x00")).decode()
    members.append({
        "node_id": nid,
        "fingerprint": hashlib.sha256(nid.encode()).hexdigest(),
        "wireguard_pubkey": wg,
        "cluster_pubkey": open(f"{work}/node-{name}/cluster-keys/cluster.pub.b64").read().strip(),
    })
json.dump({"schema_version": "1.0", "election_id": "cluster-election-1",
           "members": members}, open(f"{work}/cluster-members.json", "w"), indent=2)
print(len(members))
PY
check "roster names exactly three distinct nodes" \
  test "$("$PY" -c 'import json,sys; print(len(json.load(open(sys.argv[1]))["members"]))' "$WORK/cluster-members.json")" = 3

step "peer-only mode: every node boots, validates, and claims nothing"
for n in "${NODES[@]}"; do
  bash "$(node "$n")/scripts/sparknet-env-init.sh" "$(node "$n")/peer-node" >/dev/null 2>&1 || true
  bash "$(node "$n")/scripts/sparknet-env-init.sh" "$(node "$n")/master-node" >/dev/null 2>&1 || true
  check "node-$n peer validate (standalone boot)" bash "$(node "$n")/peer-node/scripts/sparknet-validate.sh"
  check "node-$n master identity is a peer" \
    jtest "$(node "$n")/master-node/manifests/master-identity.json" "d['role'] == 'peer'"
  check "node-$n holds no trust root" \
    jtest "$(node "$n")/master-node/manifests/cluster-trust-root.json" "d.get('root') is None"
done

step "snapshot the pre-election trees for the no-loss assertions (DoD 5)"
snapshot() { # snapshot <out.json>
  local out="$1"
  "$PY" - "$WORK" "${NODES[*]}" "$out" <<'PY'
import hashlib, json, sys
from pathlib import Path
work, nodes, out = sys.argv[1], sys.argv[2].split(), sys.argv[3]

def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()

def tree(root, exclude):
    root = Path(root)
    ex = tuple(exclude)
    res = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        if rel.startswith(ex):
            continue
        res.append((rel, sha(p)))
    return res

state = {}
for name in nodes:
    base = f"{work}/node-{name}"
    state[f"{name}:ledger"] = sha(f"{base}/master-node/blockchain/ledger.json")
    for tag, path, keep in (
        ("peer", f"{base}/peer-node/manifests/node-identity.json",
         ("node_id", "wireguard_public_key_b64", "overlay_ipv4", "requested_capabilities")),
        ("master", f"{base}/master-node/manifests/master-identity.json",
         ("node_id", "wireguard_public_key_b64", "overlay_ipv4", "requested_capabilities", "cluster_pubkey_b64")),
    ):
        d = json.load(open(path))
        state[f"{name}:{tag}"] = {k: d[k] for k in keep if k in d}
    state[f"{name}:peer"] = tree(
        f"{base}/peer-node",
        (".state", ".cache", ".env", "manifests/node-identity.json"),
    )
    state[f"{name}:master"] = tree(
        f"{base}/master-node",
        (".state", ".cache", ".env", "blockchain/ledger.json",
         "manifests/master-identity.json", "manifests/cluster-trust-root.json"),
    )
json.dump(state, open(out, "w"), sort_keys=True, indent=2)
PY
  ok "snapshot $out"
}
snapshot "$WORK/before.json"

step "the election: three real member processes against the exchange"
"$PY" - "$URL" /dev/null <<'PY' 2>/dev/null || true
import sys, urllib.request
urllib.request.urlopen(sys.argv[1] + "/election/status", timeout=1)
PY
if [ -n "$EXC_PID" ]; then bad "an exchange is already running"; exit 1; fi
(
  cd "$(node "$CAND")"
  exec "$PY" "$ELECTION" serve --members "$WORK/cluster-members.json" \
      --bind 127.0.0.1 --port "$PORT"
) > "$WORK/exchange.log" 2>&1 &
EXC_PID=$!
up=0
for _ in $(seq 1 100); do
  if "$PY" -c '
import json, sys, urllib.request
urllib.request.urlopen(sys.argv[1] + "/election/status", timeout=1)
' "$URL" >/dev/null 2>&1; then up=1; break; fi
  sleep 0.2
done
if [ "$up" = 1 ]; then ok "exchange listening at $URL"; else bad "exchange never answered"; tail -5 "$WORK/exchange.log"; exit 1; fi

A_LOG="$WORK/ceremony-candidate.log"
B_LOG="$WORK/ceremony-beta.log"
G_LOG="$WORK/ceremony-gamma.log"

SPARKNET_STATE_DIR="$WORK/state-$CAND" \
SPARKNET_KEY_DIR="$(node "$CAND")/cluster-keys" \
SPARKNET_ELECTION_URL="$URL" \
PY="$PY" \
bash "$(node "$CAND")/master-node/scripts/sparknet-election-approve.sh" \
  --expect-master "node-$CAND" --wait-seconds "$WAIT" > "$A_LOG" 2>&1 &
A_PID=$!

SPARKNET_KEY_DIR="$(node beta)/cluster-keys" \
SPARKNET_ELECTION_URL="$URL" \
PY="$PY" \
bash "$(node beta)/peer-node/scripts/sparknet-election-request.sh" \
  --candidate "node-$CAND" --wait-seconds "$WAIT" > "$B_LOG" 2>&1 &
B_PID=$!

SPARKNET_KEY_DIR="$(node gamma)/cluster-keys" \
SPARKNET_ELECTION_URL="$URL" \
PY="$PY" \
bash "$(node gamma)/peer-node/scripts/sparknet-election-request.sh" \
  --candidate "node-$CAND" --wait-seconds "$WAIT" > "$G_LOG" 2>&1 &
G_PID=$!

ceremony_rc=0
for p in "$A_PID" "$B_PID" "$G_PID"; do
  wait "$p" || ceremony_rc=$?
done
if [ "$ceremony_rc" -eq 0 ]; then
  ok "all three ceremonies completed and the root formed"
else
  bad "ceremony failed (rc $ceremony_rc)"
  for f in "$A_LOG" "$B_LOG" "$G_LOG"; do
    printf '   --- %s ---\n' "$(basename "$f")"
    tail -6 "$f" | sed 's/^/     /'
  done
fi
kill "$EXC_PID" 2>/dev/null || true
wait "$EXC_PID" 2>/dev/null || true
EXC_PID=""
ok "exchange shut down"
[ "$ceremony_rc" -eq 0 ] || exit 1

step "the formed root and the role state"
check "elected node's master identity role is master" \
  jtest "$(node "$CAND")/master-node/manifests/master-identity.json" "d['role'] == 'master'"
check "elected node's operational key is held" \
  jtest "$(node "$CAND")/master-node/manifests/master-identity.json" "d['operational_key']['held'] is True"
check "elected node now pins the root in its identity" \
  jtest "$(node "$CAND")/master-node/manifests/master-identity.json" \
    "d['trust_root']['root_id'] == json.load(open('$(node "$CAND")/master-node/manifests/cluster-trust-root.json'))['root_id']"
check "root names node-$CAND as master" \
  jtest "$(node "$CAND")/master-node/manifests/cluster-trust-root.json" "d['root']['master_node_id'] == 'node-$CAND'"
check "root carries three cosignatures" \
  jtest "$(node "$CAND")/master-node/manifests/cluster-trust-root.json" "len(d['root']['signatures']) == 3"
check "root.master_pubkey is the elected node's operational key" \
  test "$(cat "$(node "$CAND")/cluster-keys/operational.pub.b64")" = \
       "$(jfield "$(node "$CAND")/master-node/manifests/cluster-trust-root.json" root.master_pubkey)"
for n in beta gamma; do
  check "node-$n master identity stayed a peer" \
    jtest "$(node "$n")/master-node/manifests/master-identity.json" "d['role'] == 'peer'"
  check "node-$n has no trust_root block" \
    jtest "$(node "$n")/master-node/manifests/master-identity.json" "'trust_root' not in d"
  check "node-$n wrote no trust-root document" \
    jtest "$(node "$n")/master-node/manifests/cluster-trust-root.json" "d.get('root') is None"
done

step "no loss across the transition (DoD 5)"
snapshot "$WORK/after.json"
check "every unchanging file, ledger and identity field survived byte-identically" \
  cmp -s "$WORK/before.json" "$WORK/after.json"

step "the isolated signer, bound to the formed root on the elected node"
"$PY" -c '
import json, sys
doc = json.load(open(sys.argv[1]))
json.dump(doc["root"], open(sys.argv[2], "w"), indent=2, sort_keys=True)
' "$(node "$CAND")/master-node/manifests/cluster-trust-root.json" "$WORK/root.json"
check "bare root extracted for the signer" test -f "$WORK/root.json"
mkdir -p "$WORK/state-$CAND/signer"
SPARKNET_STATE_DIR="$WORK/state-$CAND" \
"$PY" "$SIGNER" --node-id "node-$CAND" \
  --root "$WORK/root.json" \
  --key "$(node "$CAND")/cluster-keys/operational.ed25519" \
  --socket "$WORK/state-$CAND/signer/signer.sock" \
  --ledger "$(node "$CAND")/master-node/blockchain/ledger.json" \
  > "$WORK/signer.log" 2>&1 &
SIGNER_PID=$!
up=0
for _ in $(seq 1 100); do
  if "$PY" -c '
import json, socket, sys
sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
sock.connect(sys.argv[1])
sock.sendall(b"{\"op\": \"pong\"}\n")
sock.recv(4096)
sock.close()
' "$WORK/state-$CAND/signer/signer.sock" 2>/dev/null; then
    up=1; break
  fi
  sleep 0.1
done
if [ "$up" = 1 ]; then ok "signer socket is up"; else bad "signer did not bind"; tail -5 "$WORK/signer.log"; exit 1; fi

"$PY" -c '
import json, socket, sys
sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
sock.connect(sys.argv[1])
sock.sendall(b"{\"op\": \"root-id\"}\n")
out = b""
while b"\n" not in out:
    out += sock.recv(4096)
print(out.decode().strip())
' "$WORK/state-$CAND/signer/signer.sock"
check "signer answers only its pinned root" \
  test "$("$PY" -c '
import json, socket, sys
sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
sock.connect(sys.argv[1])
sock.sendall(b"{\"op\": \"root-id\"}\n")
out = b""
while b"\n" not in out:
    out += sock.recv(4096)
print(json.loads(out.decode())["root_id"])
' "$WORK/state-$CAND/signer/signer.sock")" = "$(jfield "$(node "$CAND")/master-node/manifests/cluster-trust-root.json" root_id)"
check "signer capability set is exactly the one word" \
  test "$("$PY" -c '
import json, socket, sys
sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
sock.connect(sys.argv[1])
sock.sendall(b"{\"op\": \"capabilities\"}\n")
out = b""
while b"\n" not in out:
    out += sock.recv(4096)
print(json.dumps(sorted(json.loads(out.decode())["capabilities"])))
' "$WORK/state-$CAND/signer/signer.sock")" = '["sign"]'

step "the elected master can sign (DoD 7), and a peer verifies by the root"
ROOT_ID="$(jfield "$(node "$CAND")/master-node/manifests/cluster-trust-root.json" root_id)"
RESP="$("$PY" -c '
import json, importlib.util, socket, sys
from datetime import datetime, timedelta, timezone
shared = sys.argv[1]

def load(name, file):
    spec = importlib.util.spec_from_file_location(name, f"{shared}/{file}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod

authz = load("authz", "sparknet-authz.py")
identity = json.load(open(sys.argv[2]))
now = datetime.now(timezone.utc)
entry = {
    "fingerprint": authz.fingerprint(identity),
    "identity": identity,
    "capabilities": sorted(identity.get("requested_capabilities", ["telemetry"])),
    "issued_at": now.isoformat(),
    "expires_at": (now + timedelta(days=365)).isoformat(),
}
payload = json.dumps({
    "op": "sign-registry-entry",
    "root_id": sys.argv[3],
    "entry": entry,
})
sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
sock.connect(sys.argv[4])
sock.sendall(payload.encode() + b"\n")
out = b""
while b"\n" not in out:
    out += sock.recv(4096)
response = json.loads(out.decode())
print(json.dumps(response, sort_keys=True))
' "$REPO_ROOT/shared" "$(node beta)/peer-node/manifests/node-identity.json" "$ROOT_ID" "$WORK/state-$CAND/signer/signer.sock")"
check "signer signed a registry entry for a still-peer" \
  bash -c "grep -qF '\"ok\": true' <<< \"\$0\"" "$RESP"
check "that signature verifies against the root public key" \
  "$PY" -c '
import json, importlib.util, sys
shared = sys.argv[1]
spec = importlib.util.spec_from_file_location("authz", f"{shared}/sparknet-authz.py")
authz = importlib.util.module_from_spec(spec)
sys.modules["authz"] = authz
spec.loader.exec_module(authz)
resp = json.loads(sys.argv[2])
root = json.load(open(sys.argv[3]))
entry = resp["entry"]
unsigned = {k: v for k, v in entry.items() if k != "signature_b64"}
master_pub = authz.public_key_from_b64(root["master_pubkey"])
ok = authz.verify_signature(master_pub, entry["signature_b64"], authz.authorization_message(unsigned))
sys.exit(0 if ok else 1)
' "$REPO_ROOT/shared" "$RESP" "$WORK/root.json"

step "a still-peer cannot sign (the vocabulary granted it nothing)"
expect_refuse "loser node-beta's own operational key is refused by the root" \
  "is not the key this root authorises" \
  env SPARKNET_STATE_DIR="$WORK/state-$CAND" "$PY" "$SIGNER" \
    --node-id "node-$CAND" --root "$WORK/root.json" \
    --key "$(node beta)/cluster-keys/operational.ed25519" \
    --socket "$WORK/state-$CAND/signer/loser-key.sock" \
    --ledger "$(node beta)/master-node/blockchain/ledger.json"
expect_refuse "a node the root does not name is refused" \
  "refusing to sign" \
  env SPARKNET_STATE_DIR="$WORK/state-$CAND" "$PY" "$SIGNER" \
    --node-id node-gamma --root "$WORK/root.json" \
    --key "$(node "$CAND")/cluster-keys/operational.ed25519" \
    --socket "$WORK/state-$CAND/signer/wrong-node.sock" \
    --ledger "$(node gamma)/master-node/blockchain/ledger.json"
cp "$WORK/root.json" "$WORK/root-tampered.json"
"$PY" -c '
import json, sys
d = json.load(open(sys.argv[1]))
d["members"][1]["wireguard_pubkey"] = "AAAA"
json.dump(d, open(sys.argv[1], "w"), indent=2, sort_keys=True)
' "$WORK/root-tampered.json"
expect_refuse "a tampered root is refused" \
  "not valid" \
  env SPARKNET_STATE_DIR="$WORK/state-$CAND" "$PY" "$SIGNER" \
    --node-id "node-$CAND" --root "$WORK/root-tampered.json" \
    --key "$(node "$CAND")/cluster-keys/operational.ed25519" \
    --socket "$WORK/state-$CAND/signer/tampered.sock" \
    --ledger "$(node "$CAND")/master-node/blockchain/ledger.json"

step "the master-side registry publication script signs with the elected key"
mkdir -p "$WORK/state-$CAND/keys"
cp "$(node "$CAND")/cluster-keys/operational.ed25519" "$WORK/state-$CAND/keys/operational.ed25519"
cp "$(node "$CAND")/cluster-keys/operational.pub.b64" "$WORK/state-$CAND/keys/operational.pub.b64"
check "operational key present in the elected node's state dir" \
  test -f "$WORK/state-$CAND/keys/operational.ed25519"
if SPARKNET_STATE_DIR="$WORK/state-$CAND" PY="$PY" \
  bash "$(node "$CAND")/master-node/scripts/sparknet-registry-sign.sh" \
    --identity "$(node beta)/peer-node/manifests/node-identity.json" \
    --capabilities "telemetry,guard-apply" \
    --out "$WORK/registry-entry.json"; then
  ok "registry-sign produced a signed entry"
else
  bad "registry-sign failed"; exit 1
fi
check "a still-peer verifies the published entry by the root alone" \
  "$PY" -c '
import json, importlib.util, sys
shared = sys.argv[1]
spec = importlib.util.spec_from_file_location("authz", f"{shared}/sparknet-authz.py")
authz = importlib.util.module_from_spec(spec)
sys.modules["authz"] = authz
spec.loader.exec_module(authz)
entry_path, root_path = sys.argv[2], sys.argv[3]
entry = json.load(open(entry_path))
root = json.load(open(root_path))
unsigned = {k: v for k, v in entry.items() if k != "signature_b64"}
master_pub = authz.public_key_from_b64(root["master_pubkey"])
ok = authz.verify_signature(master_pub, entry["signature_b64"], authz.authorization_message(unsigned))
sys.exit(0 if ok else 1)
' "$REPO_ROOT/shared" "$WORK/registry-entry.json" "$WORK/root.json"

step "closeout"
kill "$SIGNER_PID" 2>/dev/null || true
wait "$SIGNER_PID" 2>/dev/null || true
SIGNER_PID=""
printf '\n   passed: %s   failed: %s\n   transcript: %s\n' "$PASS" "$FAIL" "$TRANSCRIPT"
[ "$FAIL" -eq 0 ]