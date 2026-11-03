# Phase 9 — destructive recovery runbook

Status: **executed live on the peer 2026-11-01 03:12 UTC.**
Approved window: **Sunday 2026-11-08 02:00–05:00 CET**; on 2026-11-01 the operator explicitly moved execution to **2026-11-01 04:00–07:00 CET** (03:00–06:00 UTC).
This runbook is the procedure; the live result is `DoD: confirm: user`.

> [!danger] The destructive operation is a restore over a live role root.
> Do not run it outside the window, without a verified off-host archive, or
> without the exact phrase below. A wrong target is a data-loss event.

## Execution record 2026-11-01

- Frozen live archive `peer-0001-live.tar.gz`: 222 files, sha256
  `29cfe73d07e50b52e2119f498c6f28dc2d0bdc5f31476afed9990cdef2d8afe8`.
- User-vault archive `user-vaults-0001.tar.gz`: 147 files, sha256
  `c59b047c0d56699b32a4830c31a7b1ee161786b5e8dfed3f3c132a2e4bbe665f`;
  **not** overwritten by this proof.
- The first extraction hit `chattr +i` on the managed
  `.state/wireguard/wg1.conf`; it was lifted, the verified archive was restored
  again, and the flag was re-applied.
- Sentinel `00_System/phase9-sentinel.md` restored with the manifest hash
  `c4ec2970…`; receipt is in the role root.
- The restore exposed a pre-existing wrong registry entry (placeholder WG key).
  Registry sequence 5 corrected it to fingerprint `84bd134e…`; the WebUI grant
  was re-minted and the tool server re-registered.
- Post-restore ownership fix: `00_System/vault-health.json` restored root-owned
  and was changed to `raxxar:raxxar`; public key files were set to 0600 to
  satisfy `keys-check`.
- Verified: all peer services active, WebUI 200 with 1 tool server, vault-health
  healthy, `make validate` pass, `keys-check` clean, provenance 11/9 valid/2
  pending, shares closed.

## Preflight record 2026-10-31

The operator supplied `/mnt/backup/phase9` on **agx32** (`root:root`, 0700).
It holds root-only 0600 preflight archives and a `SHA256SUMS`:

```
efbf0383...  peer-0001.tar.gz
42401015...  master-0002.tar.gz
17beb321...  master-state-0002.tar.gz
```

All three verified and rehearsed (delete-and-restore a sampled file) on agx32.
The peer archive is off-host relative to agx64. The Master archives are on the
same host they would restore, so before the Master destructive step copy them
to an external/other off-host target or record an explicit operator acceptance
of same-host risk. These are preflight archives, not the frozen-window snapshot;
take a fresh snapshot after the T0 freeze.

## Trigger and authority

The operator must type this phrase in the shell that runs `restore --live`:

```
I ACCEPT PHASE 9 DESTRUCTIVE RESTORE ON AGX64 AGX32
```

The tool refuses any other phrase, refuses `/` and `$HOME` as targets, and
refuses `--live` outside the current window (2026-11-01 03:00–06:00 UTC). The phrase is not a password; it is the
human decision the plan requires. The signer is not involved and this exercise
grants no authority.

## Scope

| Host | Role root | Separate state |
|---|---|---|
| `agx64` `sparknet-node-0001` | `/home/raxxar/sparknet/peer-node` | `/srv/sparknet/knowledge/peer-*` (user vaults) are separate; back them up but this proof does not overwrite them |
| `agx32` `sparknet-node-0002` | `/home/raxxar/sparknet/master-node` | `/home/raxxar/.local/state/sparknet/master-node` |
| `agx32` read-only artifacts | `/srv/sparknet/share`, `/srv/sparknet/git` | re-creatable; not in the destructive proof |

The tool excludes `.state/qdrant` and `.state/chroma` (derived, rebuildable) and caches. It includes
`.env`, `.state/keys`, manifests, ledger, sessions and shared-share state. The
archive therefore contains key material: keep it on encrypted/root-only media,
mode 0600, never in the vault and never in git.

Docker data is snapshotted separately because it is not under the role root:

```sh
# WebUI DB (stop the container first; see freeze below)
docker cp sparknet-webui:/app/backend/data/webui.db /backup/phase9/webui.db
# Qdrant volume (agx64; Master uses its own store)
docker run --rm -v sparknet-qdrant-data:/data -v /backup/phase9:/backup alpine \
  tar czf /backup/qdrant-data.tar.gz -C /data .
```

Restore is the reverse (`docker cp` back, or extract the volume tar into a fresh
volume). Re-embedding is always possible from the vault; the DB backup is for
speed, not for authority.

## T-24h preflight

1. Read `MEMORY.md` and today's session file. Confirm the window and phrase with
   the user; record the confirmation.
2. Confirm both hosts are healthy: `make vault-health`, `make -C peer-node
   validate`, `make -C master-node validate`, `make contract-test`.
3. Check free space: the peer archive is small; the Master state can hold keys,
   ledger and spool. Use `/mnt/backup/phase9` on an encrypted/root-only device.
4. Copy `scripts/sparknet-recovery.py` to both hosts and confirm `--help`.
5. Re-run the local rehearsal: `make recovery-rehearse` (snapshot, delete one
   file in a temp extraction, restore, verify). It must print `ok`.
