# Multi-custodian 2-of-3 rekey / recovery ceremony (manual)

**Status:** `WAITING_FOR_THREE_CUSTODIANS`

**STOP for Cursor / automation:** do **not** perform rekey, seal, unseal, root revocation, or create a review ZIP from this runbook alone.

**Confirmed model:** `MULTI_CUSTODIAN_2_OF_3` (shares=3, threshold=2)

Cursor must never receive: passphrases, private keys, current/new unseal shares, PGP ciphertext of shares, tokens, RoleID, SecretID, or secret hashes.

---

## Roles (must be distinguished)

| Role | Function |
|------|----------|
| **Current unseal-key holders** | Hold the **existing** Shamir shares. Their quorum (**2 of 3**) **authorises** the rekey operation. |
| **New custodians** | Provide **new** PGP **public** keys that **encrypt** the newly generated shares. Receive and store the new shares. |

These sets of people **may differ**. Do **not** assume they are the same three humans.

No current or new share may pass through Cursor, source files, environment variables, shell arguments that embed share material, logs, or Git artifacts.

---

## Preconditions

- Vault healthy and unsealed
- Audit device `file/` enabled
- Limited operator `uhbse-operator-limited` (userpass) live verification PASS
- AppRole `uhbse-canonical-loader` intact
- Canonical DB seven tables at row count 0
- Initial root token still available (not revoked in this ceremony)
- Three **new** custodian public keys prepared in Vault-compatible form (below)

---

## 1. PGP input format for Vault `-pgp-keys` (mandatory)

### Forbidden as direct `-pgp-keys` input

- ASCII-armored files (`.asc` / `-----BEGIN PGP PUBLIC KEY BLOCK-----`)
- Private / secret key material
- Passing key data via Cursor chat

Vault does **not** accept ASCII armor on `-pgp-keys`. Use **binary** public-key export or **standard base64** of that binary (no armor headers).

### Required export (each new custodian, on their own workstation)

```bash
# Preferred for validation tooling: base64 of binary public key
gpg --export <FULL_FINGERPRINT> | base64 > custodian-N.gpg.b64

# Or binary:
gpg --export <FULL_FINGERPRINT> > custodian-N.gpg.bin
```

Example placement (git-ignored custody dir — **public material only**):

```text
ops/vault/operator-custody/custodians/custodian-1.gpg.b64
ops/vault/operator-custody/custodians/custodian-2.gpg.b64
ops/vault/operator-custody/custodians/custodian-3.gpg.b64
```

Private keys and passphrases stay on custodian workstations only — **never** in the project tree.

### Read-only validation (before rekey)

Run the project validator (no Vault mutation):

```bash
python3.12 -m human_simulator.stage03_alignment.pgp_public_key_validate \
  ops/vault/operator-custody/custodians/custodian-1.gpg.b64 \
  ops/vault/operator-custody/custodians/custodian-2.gpg.b64 \
  ops/vault/operator-custody/custodians/custodian-3.gpg.b64
```

Each file must PASS all of:

- parses as a valid PGP **public** key
- contains **no** secret/private key packets
- encoding is binary or standard base64 (ASCII armor → **reject**)
- full fingerprint matches the custodian-approved fingerprint
- three fingerprints are **distinct**
- key **supports encryption**
- key is **not expired** and **not revoked**
- file presents the expected public identity (UID present)

---

## 2. Raft snapshot (data protection only — not rekey rollback)

Before rekey, take a Raft snapshot for **Vault data** protection:

```bash
./ops/vault/scripts/raft-snapshot.sh
```

Store the snapshot outside Git per backup policy.

### What a snapshot is not

- A Raft snapshot **protects Vault data**; it does **not** substitute for a valid unseal quorum.
- Restoring a snapshot is a **separate disaster-recovery** operation.
- Restoration must **not** be attempted automatically during this ceremony.
- `vault operator raft snapshot restore -force` is **forbidden** in this ceremony.
- A sealed Vault **without** a working unseal quorum **cannot** rely on an ordinary snapshot restore as recovery from **lost new shares**.

### Normal abort path (before completion)

If anything fails before the new configuration is verified and activated:

```bash
vault operator rekey -cancel
```

Do **not** embed secret keys or tokens in command-line arguments. Use interactive prompts / stdin patterns from HashiCorp docs; keep `VAULT_TOKEN` in the environment only for the operator session.

---

## 3. Rekey with mandatory `-verify`

Initiate **only** with:

```text
-key-shares=3
-key-threshold=2
-pgp-keys=<three validated binary or base64 public-key files>
-verify
```

