#!/bin/bash
# ntp_sync.sh <target_ip> — set WSL/local clock to target DC time via NTP (UDP 123).
# Use before Kerberos operations if nmap/smb2-time shows >5 min clock skew.
set -euo pipefail
IP="${1:?target DC IP}"
TGT=$(python3 - <<PY
import socket, struct
s=socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.settimeout(5)
p=bytearray(48); p[0]=0x1B
s.sendto(p,("$IP",123))
d,_=s.recvfrom(48)
print(int(struct.unpack("!I",d[40:44])[0] - 2208988800))
PY
)
date -s "@$TGT" >/dev/null
date -u
