#!/bin/bash
# install_tools.sh — idempotent install of the standard AD pentest tool set on Kali.
# Run as root inside WSL Kali.
set -u
export DEBIAN_FRONTEND=noninteractive

APT_PKGS=(
  python3-impacket netexec bloodhound.py certipy-ad coercer krbrelayx
  responder ldap-utils krb5-user libsasl2-modules-gssapi-mit nftables
  tmux evil-winrm smbclient curl python3-pip pipx openssl
)

MISSING=()
for p in "${APT_PKGS[@]}"; do
  dpkg -l "$p" 2>/dev/null | grep -q "^ii" || MISSING+=("$p")
done

if [ ${#MISSING[@]} -gt 0 ]; then
  echo "[*] apt-get install: ${MISSING[*]}"
  apt-get install -y --no-install-recommends "${MISSING[@]}"
else
  echo "[+] all apt packages present"
fi

# pipx tools (not in apt)
for p in wsuks bloodyAD; do
  if ! command -v "$p" >/dev/null; then
    echo "[*] pipx install $p"
    pipx install "$p" || true
  fi
done

# PATH hint
grep -q "/.local/bin" ~/.bashrc 2>/dev/null || echo 'export PATH=$PATH:/root/.local/bin' >> ~/.bashrc

echo "[+] done. Confirm: nxc impacket-getTGT certipy-ad coercer dnstool wsuks"
