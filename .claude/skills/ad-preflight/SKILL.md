---
description: "Environment readiness + gotcha checklist for attacking Windows Active Directory targets from a Linux attacker host (especially WSL Kali). Use when starting an AD engagement: CTF box, lab, or authorized pentest where a domain/DC is known. Provides TUN/MTU fixes, tool install check, krb5.conf template, clock sync, and port matrix. Removes ~30–60 min of 'why is Kerberos hanging' debugging. Platform-agnostic — HTB/THM/OSCP quirks noted but not required."
---

# /ad-preflight — Windows AD attacker-host readiness

**Purpose**: Cut dead time caused by environment issues before actual attack. Checklist + ready-to-paste snippets, **not** a prescribed sequence.

## Use when

- Target known to expose Windows AD (LDAP/Kerberos/SMB/WinRM ports open, domain banner seen)
- Fresh attacker host / after VPN reconnect / after target reset
- Kerberos auth mysteriously hanging / timing out / "cannot contact KDC"

## Skip when

- Target is Linux / pure web / standalone Windows (no domain)
- Environment already working — don't over-engineer

## The Five Gotchas

### 1. WSL2 TUN driver + VPN MTU

```bash
wsl -d kali-linux -u root -- bash -c '
  lsmod | grep -q "^tun" || modprobe tun
  [ -c /dev/net/tun ] || (mkdir -p /dev/net && mknod /dev/net/tun c 10 200 && chmod 600 /dev/net/tun)
  ip link set tun0 mtu 1200 2>/dev/null
  echo "tun=$(ls -l /dev/net/tun 2>&1 | head -1)  mtu=$(ip link show tun0 2>&1 | grep -o "mtu [0-9]*" | head -1)"
'
```

**Why MTU 1200?** Kerberos TGS-REP with PAC often exceeds 1500 B. Over VPN with DF bit, fragmented UDP gets dropped; some TCP paths also drop. 1200 is safe margin.

**Symptom when wrong**: `kinit` succeeds but `kvno` / `getST.py` / `nxc -k` / SASL GSSAPI bind **hang forever** with no error. Quick test: if `kinit` works but `kvno krbtgt/<REALM>` hangs ≥10s, lower MTU.

Non-WSL Linux: usually fine unless over the same kind of VPN.

### 2. Tool availability (install gaps only)

```bash
wsl -d kali-linux -u root -- bash -c '
  for t in impacket-getTGT nxc bloodhound-python certipy-ad coercer dnstool ldapsearch kinit nft; do
    command -v $t >/dev/null || echo "MISSING: $t"
  done
'
```

Standard apt set:
```
python3-impacket netexec bloodhound.py certipy-ad coercer krbrelayx \
  responder ldap-utils krb5-user libsasl2-modules-gssapi-mit nftables tmux
```

Extras via pipx (not in apt): `wsuks`, `bloodyAD`.

### 3. /etc/hosts entries

Minimum: DC FQDN + any hostname you'll later spoof via ADIDNS.
```bash
wsl -d kali-linux -u root -- bash -c "
  sed -i '/<DOMAIN>/d' /etc/hosts
  echo '<DC_IP> dc01.<DOMAIN> <DOMAIN> dc01' >> /etc/hosts
"
```

### 4. krb5.conf template

Save to `/etc/krb5.conf` (replace `<REALM>` = domain uppercased):
```ini
[libdefaults]
    default_realm = <REALM>
    dns_lookup_realm = false
    dns_lookup_kdc = false
    ticket_lifetime = 24h
    forwardable = true
    rdns = false
    udp_preference_limit = 1

[realms]
    <REALM> = {
        kdc = dc01.<domain>
        admin_server = dc01.<domain>
    }

[domain_realm]
    .<domain> = <REALM>
    <domain> = <REALM>
```

### 5. Clock sync to target DC

