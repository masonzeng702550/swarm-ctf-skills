#!/bin/bash
# build_wsus_pem.sh <cert_file> <key_file> [out_combined]
# wsuks's --tls-cert expects cert + key concatenated in one PEM file.
set -euo pipefail
CERT="${1:?cert PEM/DER}"
KEY="${2:?private key PEM}"
OUT="${3:-/tmp/wsus-mitm/wsus_combined.pem}"

# If cert is DER-encoded, convert to PEM first
if ! head -1 "$CERT" | grep -q BEGIN; then
  echo "[*] converting DER -> PEM"
  openssl x509 -inform DER -in "$CERT" -out /tmp/wsus.pem
  CERT=/tmp/wsus.pem
fi

cat "$CERT" "$KEY" > "$OUT"
echo "[+] combined PEM: $OUT"
openssl x509 -in "$OUT" -noout -subject -issuer -dates | sed 's/^/    /'