6. Record the current registry sequence, Git HEAD, service list and open shares.

## T0 freeze

Stop writers before snapshotting. On each host, stop the sparknet units that
write, in this order:

```sh
# peer
systemctl --user stop sparknet-dispatch-bridge.service sparknet-share-serve.service \
  sparknet-telemetry-push.timer sparknet-liveness-monitor.service \
  sparknet-checkpoint-anchor.timer sparknet-vault-health.timer
# master
sudo systemctl stop sparknet-master-vector.service sparknet-file-share.service \
  sparknet-nat-status.service sparknet-git-daemon.service \
  sparknet-registry-deliver.timer sparknet-rfi-responder.service
docker stop sparknet-webui
```

Do not stop the WireGuard anchor until the archives are off-host; an overlay
outage makes recovery harder, not easier. Do not stop the signer for a peer
restore; for a Master restore, stop it **after** the archive is verified and
before extracting the state directory.

## Snapshot and verify

Use a separate archive per root, not one giant archive:

```sh
# on agx64 (sudo is required: .state/wireguard/wg1.conf is root-only)
sudo scripts/sparknet-recovery.py snapshot \
  --root /home/raxxar/sparknet/peer-node \
  --out /mnt/backup/phase9/peer-0001.tar.gz
sudo scripts/sparknet-recovery.py verify /mnt/backup/phase9/peer-0001.tar.gz

# on agx32
sudo scripts/sparknet-recovery.py snapshot \
  --root /home/raxxar/sparknet/master-node \
  --out /mnt/backup/phase9/master-0002.tar.gz
sudo scripts/sparknet-recovery.py snapshot \
  --root /home/raxxar/.local/state/sparknet/master-node \
  --out /mnt/backup/phase9/master-state-0002.tar.gz
sudo scripts/sparknet-recovery.py verify /mnt/backup/phase9/master-0002.tar.gz
sudo scripts/sparknet-recovery.py verify /mnt/backup/phase9/master-state-0002.tar.gz
```

Also capture the Docker DB/volume files above, and copy every archive **off the
host** before the destructive step. A backup on the disk being restored is not a
backup. Record the archive SHA-256 in the transcript.

## Destructive proof (peer first)

The approved destructive proof is a full restore of the **peer role root** from
the verified archive. The Master is restored only if the peer proof passes and
the operator explicitly repeats the confirmation.

1. Create a sentinel before the snapshot above: `00_System/phase9-sentinel.md`
   with a one-time nonce. It must be in the verified archive.
2. Delete the sentinel from the live peer root. This proves the next step is
   not a no-op.
3. Run the live restore. The target is the role root, `--live` enforces the
   window, and the phrase is typed:

   ```sh
   sudo scripts/sparknet-recovery.py restore \
     /mnt/backup/phase9/peer-0001.tar.gz \
     --target /home/raxxar/sparknet/peer-node \
     --live \
     --confirm 'I ACCEPT PHASE 9 DESTRUCTIVE RESTORE ON AGX64 AGX32'
   ```

4. Verify the sentinel is back, the archive manifest matches, and no file was
   taken from another host. The tool writes `.sparknet-restore-receipt.json`
   into the target; keep it as evidence.

For the Master, repeat the same procedure with the two Master archives and the
same phrase, after `systemctl stop sparknet-master-signer.service`. The
operational key is in the state archive; do not start the signer until the
restored state verifies.

## Verification after restore

On the restored host, in this order:

1. `make -C peer-node validate` or `make -C master-node validate`; the Master
   ledger verifies and no key material is in the vault.
2. `make vault-health`; `make keys-check`; `make shims-check`.
3. Start the units in reverse order; assert `systemctl is-active` for every one.
4. Peer: control socket `state` returns the pre-freeze shares; WebUI `8181`
   health is 200; RFI loop and telemetry timers resume.
5. Master: 4220 `git ls-remote`, 4221 signed file list, 4222 signed status,
   4223 signed health; registry sequence is not rolled back.
6. The restored peer can still verify the signed registry and its own signed
   notes; the user key is present and mode 0600.
7. Record every check in the dated transcript under `/mnt/log/`.

## Rollback

If a restore or post-restore check fails:

1. Stop the restored units.
2. Re-extract the **same verified archive** to the same target; do not use
   `rsync --delete` and do not repair by hand. If the archive is the problem,
   use the off-host copy.
3. For the Master, restore the state archive before starting the signer; a
   signer pointed at a half-restored state must stay stopped.
4. If the user key is missing or a signature fails, stop and escalate. Do not
   re-key or rewrite ledger history as a recovery shortcut.
5. Start the last known-good services and record the failure. The window can
   close with the peer restored and the Master untouched; that is a valid
   partial result, not a reason to force the second host.

## Close-out

The exercise is complete only when the transcript, archive hashes, sentinel and
receipts are filed and the operator confirms:

- [ ] peer restored and verified; services active
- [ ] Master restored only if attempted; signer/ledger/registry verified
- [ ] no key or archive left in a vault or git
- [ ] rollback archive retained
- [ ] `DoD: confirm: user` recorded with the date and host