Kerberos silently fails if skew > 5 min. Ways to pull DC time:
- `nmap -p 445 --script smb2-time <DC>` (no auth)
- NTP via UDP 123 if open (one-liner below)
- SMB2 header from `nxc smb <DC>` banner

```bash
wsl -d kali-linux -u root -- bash -c '
python3 - <<PY
import socket, struct, os
s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.settimeout(5)
p=bytearray(48); p[0]=0x1B
s.sendto(p,("<DC_IP>",123)); d,_=s.recvfrom(48)
os.system(f"date -s @{struct.unpack(\"!I\",d[40:44])[0]-2208988800}")
PY
date -u
'
```

## Connectivity matrix (5-second sanity)

```bash
wsl -d kali-linux -u root -- bash -c '
for P in 53 80 88 135 139 389 443 445 464 593 636 3268 3389 5985 5986 8530 8531 9389 47001 1433; do
  nc -zvw 2 <DC_IP> $P 2>&1 | grep -E "succeeded|open" | head -1
done
'
```

Inference hints (just signals, not decisions):

| Port | Signal |
|---|---|
| 88/389/445 | AD domain confirmed |
| 5985 | WinRM (only works if user in Remote Management Users) |
| 8530/8531 | WSUS present — potential target for `/wsus-mitm` |
| 3389 | RDP — lateral / GUI angle |
| 5986 | WinRM HTTPS (channel binding may complicate relay) |
| 1433/1434 | SQL — separate attack surface |
| 80/443 | Web app / ADCS web enroll / IIS |
| 53 | DNS — ADIDNS spoofing potentially viable |

## Attack-surface cheat sheet (signals → candidate angles)

Use as hints, not a decision tree:

| Signal | Possible angle |
|---|---|
| Readable `\Logs` / custom share with log files | Credential hunt (grep for passwords, dates, base64) |
| LDAP user enum shows `$`-suffix + BloodHound GenericWrite on it | `/gmsa-takeover` |
| WU registry (`HKLM\Software\Policies\Microsoft\Windows\WindowsUpdate`) points to hostname not resolvable | `/wsus-mitm` via ADIDNS |
| `msDS-KeyCredentialLink` writable on target | Shadow Credentials (certipy) |
| ADCS template with "Enrollee Supplies Subject" + ClientAuth EKU | ESC1 (certipy) |
| ADCS Web Enrollment on port 80/443 | ESC8 (ntlmrelayx → AD CS) |
| Computer account w/ `TrustedToAuthForDelegation` | S4U2Self/S4U2Proxy |
| Readable SYSVOL w/ `.xml` in Policies dir | GPP cpassword (gpp-decrypt) |
| Service accounts with SPN | Kerberoast (GetUserSPNs.py) |
| User w/ `DONT_REQ_PREAUTH` flag | AS-REProast |
| DC LSA secret dumpable | DCSync via DRSUAPI |

## Platform-specific notes (small, optional)

**HackTheBox**:
- TUN usually needs `mknod` after WSL reboot.
- Box reset → new IP → update `/etc/hosts`.
- Some credentials in logs use **year rotation**: the literal password in a `2025`-dated file may actually be the year+1 value on the live box. If a found password fails Kerberos PREAUTH with correct format, try current/next year.
- Reset wipes your state (ADIDNS writes, gMSA membership changes, locked DLLs) — plan atomic payloads accordingly.

**TryHackMe AttackBox**: TUN usually pre-configured; skip gotcha #1.

**OSCP / Proving Grounds**: similar to HTB; sometimes MTU 1400 works instead of 1200.

## Flexibility reminder

These are lessons-learned signals, **not a recipe**. Skip anything already handled. If Kerberos works first try — move on, don't run the checklist for its own sake.

## Scripts

- `scripts/ntp_sync.sh` — pull DC time via NTP + set system clock
- `scripts/connectivity.sh` — port matrix (takes `<DC_IP>` as `$1`)
- `scripts/install_tools.sh` — apt + pipx idempotent installer