Record **both** nonces separately (values stay with operators — Cursor may only record that each was **present**, never the nonce strings in chat if policy forbids; sanitised evidence uses booleans):

| Nonce | Meaning |
|-------|---------|
| **Rekey operation nonce** | Issued when rekey is initialized |
| **Verification nonce** | Used to complete rekey verification after new shares are tested |

### Required flow

**a.** Initialize rekey with `-verify` and the three validated public-key files.  
**b.** Submit the **current** unseal quorum interactively (current share holders).  
**c.** Distribute the three **PGP-encrypted new shares** to their intended **new** custodians (out of band).  
**d.** Each new custodian decrypts their share **only** on their own workstation.  
**e.** Complete Vault **rekey verification** using **two independently held new shares** (verification nonce).  
**f.** Do **not** activate/finalize the new configuration unless verification **succeeds**.

### If verification fails

- Cancel the incomplete rekey: `vault operator rekey -cancel`
- **Retain** the current shares
- Leave **every** custody blocker **OPEN**
- Do **not** seal Vault as a “fix”
- Do **not** revoke the root token

---

## 4. Controlled seal / unseal drill (mandatory after successful rekey)

Without a real successful seal/unseal drill, these blockers remain **OPEN**:

- `vault_key_custody_decision_required`
- `pgp_keys_shared_keyring_empty_passphrase`
- `multi_custodian_separation_absent`

After **rekey verification PASS** and **rekey completion PASS**:

**a.** Confirm all three custodians independently received and securely stored their corresponding new encrypted/decrypted share.  
**b.** Confirm **no single person** controls two shares.  
**c.** Schedule a controlled maintenance window.  
**d.** Before seal: verify Agent path readiness, limited operator login, audit device, and backup/snapshot presence (data protection).  
**e.** **Seal** Vault.  
**f.** Require **two distinct custodians** to decrypt and submit **their own** shares.  
**g.** Verify Vault becomes **unsealed**.  
**h.** Verify limited operator login.  
**i.** Verify audit device.  
**j.** Run **two** Vault Agent restart/reauth cycles.  
**k.** Verify loader AppRole policy exactness.  
**l.** Verify PostgreSQL `SET ROLE`.  
**m.** Verify canonical row counts remain **0**.  
**n.** Verify raw DB connections and clinical reads remain **0**.

---

## 5. Old-share retirement

Do **not** retire or destroy old shares immediately after rekey output.

Permit retirement **only after all** of:

- rekey verification PASS  
- rekey completion PASS  
- three-custodian receipt confirmation  
- controlled 2-of-3 seal/unseal drill PASS  
- post-unseal Agent and operator verification PASS  

Record **no** old or new share values anywhere in the repo or Cursor transcripts.

---

## 6. Sanitised evidence (allowed vs forbidden)

### Allowed

- three full public-key fingerprints  
- `shares=3`, `threshold=2`  
- public-key validation booleans  
- rekey initiated / completed booleans  
- verification completed boolean (`PASS`/`FAIL`)  
- rekey operation nonce **recorded** (boolean) and verification nonce **recorded** (boolean)  
- two distinct custodian slots participated in unseal drill  
- seal/unseal drill PASS/FAIL  
- audit event identifiers that disclose no tokens or shares  
- timestamps and exit codes  

### Forbidden

- current or new unseal shares  
- PGP ciphertext of shares  
- private keys / passphrases  
- tokens / RoleID / SecretID / secret hashes  
- credential-bearing DSNs  

After a successful human ceremony, reply to Cursor with:

```text
confirm custody ceremony completed
```

plus only allowed sanitised fields. Documents or `status: CONFIRMED` **without** live ceremony evidence do **not** close custody blockers.

---

## Corrected ceremony sequence (summary)

1. Distinguish current share holders vs new custodians.  
2. Export three **binary/base64** public keys; validate (reject ASCII armor / private material).  
3. Raft snapshot for **data** protection (not rekey rollback).  
4. `vault operator rekey -key-shares=3 -key-threshold=2 -pgp-keys=... -verify`.  
5. Current quorum authorises; distribute encrypted **new** shares.  
6. Rekey **verification** with two new shares → only then complete.  
7. On verify failure: `-cancel`, keep current shares, blockers OPEN.  
8. Mandatory controlled **seal → 2-of-3 unseal** drill + post checks.  
9. Old-share retirement only after drill + post-unseal PASS.  
10. Sanitised evidence only → then Cursor may evaluate blocker closure.

---

## Project validators / tests

- `src/human_simulator/stage03_alignment/pgp_public_key_validate.py`  
- `src/human_simulator/stage03_alignment/custody_ceremony_validate.py`  
- `tests/test_custody_ceremony_v01_unit.py`  
