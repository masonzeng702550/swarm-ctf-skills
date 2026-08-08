#!/bin/bash
# Usage: connectivity.sh <DC_IP>
IP="${1:?need DC IP}"
for P in 53 80 88 135 139 389 443 445 464 593 636 3268 3389 5985 5986 8530 8531 9389 47001 1433 5432 21 22 25 110 143; do
  nc -zvw 2 "$IP" "$P" 2>&1 | grep -E "succeeded|open" | head -1
done
