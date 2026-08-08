#!/bin/bash
# generate_csr.sh — produce RSA key + CSR with target SAN
# Usage: generate_csr.sh <cn> [san1 [san2 ...]]
# Example: generate_csr.sh wsus.example.com wsus.example.com dc01.example.com
set -euo pipefail
CN="${1:?need CN (e.g. wsus.example.com)}"
shift
SANS=("$@")
[ ${#SANS[@]} -eq 0 ] && SANS=("$CN")

OUT_DIR="${OUT_DIR:-/tmp/wsus-mitm}"
mkdir -p "$OUT_DIR"

openssl genrsa -out "$OUT_DIR/wsus.key" 2048 2>/dev/null

{
  echo "[req]"
  echo "default_bits = 2048"
  echo "prompt = no"
  echo "distinguished_name = dn"
  echo "req_extensions = req_ext"
  echo "[dn]"
  echo "CN = $CN"
  echo "[req_ext]"
  echo "subjectAltName = @alt_names"
  echo "[alt_names]"
  i=1
  for s in "${SANS[@]}"; do
    echo "DNS.$i = $s"
    i=$((i+1))
  done
} > "$OUT_DIR/wsus.csr.conf"

openssl req -new -key "$OUT_DIR/wsus.key" -out "$OUT_DIR/wsus.csr" -config "$OUT_DIR/wsus.csr.conf"
echo "[+] key=$OUT_DIR/wsus.key  csr=$OUT_DIR/wsus.csr"
echo "[+] subject: $(openssl req -in $OUT_DIR/wsus.csr -noout -subject)"
echo "[+] SANs:    $(openssl req -in $OUT_DIR/wsus.csr -noout -ext subjectAltName 2>/dev/null | grep DNS)"
